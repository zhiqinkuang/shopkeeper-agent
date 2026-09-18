"""SQL 执行节点"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger


async def execute_sql(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """执行 SQL，并通过 SSE 输出最终查询结果"""
    step = "执行SQL"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        sql = state["sql"]
        result = await runtime.context.dw_mysql_repository.run(sql)
        logger.info(f"SQL执行结果：{result}")
        writer(progress_event(step, "success"))
        writer({"type": "result", "data": result})
        return {"execution_result": result, "error": None}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
