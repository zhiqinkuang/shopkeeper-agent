"""执行 120 问数场景：先用 gold SQL 打数仓，再按需对比智能体结果。"""

import argparse
import asyncio
import json
import time
from contextlib import AsyncExitStack
from decimal import Decimal

from elasticsearch import AsyncElasticsearch
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from app.agent.answer_grounding import answer_is_grounded
from app.agent.context import DataAgentContext
from app.agent.graph import query_graph
from app.clients.embedding_client_manager import EmbeddingClientManager
from app.clients.mysql_client_manager import MySQLClientManager
from app.conf.app_config import DBConfig, app_config
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.scripts.query_scenario_catalog import QueryScenario, build_query_scenarios

# 40 条抽检：覆盖聚合、过滤、分组、排序、交叉和空结果，并固定回归 B011
AGENT_SAMPLE_IDS = (
    "G001",
    "G003",
    "G006",
    "G008",
    "R001",
    "R006",
    "R009",
    "R014",
    "R015",
    "C001",
    "C011",
    "C012",
    "C014",
    "C016",
    "P001",
    "P007",
    "P013",
    "P014",
    "T001",
    "T002",
    "T006",
    "T007",
    "T010",
    "T012",
    "B001",
    "B003",
    "B005",
    "B011",
    "B015",
    "X001",
    "X003",
    "X008",
    "K001",
    "K002",
    "K011",
    "K012",
    "Z001",
    "Z002",
    "Z003",
    "Z004",
)


def select_scenarios(ids: list[str] | tuple[str, ...] | None = None) -> list[QueryScenario]:
    catalog = {item["id"]: item for item in build_query_scenarios()}
    if ids is None:
        return [catalog[item_id] for item_id in catalog]
    missing = [item_id for item_id in ids if item_id not in catalog]
    if missing:
        raise KeyError(f"未知场景: {missing}")
    return [catalog[item_id] for item_id in ids]


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows_are_empty(rows: list[dict]) -> bool:
    if not rows:
        return True
    if len(rows) == 1:
        return all(value is None for value in rows[0].values())
    return False


def _normalize_cell(value):
    value = _jsonable(value)
    if isinstance(value, float):
        return round(value, 2)
    if value is None:
        return None
    if isinstance(value, (int, str)):
        return value
    return str(value).strip()


def _cells_by_kind(rows: list[dict]) -> tuple[list, list]:
    numbers = []
    texts = []
    for row in rows:
        for value in row.values():
            cell = _normalize_cell(value)
            if cell is None:
                continue
            if isinstance(cell, (int, float)):
                numbers.append(round(float(cell), 2))
            else:
                texts.append(str(cell).strip())
    return sorted(numbers), sorted(texts)


def results_match(gold_rows: list[dict], agent_rows: list[dict]) -> bool:
    """比较查询结果的取值，忽略列名和列顺序。"""
    if _rows_are_empty(gold_rows) and _rows_are_empty(agent_rows):
        return True
    gold_numbers, gold_texts = _cells_by_kind(gold_rows)
    agent_numbers, agent_texts = _cells_by_kind(agent_rows)
    if (gold_numbers, gold_texts) == (agent_numbers, agent_texts):
        return True
    # 排名类问题常只返回维度，允许缺少 gold 里的辅助度量列
    return bool(gold_texts) and gold_texts == agent_texts and not agent_numbers


async def eval_gold_sql(scenarios: list[QueryScenario]) -> list[dict]:
    """用 gold SQL 验证教学数仓里确有对应数据。"""
    dw_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "dw")
    )
    dw_manager.init()
    results = []
    try:
        async with dw_manager.session_factory() as session:
            for scenario in scenarios:
                started = time.perf_counter()
                try:
                    result = await session.execute(text(scenario["gold_sql"]))
                    rows = [
                        {key: _jsonable(value) for key, value in row.items()}
                        for row in result.mappings().all()
                    ]
                    empty = _rows_are_empty(rows)
                    passed = empty == scenario["expect_empty"]
                    error = None
                except Exception as exc:
                    rows = []
                    empty = True
                    passed = False
                    error = str(exc)
                results.append(
                    {
                        "id": scenario["id"],
                        "category": scenario["category"],
                        "question": scenario["question"],
                        "passed": passed,
                        "expect_empty": scenario["expect_empty"],
                        "empty": empty,
                        "row_count": len(rows),
                        "sample": rows[:3],
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        "error": error,
                    }
                )
    finally:
        await dw_manager.close()
    return results


async def eval_agent(scenarios: list[QueryScenario]) -> list[dict]:
    """跑问数图，按结果取值对比 gold SQL，不要求 SQL 字面量一致。"""
    meta_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "meta")
    )
    dw_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "dw")
    )
    embedding_manager = EmbeddingClientManager(app_config.embedding)
    qdrant_client = AsyncQdrantClient(
        url="http://127.0.0.1:16333",
        trust_env=False,
        check_compatibility=False,
    )
    es_client = AsyncElasticsearch("http://127.0.0.1:19200")
    results = []
    async with AsyncExitStack() as exit_stack:
        embedding_manager.init()
        exit_stack.push_async_callback(embedding_manager.close)
        exit_stack.push_async_callback(qdrant_client.close)
        exit_stack.push_async_callback(es_client.close)
        meta_manager.init()
        exit_stack.push_async_callback(meta_manager.close)
        dw_manager.init()
        exit_stack.push_async_callback(dw_manager.close)
        meta_session = await exit_stack.enter_async_context(meta_manager.session_factory())
        dw_session = await exit_stack.enter_async_context(dw_manager.session_factory())
        context = DataAgentContext(
            column_qdrant_repository=ColumnQdrantRepository(qdrant_client),
            embedding_client=embedding_manager.client,
            metric_qdrant_repository=MetricQdrantRepository(qdrant_client),
            value_es_repository=ValueESRepository(es_client),
            meta_mysql_repository=MetaMySQLRepository(meta_session),
            dw_mysql_repository=DWMySQLRepository(dw_session),
        )
        for scenario in scenarios:
            started = time.perf_counter()
            merged = {"query": scenario["question"]}
            error = None
            gold_rows = []
            try:
                gold_result = await dw_session.execute(text(scenario["gold_sql"]))
                gold_rows = [
                    {key: _jsonable(value) for key, value in row.items()}
                    for row in gold_result.mappings().all()
                ]
                async for update in query_graph.astream(
                    {"query": scenario["question"]},
                    context=context,
                    stream_mode="updates",
                ):
                    for node_update in update.values():
                        if isinstance(node_update, dict):
                            merged.update(node_update)
            except Exception as exc:
                error = str(exc)

            if error is None and merged.get("execution_result") is None:
                error = merged.get("error") or "智能体未返回查询结果"

            agent_rows = [
                {key: _jsonable(value) for key, value in row.items()}
                for row in (merged.get("execution_result") or [])
            ]
            result_hit = results_match(gold_rows, agent_rows)
            answer = (merged.get("answer") or "").strip()
            answer_grounded = bool(answer) and answer_is_grounded(
                answer, agent_rows, scenario["question"]
            )
            tables = {table["name"] for table in merged.get("table_infos") or []}
            metrics = {metric["name"] for metric in merged.get("metric_infos") or []}
            table_hit = set(scenario["expected_tables"]) <= tables
            metric_hit = set(scenario["expected_metrics"]) <= metrics
            item = {
                "id": scenario["id"],
                "category": scenario["category"],
                "question": scenario["question"],
                "passed": error is None and result_hit and answer_grounded,
                "result_hit": result_hit,
                "answer_grounded": answer_grounded,
                "table_hit": table_hit,
                "metric_hit": metric_hit,
                "expected_tables": scenario["expected_tables"],
                "actual_tables": sorted(tables),
                "expected_metrics": scenario["expected_metrics"],
                "actual_metrics": sorted(metrics),
                "gold_sample": gold_rows[:3],
                "agent_sample": agent_rows[:3],
                "answer": answer,
                "sql": merged.get("sql"),
                "elapsed_s": round(time.perf_counter() - started, 3),
                "error": error,
            }
            if not item["passed"]:
                item["diff"] = {
                    "gold": gold_rows[:5],
                    "agent": agent_rows[:5],
                    "sql": merged.get("sql"),
                    "answer": answer,
                    "answer_grounded": answer_grounded,
                }
            results.append(item)
            print(
                f"{item['id']} passed={item['passed']} "
                f"tables={item['actual_tables']} metrics={item['actual_metrics']} "
                f"{item['elapsed_s']}s",
                flush=True,
            )
    return results


def _summarize(title: str, results: list[dict]) -> dict:
    passed = sum(1 for item in results if item["passed"])
    by_category: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = by_category.setdefault(item["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if item["passed"]:
            bucket["passed"] += 1
    summary = {
        "title": title,
        "passed": passed,
        "total": len(results),
        "by_category": by_category,
        "failed_ids": [item["id"] for item in results if not item["passed"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser(description="评估 120 问数场景")
    parser.add_argument("--agent", action="store_true", help="同时跑智能体结果对比")
    parser.add_argument("--sample", action="store_true", help="只跑抽检样本")
    parser.add_argument("--ids", default="", help="逗号分隔的场景 ID")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    args = parser.parse_args()

    if args.ids:
        scenarios = select_scenarios(
            [item_id.strip() for item_id in args.ids.split(",") if item_id.strip()]
        )
    elif args.sample:
        scenarios = select_scenarios(AGENT_SAMPLE_IDS)
    else:
        scenarios = build_query_scenarios()
    if args.limit > 0:
        scenarios = scenarios[: args.limit]

    gold_results = await eval_gold_sql(scenarios)
    gold_summary = _summarize("gold_sql", gold_results)
    ok = gold_summary["passed"] == gold_summary["total"]
    if args.agent:
        agent_results = await eval_agent(scenarios)
        agent_summary = _summarize("agent_result", agent_results)
        print(
            json.dumps(
                {
                    "agent_summary": agent_summary,
                    "note": "对比结果取值，不要求 SQL 字面量一致",
                },
                ensure_ascii=False,
            )
        )
        ok = ok and agent_summary["passed"] == agent_summary["total"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
