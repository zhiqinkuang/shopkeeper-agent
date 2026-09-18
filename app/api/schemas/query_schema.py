"""查询接口请求体"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuerySchema(BaseModel):
    """前端提交的自然语言问题"""

    query: str


class QueryAuditSchema(BaseModel):
    """一次问答的可回放审计记录"""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    request_id: str
    query: str
    sql: str | None = Field(default=None, validation_alias="sql_text")
    execution_result: list[dict[str, Any]] | None = None
    answer: str | None = None
    error: str | None = None
    created_at: datetime | None = None
