"""SQL 校验节点"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger


async def validate_sql(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """校验 SQL；语法错误写入 state，不中断图执行"""
    step = "校验SQL"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        attempts = state.get("correction_attempts", 0)
        if attempts < runtime.context.simulated_validation_failures:
            update: DataAgentState = {
                "sql_valid": False,
                "validation_error": "模拟 SQL 校验失败",
                "error": "模拟 SQL 校验失败",
            }
            if attempts >= state.get("max_correction_attempts", 0):
                update["error"] = "SQL 校验失败且已达到最大纠错次数"
            writer(progress_event(step, "success"))
            return update

        sql = state.get("sql")
        repository = getattr(runtime.context, "dw_mysql_repository", None)
        if sql and repository is not None:
            try:
                await repository.validate(sql)
                writer(progress_event(step, "success"))
                logger.info("SQL语法正确")
                return {
                    "sql_valid": True,
                    "validation_error": None,
                    "error": None,
                }
            except Exception as error:
                # SQL 语法或字段错误属于业务分支，交给条件边进入 correct_sql
                logger.info(f"SQL语法错误：{error}")
                writer(progress_event(step, "success"))
                return {
                    "sql_valid": False,
                    "validation_error": str(error),
                    "error": str(error),
                }

        writer(progress_event(step, "success"))
        return {"sql_valid": True, "validation_error": None}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
