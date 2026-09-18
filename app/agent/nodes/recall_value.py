"""基于 Elasticsearch 召回字段真实取值"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.prompt.prompt_loader import load_prompt


async def recall_value(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """扩展字段取值关键词并从 Elasticsearch 召回真实值"""
    step = "召回字段取值"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        query = state["query"]
        keywords = state["keywords"]
        repository = runtime.context.value_es_repository

        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_value_recall"),
            input_variables=["query"],
        )
        chain = prompt | llm | JsonOutputParser()
        extended_keywords = await chain.ainvoke({"query": query})
        if not isinstance(extended_keywords, list) or not all(
            isinstance(keyword, str) for keyword in extended_keywords
        ):
            raise ValueError("字段取值召回扩展词必须是 JSON 字符串数组")
        recall_keywords = set([*keywords, *extended_keywords])

        value_info_map: dict[str, ValueInfo] = {}
        for keyword in recall_keywords:
            value_infos = await repository.search(keyword)
            for value_info in value_infos:
                value_info_map.setdefault(value_info.id, value_info)

        retrieved_value_infos = list(value_info_map.values())
        writer(progress_event(step, "success"))
        logger.info(f"检索到字段取值：{list(value_info_map)}")
        return {"retrieved_value_infos": retrieved_value_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
