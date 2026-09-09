"""问数智能体 LangGraph 骨架"""

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.context import QueryContext
from app.agent.nodes import (
    add_extra_context,
    correct_sql,
    execute_sql,
    extract_keywords,
    filter_metric,
    filter_table,
    generate_sql,
    merge_retrieved_info,
    recall_column,
    recall_metric,
    recall_value,
    validate_sql,
)
from app.agent.state import QueryState


def route_after_validation(
    state: QueryState,
) -> Literal["execute_sql", "correct_sql", "end"]:
    """根据校验结果和剩余纠错次数选择下一节点"""
    if state.get("sql_valid", False):
        return "execute_sql"
    if state.get("correction_attempts", 0) < state.get(
        "max_correction_attempts", 0
    ):
        return "correct_sql"
    return "end"


def build_query_graph() -> CompiledStateGraph:
    """构建并编译最小可运行的问数工作流"""
    graph = StateGraph(QueryState, context_schema=QueryContext)

    graph.add_node("extract_keywords", extract_keywords)
    graph.add_node("recall_column", recall_column)
    graph.add_node("recall_metric", recall_metric)
    graph.add_node("recall_value", recall_value)
    graph.add_node("merge_retrieved_info", merge_retrieved_info)
    graph.add_node("filter_table", filter_table)
    graph.add_node("filter_metric", filter_metric)
    graph.add_node("add_extra_context", add_extra_context)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("correct_sql", correct_sql)
    graph.add_node("execute_sql", execute_sql)

    graph.add_edge(START, "extract_keywords")
    graph.add_edge("extract_keywords", "recall_column")
    graph.add_edge("extract_keywords", "recall_metric")
    graph.add_edge("extract_keywords", "recall_value")
    graph.add_edge(
        ["recall_column", "recall_metric", "recall_value"],
        "merge_retrieved_info",
    )
    graph.add_edge("merge_retrieved_info", "filter_table")
    graph.add_edge("merge_retrieved_info", "filter_metric")
    graph.add_edge(["filter_table", "filter_metric"], "add_extra_context")
    graph.add_edge("add_extra_context", "generate_sql")
    graph.add_edge("generate_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validation,
        {
            "execute_sql": "execute_sql",
            "correct_sql": "correct_sql",
            "end": END,
        },
    )
    graph.add_edge("correct_sql", "validate_sql")
    graph.add_edge("execute_sql", END)

    return graph.compile()


query_graph = build_query_graph()
