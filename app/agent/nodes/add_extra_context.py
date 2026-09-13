"""补充 SQL 生成所需的日期和数据库环境信息"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState, DateInfoState, DBInfoState
from app.core.log import logger

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


async def add_extra_context(
    _: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """补齐相对时间和数仓 SQL 方言信息"""
    step = "添加额外上下文"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        return await _add_extra_context(runtime, writer, step)
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise


async def _add_extra_context(
    runtime: Runtime[DataAgentContext], writer, step: str
) -> DataAgentState:
    today = runtime.context.current_date
    date_info = DateInfoState(
        date=today.strftime("%Y-%m-%d"),
        weekday=_WEEKDAYS[today.weekday()],
        quarter=f"Q{(today.month - 1) // 3 + 1}",
    )

    db_info = DBInfoState(**await runtime.context.dw_mysql_repository.get_db_info())
    writer(progress_event(step, "success"))
    logger.info(f"数据库信息：{db_info}")
    logger.info(f"日期信息：{date_info}")
    return {
        "date_info": date_info,
        "db_info": db_info,
        "max_correction_attempts": runtime.context.max_correction_attempts,
    }
