"""FastAPI 应用级外部资源生命周期"""

from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时初始化客户端，关闭时按逆序释放"""
    async with AsyncExitStack() as exit_stack:
        qdrant_client_manager.init()
        exit_stack.push_async_callback(qdrant_client_manager.close)
        embedding_client_manager.init()
        exit_stack.push_async_callback(embedding_client_manager.close)
        es_client_manager.init()
        exit_stack.push_async_callback(es_client_manager.close)
        meta_mysql_client_manager.init()
        exit_stack.push_async_callback(meta_mysql_client_manager.close)
        dw_mysql_client_manager.init()
        exit_stack.push_async_callback(dw_mysql_client_manager.close)
        yield
