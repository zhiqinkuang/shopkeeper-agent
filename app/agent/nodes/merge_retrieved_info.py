"""召回信息合并占位节点"""

from app.agent.state import QueryState


async def merge_retrieved_info(state: QueryState) -> QueryState:
    """把三路召回结果汇总到统一上下文"""
    return {
        "merged_context": {
            "columns": state.get("recalled_columns", []),
            "metrics": state.get("recalled_metrics", []),
            "values": state.get("recalled_values", []),
        }
    }
