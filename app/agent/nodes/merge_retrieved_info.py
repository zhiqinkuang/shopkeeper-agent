"""把三路召回结果整理成 SQL 生成所需的上下文"""

from dataclasses import replace

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.progress import progress_event
from app.agent.state import (
    ColumnInfoState,
    DataAgentState,
    MetricInfoState,
    TableInfoState,
)
from app.core.log import logger
from app.entities.column_info import ColumnInfo


def _copy_column_info(column_info: ColumnInfo) -> ColumnInfo:
    """复制字段及其可变属性，避免合并过程修改上游召回结果"""
    return replace(
        column_info,
        examples=list(column_info.examples),
        alias=list(column_info.alias),
    )


async def merge_retrieved_info(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """合并字段、指标和真实取值，并按表组织候选上下文"""
    step = "合并召回信息"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        return await _merge_retrieved_info(state, runtime, writer, step)
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise


async def _merge_retrieved_info(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
    writer,
    step: str,
) -> DataAgentState:
    retrieved_column_infos = state["retrieved_column_infos"]
    retrieved_metric_infos = state["retrieved_metric_infos"]
    retrieved_value_infos = state["retrieved_value_infos"]
    repository = runtime.context.meta_mysql_repository

    # 字段 ID 是三路结果之间的关联键，同时可自然消除重复字段
    column_info_map = {
        column_info.id: _copy_column_info(column_info)
        for column_info in retrieved_column_infos
    }

    # 指标命中后必须补齐计算口径依赖的底层字段
    for metric_info in retrieved_metric_infos:
        for column_id in metric_info.relevant_columns:
            if column_id not in column_info_map:
                column_info_map[column_id] = _copy_column_info(
                    await repository.get_column_info_by_id(column_id)
                )

    # 真实取值要回填到所属字段，帮助后续生成准确的过滤条件
    for value_info in retrieved_value_infos:
        column_id = value_info.column_id
        if column_id not in column_info_map:
            column_info_map[column_id] = _copy_column_info(
                await repository.get_column_info_by_id(column_id)
            )
        if value_info.value not in column_info_map[column_id].examples:
            column_info_map[column_id].examples.append(value_info.value)

    table_to_columns: dict[str, list[ColumnInfo]] = {}
    for column_info in column_info_map.values():
        table_to_columns.setdefault(column_info.table_id, []).append(column_info)

    # 自然语言通常不会提到关联键，但多表 SQL 需要这些字段构造 Join
    for table_id, column_infos in table_to_columns.items():
        existing_column_ids = {column_info.id for column_info in column_infos}
        key_columns = await repository.get_key_columns_by_table_id(table_id)
        for key_column in key_columns:
            if key_column.id not in existing_column_ids:
                column_infos.append(key_column)
                existing_column_ids.add(key_column.id)

    table_infos: list[TableInfoState] = []
    for table_id, column_infos in table_to_columns.items():
        table_info = await repository.get_table_info_by_id(table_id)
        columns = [
            ColumnInfoState(
                name=column_info.name,
                type=column_info.type,
                role=column_info.role,
                examples=list(column_info.examples),
                description=column_info.description,
                alias=list(column_info.alias),
            )
            for column_info in column_infos
        ]
        table_infos.append(
            TableInfoState(
                name=table_info.name,
                role=table_info.role,
                description=table_info.description,
                columns=columns,
            )
        )

    metric_infos = [
        MetricInfoState(
            name=metric_info.name,
            description=metric_info.description,
            relevant_columns=list(metric_info.relevant_columns),
            alias=list(metric_info.alias),
            formula=metric_info.formula,
        )
        for metric_info in retrieved_metric_infos
    ]

    writer(progress_event(step, "success"))
    logger.info(f"合并后的表信息：{[item['name'] for item in table_infos]}")
    logger.info(f"合并后的指标信息：{[item['name'] for item in metric_infos]}")
    return {"table_infos": table_infos, "metric_infos": metric_infos}
