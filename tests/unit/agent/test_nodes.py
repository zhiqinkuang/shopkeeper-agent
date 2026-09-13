from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.runnables import RunnableLambda

from app.agent.graph import route_after_validation
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import (
    ColumnInfoState,
    DateInfoState,
    DBInfoState,
    MetricInfoState,
    TableInfoState,
)
from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.prompt.prompt_loader import load_prompt
from tests.conftest import FakeEmbeddings

pytestmark = pytest.mark.unit


def _runtime(context=None):
    return SimpleNamespace(stream_writer=lambda _: None, context=context)


def test_load_prompt_reads_filter_table_template():
    content = load_prompt("filter_table_info")

    assert "{query}" in content
    assert "{table_infos}" in content
    generate_sql_prompt = load_prompt("generate_sql")
    assert "{query}" in generate_sql_prompt
    assert "```sql" in generate_sql_prompt
    assert "{error}" in load_prompt("correct_sql")


async def test_extract_keywords_keeps_query_and_business_terms():
    events = []
    result = await extract_keywords(
        {"query": "统计华北地区的销售总额"},
        SimpleNamespace(stream_writer=events.append, context=None),
    )

    assert "统计华北地区的销售总额" in result["keywords"]
    assert any("销售" in keyword or "华北" in keyword for keyword in result["keywords"])
    assert events[0] == {"type": "progress", "step": "抽取关键词", "status": "running"}
    assert events[-1] == {"type": "progress", "step": "抽取关键词", "status": "success"}


async def test_recall_nodes_deduplicate_and_reject_invalid_llm_output(mocker):
    column = ColumnInfo(
        "fact_order.order_amount",
        "order_amount",
        "decimal",
        "measure",
        [],
        "订单金额",
        [],
        "fact_order",
    )
    metric = MetricInfo(
        "GMV",
        "GMV",
        "成交额",
        [column.id],
        ["销售总额"],
        "SUM(fact_order.order_amount)",
    )
    value = ValueInfo("v", "华北", "dim_region.region_name")
    runtime = _runtime(
        SimpleNamespace(
            embedding_client=FakeEmbeddings(),
            column_qdrant_repository=SimpleNamespace(
                search=AsyncMock(return_value=[column, column])
            ),
            metric_qdrant_repository=SimpleNamespace(
                search=AsyncMock(return_value=[metric, metric])
            ),
            value_es_repository=SimpleNamespace(
                search=AsyncMock(return_value=[value, value])
            ),
        )
    )
    state = {"query": "统计华北地区的销售总额", "keywords": ["销售总额"]}
    mocker.patch(
        "app.agent.nodes.recall_column.llm",
        RunnableLambda(lambda _: '["销售金额"]'),
    )
    mocker.patch(
        "app.agent.nodes.recall_metric.llm",
        RunnableLambda(lambda _: '["GMV"]'),
    )
    mocker.patch(
        "app.agent.nodes.recall_value.llm",
        RunnableLambda(lambda _: '["华北"]'),
    )

    column_result = await recall_column(state, runtime)
    metric_result = await recall_metric(state, runtime)
    value_result = await recall_value(state, runtime)

    assert [item.id for item in column_result["retrieved_column_infos"]] == [column.id]
    assert [item.id for item in metric_result["retrieved_metric_infos"]] == [metric.id]
    assert [item.id for item in value_result["retrieved_value_infos"]] == [value.id]

    mocker.patch(
        "app.agent.nodes.recall_column.llm",
        RunnableLambda(lambda _: '{"bad": true}'),
    )
    mocker.patch(
        "app.agent.nodes.recall_metric.llm",
        RunnableLambda(lambda _: "1"),
    )
    mocker.patch(
        "app.agent.nodes.recall_value.llm",
        RunnableLambda(lambda _: '{"bad": true}'),
    )
    with pytest.raises(ValueError, match="字段召回扩展词"):
        await recall_column(state, runtime)
    with pytest.raises(ValueError, match="指标召回扩展词"):
        await recall_metric(state, runtime)
    with pytest.raises(ValueError, match="字段取值召回扩展词"):
        await recall_value(state, runtime)


async def test_merge_retrieved_info_completes_fields_and_keeps_upstream_intact():
    region = ColumnInfo(
        "dim_region.region_name",
        "region_name",
        "varchar",
        "dimension",
        ["华东"],
        "地区名称",
        ["地区"],
        "dim_region",
    )
    amount = ColumnInfo(
        "fact_order.order_amount",
        "order_amount",
        "decimal",
        "measure",
        [],
        "订单金额",
        [],
        "fact_order",
    )
    keys = {
        "dim_region": ColumnInfo(
            "dim_region.region_id",
            "region_id",
            "bigint",
            "primary_key",
            [],
            "地区主键",
            [],
            "dim_region",
        ),
        "fact_order": ColumnInfo(
            "fact_order.region_id",
            "region_id",
            "bigint",
            "foreign_key",
            [],
            "地区外键",
            [],
            "fact_order",
        ),
    }
    repository = SimpleNamespace(
        get_column_info_by_id=AsyncMock(return_value=amount),
        get_key_columns_by_table_id=AsyncMock(
            side_effect=lambda table_id: [keys[table_id]]
        ),
        get_table_info_by_id=AsyncMock(
            side_effect=lambda table_id: TableInfo(
                table_id,
                table_id,
                "fact" if table_id == "fact_order" else "dimension",
                "描述",
            )
        ),
    )
    state = {
        "retrieved_column_infos": [region],
        "retrieved_metric_infos": [
            MetricInfo(
                "GMV",
                "GMV",
                "成交金额总和",
                [amount.id],
                ["销售总额"],
                "SUM(fact_order.order_amount)",
            )
        ],
        "retrieved_value_infos": [ValueInfo("v", "华北", region.id)],
    }

    result = await merge_retrieved_info(
        state, _runtime(SimpleNamespace(meta_mysql_repository=repository))
    )

    assert region.examples == ["华东"]
    by_table = {table["name"]: table for table in result["table_infos"]}
    assert {column["name"] for column in by_table["fact_order"]["columns"]} == {
        "order_amount",
        "region_id",
    }
    assert by_table["dim_region"]["columns"][0]["examples"] == ["华东", "华北"]
    assert result["metric_infos"][0]["formula"] == "SUM(fact_order.order_amount)"


async def test_filter_table_and_metric_keep_selected_items_only(mocker):
    table_infos = [
        TableInfoState(
            name="fact_order",
            role="fact",
            description="订单事实表",
            columns=[
                ColumnInfoState(
                    name="order_amount",
                    type="decimal",
                    role="measure",
                    examples=[],
                    description="订单金额",
                    alias=[],
                ),
                ColumnInfoState(
                    name="order_quantity",
                    type="int",
                    role="measure",
                    examples=[],
                    description="订单数量",
                    alias=[],
                ),
            ],
        ),
        TableInfoState(
            name="dim_date",
            role="dimension",
            description="日期维度表",
            columns=[
                ColumnInfoState(
                    name="date_id",
                    type="bigint",
                    role="primary_key",
                    examples=[],
                    description="日期主键",
                    alias=[],
                )
            ],
        ),
    ]
    metric_infos = [
        MetricInfoState(
            name="GMV",
            description="成交额",
            relevant_columns=["fact_order.order_amount"],
            alias=["销售总额"],
            formula="SUM(fact_order.order_amount)",
        ),
        MetricInfoState(
            name="AOV",
            description="客单价",
            relevant_columns=["fact_order.order_amount"],
            alias=[],
            formula="AVG(fact_order.order_amount)",
        ),
    ]
    mocker.patch(
        "app.agent.nodes.filter_table.llm",
        RunnableLambda(lambda _: '{"fact_order": ["order_amount"]}'),
    )
    mocker.patch(
        "app.agent.nodes.filter_metric.llm",
        RunnableLambda(lambda _: '["GMV"]'),
    )

    table_result = await filter_table(
        {"query": "统计华北地区的销售总额", "table_infos": table_infos},
        _runtime(),
    )
    metric_result = await filter_metric(
        {"query": "统计华北地区的销售总额", "metric_infos": metric_infos},
        _runtime(),
    )

    assert [table["name"] for table in table_result["table_infos"]] == ["fact_order"]
    assert [column["name"] for column in table_result["table_infos"][0]["columns"]] == [
        "order_amount"
    ]
    assert [item["name"] for item in metric_result["metric_infos"]] == ["GMV"]
    assert table_infos[0]["columns"][1]["name"] == "order_quantity"

    mocker.patch(
        "app.agent.nodes.filter_table.llm",
        RunnableLambda(lambda _: '{"fact_order": ["missing_column"]}'),
    )
    skipped = await filter_table(
        {"query": "统计华北地区的销售总额", "table_infos": table_infos},
        _runtime(),
    )
    assert skipped["table_infos"] == []


async def test_filter_nodes_short_circuit_empty_candidates_and_reject_bad_json(
    mocker,
):
    assert await filter_table({"query": "q", "table_infos": []}, _runtime()) == {
        "table_infos": []
    }
    assert await filter_metric({"query": "q", "metric_infos": []}, _runtime()) == {
        "metric_infos": []
    }
    mocker.patch(
        "app.agent.nodes.filter_table.llm",
        RunnableLambda(lambda _: "[]"),
    )
    mocker.patch(
        "app.agent.nodes.filter_metric.llm",
        RunnableLambda(lambda _: '{"GMV": true}'),
    )
    table_state = {
        "query": "q",
        "table_infos": [
            TableInfoState(
                name="fact_order",
                role="fact",
                description="",
                columns=[],
            )
        ],
    }
    with pytest.raises(ValueError, match="表过滤结果"):
        await filter_table(table_state, _runtime())
    with pytest.raises(ValueError, match="指标过滤结果"):
        await filter_metric(
            {
                "query": "q",
                "metric_infos": [
                    MetricInfoState(
                        name="GMV",
                        description="",
                        relevant_columns=[],
                        alias=[],
                        formula="",
                    )
                ],
            },
            _runtime(),
        )


async def test_add_extra_context_uses_injected_date_and_db_info():
    runtime = _runtime(
        SimpleNamespace(
            current_date=date(2026, 3, 15),
            max_correction_attempts=3,
            dw_mysql_repository=SimpleNamespace(
                get_db_info=AsyncMock(
                    return_value={"dialect": "mysql", "version": "8.0.45"}
                )
            ),
        )
    )

    result = await add_extra_context({}, runtime)

    assert result["date_info"] == {
        "date": "2026-03-15",
        "weekday": "Sunday",
        "quarter": "Q1",
    }
    assert result["db_info"] == {"dialect": "mysql", "version": "8.0.45"}
    assert result["max_correction_attempts"] == 3


async def test_generate_and_correct_sql_use_context_and_cover_sql(mocker):
    sql_state = {
        "query": "统计华北地区的销售总额",
        "table_infos": [
            TableInfoState(
                name="fact_order",
                role="fact",
                description="订单事实表",
                columns=[],
            )
        ],
        "metric_infos": [],
        "date_info": DateInfoState(date="2026-03-15", weekday="Sunday", quarter="Q1"),
        "db_info": DBInfoState(dialect="mysql", version="8.0.45"),
        "sql": "SELECT missing FROM fact_order",
        "error": "Unknown column 'missing'",
        "correction_attempts": 0,
    }
    mocker.patch(
        "app.agent.nodes.generate_sql.llm",
        RunnableLambda(
            lambda _: (
                "SELECT SUM(fact_order.order_amount) FROM fact_order "
                "JOIN dim_region ON fact_order.region_id = dim_region.region_id "
                "WHERE dim_region.region_name = '华北'"
            )
        ),
    )
    mocker.patch(
        "app.agent.nodes.correct_sql.llm",
        RunnableLambda(lambda _: "SELECT SUM(fact_order.order_amount) FROM fact_order"),
    )

    generated = await generate_sql(sql_state, _runtime())
    assert "fact_order.order_amount" in generated["sql"]
    assert generated["error"] is None
    corrected = await correct_sql(sql_state, _runtime())
    assert corrected["sql"] == "SELECT SUM(fact_order.order_amount) FROM fact_order"
    assert corrected["correction_attempts"] == 1
    executed = await execute_sql(
        {"sql": generated["sql"]},
        _runtime(
            SimpleNamespace(
                dw_mysql_repository=SimpleNamespace(
                    run=AsyncMock(return_value=[{"gmv": 41099.5}])
                )
            )
        ),
    )
    assert executed["execution_result"] == [{"gmv": 41099.5}]

    failed = await validate_sql(
        {"correction_attempts": 0, "max_correction_attempts": 0},
        _runtime(SimpleNamespace(simulated_validation_failures=1)),
    )
    assert failed["sql_valid"] is False
    assert failed["error"] == "SQL 校验失败且已达到最大纠错次数"
    passed = await validate_sql(
        {"correction_attempts": 0},
        _runtime(SimpleNamespace(simulated_validation_failures=0)),
    )
    assert passed["sql_valid"] is True
    assert route_after_validation({"sql_valid": True}) == "execute_sql"
    assert route_after_validation(
        {"sql_valid": False, "correction_attempts": 0, "max_correction_attempts": 2}
    ) == "correct_sql"
    assert route_after_validation(
        {"sql_valid": False, "correction_attempts": 2, "max_correction_attempts": 2}
    ) == "end"


async def test_sql_nodes_write_progress_error_then_raise(mocker):
    events = []
    runtime = _runtime()
    runtime.stream_writer = events.append
    mocker.patch(
        "app.agent.nodes.generate_sql.llm",
        RunnableLambda(lambda _: (_ for _ in ()).throw(RuntimeError("生成失败"))),
    )
    mocker.patch(
        "app.agent.nodes.correct_sql.llm",
        RunnableLambda(lambda _: (_ for _ in ()).throw(RuntimeError("校正失败"))),
    )

    sql_state = {
        "query": "q",
        "table_infos": [],
        "metric_infos": [],
        "date_info": DateInfoState(date="2026-03-15", weekday="Sunday", quarter="Q1"),
        "db_info": DBInfoState(dialect="mysql", version="8.0.45"),
        "sql": "SELECT 1",
        "error": "x",
        "correction_attempts": 0,
    }
    with pytest.raises(RuntimeError, match="生成失败"):
        await generate_sql(sql_state, runtime)
    assert events[-1] == {"type": "progress", "step": "生成SQL", "status": "error"}

    events.clear()
    with pytest.raises(RuntimeError, match="校正失败"):
        await correct_sql(sql_state, runtime)
    assert events[-1] == {"type": "progress", "step": "校正SQL", "status": "error"}

    events.clear()
    execute_runtime = _runtime(
        SimpleNamespace(
            dw_mysql_repository=SimpleNamespace(
                run=AsyncMock(side_effect=RuntimeError("执行失败"))
            )
        )
    )
    execute_runtime.stream_writer = events.append
    with pytest.raises(RuntimeError, match="执行失败"):
        await execute_sql({"sql": "SELECT 1"}, execute_runtime)
    assert events[-1] == {"type": "progress", "step": "执行SQL", "status": "error"}

    events.clear()
    broken = SimpleNamespace(stream_writer=events.append, context=None)
    with pytest.raises(AttributeError):
        await validate_sql({"sql": "SELECT 1"}, broken)
    assert events[-1] == {"type": "progress", "step": "校验SQL", "status": "error"}
