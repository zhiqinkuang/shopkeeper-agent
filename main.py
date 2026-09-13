"""问数智能体 HTTP 服务入口"""

import uuid

from fastapi import FastAPI, Request

from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var

app = FastAPI(lifespan=lifespan)
app.include_router(query_router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    # 请求被处理之前，先为当前请求生成一个唯一 ID
    request_id = str(uuid.uuid4())
    request_id_ctx_var.set(request_id)
    response = await call_next(request)
    return response
