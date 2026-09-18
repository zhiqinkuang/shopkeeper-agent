"""查询接口依赖组装"""

from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.query_service import QueryService

T = TypeVar("T")


def _require(value: T | None, name: str) -> T:
    if value is None:
        raise HTTPException(status_code=503, detail=f"{name} 尚未初始化")
    return value


async def get_meta_session():
    """创建一次请求内使用的元数据库 Session"""
    session_factory = _require(
        meta_mysql_client_manager.session_factory, "meta_mysql_client_manager"
    )
    async with session_factory() as meta_session:
        yield meta_session


async def get_dw_session():
    """创建一次请求内使用的数仓 Session"""
    session_factory = _require(
        dw_mysql_client_manager.session_factory, "dw_mysql_client_manager"
    )
    async with session_factory() as dw_session:
        yield dw_session


async def get_meta_mysql_repository(
    session: Annotated[AsyncSession, Depends(get_meta_session)],
) -> MetaMySQLRepository:
    """基于请求级 Session 创建元数据仓储"""
    return MetaMySQLRepository(session)


async def get_dw_mysql_repository(
    session: Annotated[AsyncSession, Depends(get_dw_session)],
) -> DWMySQLRepository:
    """基于请求级 Session 创建数仓仓储"""
    return DWMySQLRepository(session)


async def get_column_qdrant_repository() -> ColumnQdrantRepository:
    """创建字段向量检索仓储"""
    return ColumnQdrantRepository(
        _require(qdrant_client_manager.client, "qdrant_client_manager")
    )


async def get_metric_qdrant_repository() -> MetricQdrantRepository:
    """创建指标向量检索仓储"""
    return MetricQdrantRepository(
        _require(qdrant_client_manager.client, "qdrant_client_manager")
    )


async def get_value_es_repository() -> ValueESRepository:
    """创建字段取值全文检索仓储"""
    return ValueESRepository(_require(es_client_manager.client, "es_client_manager"))


async def get_embedding_client() -> Embeddings:
    """获取应用启动阶段初始化好的 Embedding 客户端"""
    return _require(embedding_client_manager.client, "embedding_client_manager")


async def get_query_service(
    meta_mysql_repository: Annotated[
        MetaMySQLRepository, Depends(get_meta_mysql_repository)
    ],
    embedding_client: Annotated[Embeddings, Depends(get_embedding_client)],
    dw_mysql_repository: Annotated[DWMySQLRepository, Depends(get_dw_mysql_repository)],
    column_qdrant_repository: Annotated[
        ColumnQdrantRepository, Depends(get_column_qdrant_repository)
    ],
    metric_qdrant_repository: Annotated[
        MetricQdrantRepository, Depends(get_metric_qdrant_repository)
    ],
    value_es_repository: Annotated[ValueESRepository, Depends(get_value_es_repository)],
) -> QueryService:
    """组装一次查询所需的业务服务"""
    return QueryService(
        meta_mysql_repository=meta_mysql_repository,
        embedding_client=embedding_client,
        dw_mysql_repository=dw_mysql_repository,
        column_qdrant_repository=column_qdrant_repository,
        metric_qdrant_repository=metric_qdrant_repository,
        value_es_repository=value_es_repository,
    )
