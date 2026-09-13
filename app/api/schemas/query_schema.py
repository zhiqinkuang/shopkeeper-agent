"""查询接口请求体"""

from pydantic import BaseModel


class QuerySchema(BaseModel):
    """前端提交的自然语言问题"""

    query: str
