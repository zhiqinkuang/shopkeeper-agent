"""问数智能体共享状态定义"""

from typing import Any, TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo


class MetricInfoState(TypedDict):
    """面向后续提示词的指标上下文"""

    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]
    formula: str


class ColumnInfoState(TypedDict):
    """面向后续提示词的字段上下文"""

    name: str
    type: str
    role: str
    examples: list[Any]
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    """按表组织的字段上下文"""

    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class DateInfoState(TypedDict):
    """SQL 生成所需的当前日期上下文"""

    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict):
    """SQL 生成所需的数据库方言和版本"""

    dialect: str
    version: str


class DataAgentState(TypedDict, total=False):
    """一次问数链路中的业务状态"""

    query: str
    keywords: list[str]
    retrieved_column_infos: list[ColumnInfo]
    retrieved_metric_infos: list[MetricInfo]
    retrieved_value_infos: list[ValueInfo]
    table_infos: list[TableInfoState]
    metric_infos: list[MetricInfoState]
    date_info: DateInfoState
    db_info: DBInfoState
    selected_tables: list[TableInfoState]
    selected_metrics: list[MetricInfoState]
    extra_context: dict[str, Any]
    sql: str
    sql_valid: bool
    validation_error: str | None
    correction_attempts: int
    max_correction_attempts: int
    execution_result: list[dict[str, Any]]
    answer: str
    error: str | None
