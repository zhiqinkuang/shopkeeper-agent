"""根据整理好的上下文生成候选 SQL"""

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


async def generate_sql(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """只生成候选 SQL，不负责校验和执行"""
    step = "生成SQL"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        prompt = PromptTemplate(
            template=load_prompt("generate_sql"),
            input_variables=[
                "table_infos",
                "metric_infos",
                "date_info",
                "db_info",
                "query",
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
            }
        )
        logger.info(f"生成的SQL：{sql}")
        writer(progress_event(step, "success"))
        return {"sql": sql, "correction_attempts": 0, "error": None}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
