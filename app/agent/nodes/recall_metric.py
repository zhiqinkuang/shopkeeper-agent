"""基于向量索引召回指标信息"""

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo
from app.prompt.prompt_loader import load_prompt


async def recall_metric(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """扩展指标关键词并从 Qdrant 召回候选指标"""
    step = "召回指标信息"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        query = state["query"]
        keywords = state["keywords"]
        repository = runtime.context.metric_qdrant_repository
        embedding_client = runtime.context.embedding_client

        prompt = PromptTemplate(
            template=load_prompt("extend_keywords_for_metric_recall"),
            input_variables=["query"],
        )
        chain = prompt | llm | JsonOutputParser()
        extended_keywords = await chain.ainvoke({"query": query})
        if not isinstance(extended_keywords, list) or not all(
            isinstance(keyword, str) for keyword in extended_keywords
        ):
            raise ValueError("指标召回扩展词必须是 JSON 字符串数组")
        recall_keywords = set([*keywords, *extended_keywords])

        metric_info_map: dict[str, MetricInfo] = {}
        for keyword in recall_keywords:
            embedding = await embedding_client.aembed_query(keyword)
            metric_infos = await repository.search(embedding)
            for metric_info in metric_infos:
                metric_info_map.setdefault(metric_info.id, metric_info)

        retrieved_metric_infos = list(metric_info_map.values())
        writer(progress_event(step, "success"))
        logger.info(f"检索到指标信息：{list(metric_info_map)}")
        return {"retrieved_metric_infos": retrieved_metric_infos}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
