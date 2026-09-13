"""根据校验错误做最小必要 SQL 修正"""

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


async def correct_sql(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """用完整上下文和数据库错误覆盖原来的候选 SQL"""
    step = "校正SQL"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        prompt = PromptTemplate(
            template=load_prompt("correct_sql"),
            input_variables=[
                "table_infos",
                "metric_infos",
                "date_info",
                "db_info",
                "query",
                "sql",
                "error",
            ],
        )
        chain = prompt | llm | StrOutputParser()
        sql = await chain.ainvoke(
            {
                "table_infos": yaml.safe_dump(
                    state["table_infos"], allow_unicode=True, sort_keys=False
                ),
                "metric_infos": yaml.safe_dump(
                    state["metric_infos"], allow_unicode=True, sort_keys=False
                ),
                "date_info": yaml.safe_dump(
                    state["date_info"], allow_unicode=True, sort_keys=False
                ),
                "db_info": yaml.safe_dump(
                    state["db_info"], allow_unicode=True, sort_keys=False
                ),
                "query": state["query"],
                "sql": state["sql"],
                "error": state["error"],
            }
        )
        logger.info(f"校正后的SQL：{sql}")
        writer(progress_event(step, "success"))
        return {
            "sql": sql,
            "correction_attempts": state.get("correction_attempts", 0) + 1,
            "validation_error": None,
            "error": None,
        }
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
