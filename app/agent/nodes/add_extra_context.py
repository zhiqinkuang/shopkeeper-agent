"""额外上下文补充占位节点"""

from langgraph.runtime import Runtime

from app.agent.context import QueryContext
from app.agent.state import QueryState


async def add_extra_context(
    _: QueryState, runtime: Runtime[QueryContext]
) -> QueryState:
    """补充当前日期和最大 SQL 纠错次数"""
    context = runtime.context
    return {
        "extra_context": {"current_date": context.current_date.isoformat()},
        "max_correction_attempts": context.max_correction_attempts,
    }
