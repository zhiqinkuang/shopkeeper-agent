"""SQL 校验占位节点"""

from langgraph.runtime import Runtime

from app.agent.context import QueryContext
from app.agent.state import QueryState


async def validate_sql(
    state: QueryState, runtime: Runtime[QueryContext]
) -> QueryState:
    """按配置模拟校验成功或失败，不访问数据库"""
    attempts = state.get("correction_attempts", 0)
    if attempts < runtime.context.simulated_validation_failures:
        update: QueryState = {
            "sql_valid": False,
            "validation_error": "模拟 SQL 校验失败",
        }
        if attempts >= state.get("max_correction_attempts", 0):
            update["error"] = "SQL 校验失败且已达到最大纠错次数"
        return update
    return {"sql_valid": True, "validation_error": None}
