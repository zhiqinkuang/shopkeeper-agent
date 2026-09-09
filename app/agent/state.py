"""问数智能体共享状态定义"""

from typing import Any, TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo


class QueryState(TypedDict, total=False):
    """LangGraph 节点之间传递的最小状态"""

    question: str
    keywords: list[str]
    recalled_columns: list[ColumnInfo]
    recalled_metrics: list[MetricInfo]
    recalled_values: list[ValueInfo]
    merged_context: dict[str, Any]
    selected_tables: list[TableInfo]
    selected_metrics: list[MetricInfo]
    extra_context: dict[str, Any]
    sql: str
    sql_valid: bool
    validation_error: str | None
    correction_attempts: int
    max_correction_attempts: int
    execution_result: list[dict[str, Any]]
    error: str | None
