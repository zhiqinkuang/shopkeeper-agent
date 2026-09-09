"""SQL 校正占位节点"""

from app.agent.state import QueryState


async def correct_sql(state: QueryState) -> QueryState:
    """记录一次模拟校正并保留安全占位 SQL"""
    return {
        "sql": state["sql"],
        "correction_attempts": state.get("correction_attempts", 0) + 1,
        "validation_error": None,
    }
