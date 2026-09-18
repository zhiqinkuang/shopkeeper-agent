"""基于向量索引召回字段信息"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.prompt.prompt_loader import load_prompt


async def recall_column(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """扩展字段关键词并从 Qdrant 召回候选字段"""
    step = "召回字段信息"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        query = state["query"]
        keywords = state["keywords"]
        repository = runtime.context.column_qdrant_repository
        embedding_client = runtime.context.embedding_client

        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_column_recall"),
            input_variables=["query"],
        )
        chain = prompt | llm | JsonOutputParser()
        extended_keywords = await chain.ainvoke({"query": query})
        if not isinstance(extended_keywords, list) or not all(
            isinstance(keyword, str) for keyword in extended_keywords
        ):
            raise ValueError("字段召回扩展词必须是 JSON 字符串数组")
        recall_keywords = set([*keywords, *extended_keywords])

        column_info_map: dict[str, ColumnInfo] = {}
        for keyword in recall_keywords:
            embedding = await embedding_client.aembed_query(keyword)
            column_infos = await repository.search(embedding)
            for column_info in column_infos:
                column_info_map.setdefault(column_info.id, column_info)

        retrieved_column_infos = list(column_info_map.values())
        writer(progress_event(step, "success"))
        logger.info(f"检索到字段信息：{list(column_info_map)}")
        return {"retrieved_column_infos": retrieved_column_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
