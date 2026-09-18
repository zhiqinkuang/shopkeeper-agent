"""根据用户问题裁剪候选指标上下文"""

from typing import Any

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState, MetricInfoState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


def _ensure_metric_selection(result: Any) -> list[str]:
    """校验模型只返回指标名称列表"""
    if not isinstance(result, list) or not all(
        isinstance(metric_name, str) for metric_name in result
    ):
        raise ValueError("指标过滤结果必须是 JSON 字符串数组")
    return result


async def filter_metric(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """让模型选择必要指标，再由程序裁剪原始结构"""
    step = "过滤指标信息"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        return await _filter_metric(state, writer, step)
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise


async def _filter_metric(
    state: DataAgentState, writer, step: str
) -> DataAgentState:
    query = state["query"]
    metric_infos = state["metric_infos"]
    if not metric_infos:
        writer(progress_event(step, "success"))
        logger.info("过滤后的指标信息：[]")
        return {"metric_infos": []}

    prompt = PromptTemplate(
        template=load_prompt("filter_metric_info"),
        input_variables=["query", "metric_infos"],
    )
    chain = prompt | llm | JsonOutputParser()
    result = _ensure_metric_selection(
        await chain.ainvoke(
            {
                "query": query,
                "metric_infos": yaml.safe_dump(
                    metric_infos, allow_unicode=True, sort_keys=False
                ),
            }
        )
    )

    filtered_metric_infos = [
        MetricInfoState(
            name=metric_info["name"],
            description=metric_info["description"],
            relevant_columns=list(metric_info["relevant_columns"]),
            alias=list(metric_info["alias"]),
            formula=metric_info["formula"],
        )
        for metric_info in metric_infos
        if metric_info["name"] in result
    ]

    writer(progress_event(step, "success"))
    logger.info(
        f"过滤后的指标信息：{[item['name'] for item in filtered_metric_infos]}"
    )
    return {"metric_infos": filtered_metric_infos}
