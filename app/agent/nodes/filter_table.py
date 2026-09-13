"""根据用户问题裁剪候选表结构上下文"""

from typing import Any

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.nodes.progress import progress_event
from app.agent.state import ColumnInfoState, DataAgentState, TableInfoState
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


def _ensure_table_selection(result: Any) -> dict[str, list[str]]:
    """校验模型只返回表名到字段名列表的选择结果"""
    if not isinstance(result, dict) or not all(
        isinstance(table_name, str)
        and isinstance(column_names, list)
        and all(isinstance(column_name, str) for column_name in column_names)
        for table_name, column_names in result.items()
    ):
        raise ValueError("表过滤结果必须是表名到字段名列表的 JSON 对象")
    return result


async def filter_table(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """让模型选择必要表和字段，再由程序裁剪原始结构"""
    step = "过滤表信息"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        return await _filter_table(state, writer, step)
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise


async def _filter_table(
    state: DataAgentState, writer, step: str
) -> DataAgentState:
    query = state["query"]
    table_infos = state["table_infos"]
    if not table_infos:
        writer(progress_event(step, "success"))
        logger.info("过滤后的表信息：[]")
        return {"table_infos": []}

    prompt = PromptTemplate(
        template=load_prompt("filter_table_info"),
        input_variables=["query", "table_infos"],
    )
    chain = prompt | llm | JsonOutputParser()
    result = _ensure_table_selection(
        await chain.ainvoke(
            {
                "query": query,
                "table_infos": yaml.safe_dump(
                    table_infos, allow_unicode=True, sort_keys=False
                ),
            }
        )
    )

    filtered_table_infos: list[TableInfoState] = []
    for table_info in table_infos:
        selected_column_names = result.get(table_info["name"])
        if selected_column_names is None:
            continue
        columns = [
            ColumnInfoState(
                name=column_info["name"],
                type=column_info["type"],
                role=column_info["role"],
                examples=list(column_info["examples"]),
                description=column_info["description"],
                alias=list(column_info["alias"]),
            )
            for column_info in table_info["columns"]
            if column_info["name"] in selected_column_names
        ]
        if not columns:
            continue
        filtered_table_infos.append(
            TableInfoState(
                name=table_info["name"],
                role=table_info["role"],
                description=table_info["description"],
                columns=columns,
            )
        )

    writer(progress_event(step, "success"))
    logger.info(f"过滤后的表信息：{[item['name'] for item in filtered_table_infos]}")
    return {"table_infos": filtered_table_infos}
