from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.graph import START, StateGraph

from app.agent.context import DataAgentContext
from app.agent.graph import route_after_validation, wire_sql_loop
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.generate_answer import generate_answer
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import (
    DataAgentState,
    DateInfoState,
    DBInfoState,
    MetricInfoState,
    TableInfoState,
)

pytestmark = pytest.mark.unit

BAD_SQL = "SELECT missing_column FROM fact_order"
GOOD_SQL = "SELECT SUM(order_amount) AS gmv FROM fact_order"


class FakeDW:
    def __init__(self):
        self.validated = []
        self.executed = []

    async def validate(self, sql: str) -> None:
        self.validated.append(sql)
        if "```" in sql:
            raise RuntimeError("You have an error in your SQL syntax")
        if "missing_column" in sql:
            raise RuntimeError("Unknown column 'missing_column'")

    async def run(self, sql: str) -> list[dict]:
        self.executed.append(sql)
        return [{"gmv": 41099.5}]


def _sql_state() -> DataAgentState:
    return {
        "query": "统计华北地区的销售总额",
        "table_infos": [
            TableInfoState(
                name="fact_order",
                role="fact",
                description="订单事实表",
                columns=[],
            )
        ],
        "metric_infos": [
            MetricInfoState(
                name="GMV",
                description="成交额",
                relevant_columns=["fact_order.order_amount"],
                alias=["销售总额"],
                formula="SUM(fact_order.order_amount)",
            )
        ],
        "date_info": DateInfoState(date="2026-03-15", weekday="Sunday", quarter="Q1"),
        "db_info": DBInfoState(dialect="mysql", version="8.0.45"),
        "max_correction_attempts": 2,
    }


def _context(dw) -> DataAgentContext:
    return DataAgentContext(
        column_qdrant_repository=SimpleNamespace(),
        embedding_client=SimpleNamespace(),
        metric_qdrant_repository=SimpleNamespace(),
        value_es_repository=SimpleNamespace(),
        meta_mysql_repository=SimpleNamespace(),
        dw_mysql_repository=dw,
        simulated_validation_failures=0,
        max_correction_attempts=2,
    )


def _sql_loop_graph():
    graph = StateGraph(DataAgentState, context_schema=DataAgentContext)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("correct_sql", correct_sql)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("generate_answer", generate_answer)
    graph.add_edge(START, "generate_sql")
    wire_sql_loop(graph)
    return graph.compile()


async def _run_sql_loop(graph, dw, mocker, generated_sql, corrected_sql=GOOD_SQL):
    mocker.patch(
        "app.agent.nodes.generate_sql.llm",
        RunnableLambda(lambda _: generated_sql),
    )
    mocker.patch(
        "app.agent.nodes.correct_sql.llm",
        RunnableLambda(lambda _: corrected_sql),
    )
    mocker.patch(
        "app.agent.nodes.generate_answer.llm",
        RunnableLambda(lambda _: "华北地区销售总额为 41099.5 元。"),
    )
    events = []
    nodes = []
    merged: DataAgentState = {}
    async for mode, chunk in graph.astream(
        _sql_state(),
        context=_context(dw),
        stream_mode=["updates", "custom"],
    ):
        if mode == "custom":
            events.append(chunk)
            continue
        nodes.extend(chunk.keys())
        for update in chunk.values():
            if isinstance(update, dict):
                merged.update(update)
    return events, nodes, merged


async def test_sql_loop_corrects_invalid_sql_then_executes(mocker):
    dw = FakeDW()
    events, nodes, merged = await _run_sql_loop(
        _sql_loop_graph(), dw, mocker, BAD_SQL, GOOD_SQL
    )

    assert nodes == [
        "generate_sql",
        "validate_sql",
        "correct_sql",
        "validate_sql",
        "execute_sql",
        "generate_answer",
    ]
    assert dw.validated == [BAD_SQL, GOOD_SQL]
    assert dw.executed == [GOOD_SQL]
    assert merged["sql"] == GOOD_SQL
    assert merged["execution_result"] == [{"gmv": 41099.5}]
    assert merged["answer"] == "华北地区销售总额为 41099.5 元。"
    assert merged["error"] is None
    assert merged["sql_valid"] is True
    assert {"type": "result", "data": [{"gmv": 41099.5}]} in events
    assert {
        "type": "answer",
        "text": "华北地区销售总额为 41099.5 元。",
    } in events
    assert {
        "type": "progress",
        "step": "校验SQL",
        "status": "success",
    } in events
    assert {
        "type": "progress",
        "step": "校正SQL",
        "status": "success",
    } in events


async def test_sql_loop_executes_when_first_validate_passes(mocker):
    dw = FakeDW()
    events, nodes, merged = await _run_sql_loop(
        _sql_loop_graph(), dw, mocker, GOOD_SQL
    )

    assert nodes == [
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "generate_answer",
    ]
    assert dw.validated == [GOOD_SQL]
    assert dw.executed == [GOOD_SQL]
    assert merged["execution_result"] == [{"gmv": 41099.5}]
    assert not any(item.get("step") == "校正SQL" for item in events if isinstance(item, dict))


async def test_sql_loop_stops_when_correction_attempts_exhausted(mocker):
    dw = FakeDW()
    state = _sql_state()
    state["max_correction_attempts"] = 1
    mocker.patch(
        "app.agent.nodes.generate_sql.llm",
        RunnableLambda(lambda _: BAD_SQL),
    )
    mocker.patch(
        "app.agent.nodes.correct_sql.llm",
        RunnableLambda(lambda _: BAD_SQL),
    )
    context = _context(dw)
    context.max_correction_attempts = 1

    nodes = []
    merged: DataAgentState = {}
    async for mode, chunk in _sql_loop_graph().astream(
        state,
        context=context,
        stream_mode=["updates", "custom"],
    ):
        if mode == "updates":
            nodes.extend(chunk.keys())
            for update in chunk.values():
                if isinstance(update, dict):
                    merged.update(update)

    assert nodes == [
        "generate_sql",
        "validate_sql",
        "correct_sql",
        "validate_sql",
    ]
    assert dw.executed == []
    assert merged["sql_valid"] is False
    assert "missing_column" in (merged.get("error") or "")
    assert route_after_validation(merged) == "end"


async def test_sql_loop_corrects_markdown_sql_then_executes(mocker):
    dw = FakeDW()
    markdown_sql = "```sql\nSELECT SUM(order_amount) AS gmv FROM fact_order\n```"
    events, nodes, merged = await _run_sql_loop(
        _sql_loop_graph(), dw, mocker, markdown_sql, GOOD_SQL
    )

    assert nodes == [
        "generate_sql",
        "validate_sql",
        "correct_sql",
        "validate_sql",
        "execute_sql",
        "generate_answer",
    ]
    assert dw.validated == [markdown_sql, GOOD_SQL]
    assert dw.executed == [GOOD_SQL]
    assert merged["execution_result"] == [{"gmv": 41099.5}]
    assert {"type": "result", "data": [{"gmv": 41099.5}]} in events


async def test_validate_sql_uses_explain_and_keeps_sql_errors_in_state():
    runtime = SimpleNamespace(
        stream_writer=lambda _: None,
        context=SimpleNamespace(
            simulated_validation_failures=0,
            dw_mysql_repository=SimpleNamespace(
                validate=AsyncMock(side_effect=RuntimeError("Unknown column 'x'"))
            ),
        ),
    )

    failed = await validate_sql({"sql": BAD_SQL, "correction_attempts": 0}, runtime)
    assert failed["sql_valid"] is False
    assert "Unknown column" in failed["error"]

    runtime.context.dw_mysql_repository.validate = AsyncMock()
    passed = await validate_sql({"sql": GOOD_SQL, "correction_attempts": 0}, runtime)
    assert passed == {
        "sql_valid": True,
        "validation_error": None,
        "error": None,
    }
