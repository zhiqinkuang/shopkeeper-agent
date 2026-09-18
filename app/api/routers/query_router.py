"""查询接口路由"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_meta_mysql_repository, get_query_service
from app.api.schemas.query_schema import QueryAuditSchema, QuerySchema
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services.query_service import QueryService

query_router = APIRouter()


@query_router.post("/api/query")
async def query_handler(
    query: QuerySchema,
    query_service: Annotated[QueryService, Depends(get_query_service)],
):
    """接收用户问题，并以 SSE 持续返回问数工作流进度"""
    return StreamingResponse(
        query_service.query(query.query),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@query_router.get("/api/audits/{request_id}")
async def get_query_audit_handler(
    request_id: str,
    meta_mysql_repository: Annotated[
        MetaMySQLRepository, Depends(get_meta_mysql_repository)
    ],
) -> QueryAuditSchema:
    """按请求编号回放一次问答的 SQL 和结果"""
    record = await meta_mysql_repository.get_query_audit(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到对应的查询审计")
    return QueryAuditSchema.model_validate(record)
