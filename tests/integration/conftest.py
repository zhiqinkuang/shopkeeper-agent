from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from elasticsearch import AsyncElasticsearch
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from app.clients.mysql_client_manager import MySQLClientManager
from app.conf.app_config import DBConfig
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import (
    QUERY_AUDIT_TABLE_SQL,
    MetaMySQLRepository,
)
from app.repositories.qdrant.column_qdrant_repository import (
    ColumnQdrantRepository,
)
from app.repositories.qdrant.metric_qdrant_repository import (
    MetricQdrantRepository,
)
from app.services.meta_knowledge_service import MetaKnowledgeService
from tests.conftest import FakeEmbeddings

TEST_COLUMN_COLLECTION = "test_column_info_collection"
TEST_METRIC_COLLECTION = "test_metric_info_collection"
TEST_VALUE_INDEX = "test_value_index"


@pytest_asyncio.fixture
async def mysql_managers():
    meta_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "meta")
    )
    dw_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "dw")
    )
    meta_manager.init()
    dw_manager.init()
    yield meta_manager, dw_manager
    await meta_manager.close()
    await dw_manager.close()


@pytest_asyncio.fixture
async def qdrant_client() -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(
        url="http://127.0.0.1:16333",
        trust_env=False,
        check_compatibility=False,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def es_client() -> AsyncIterator[AsyncElasticsearch]:
    client = AsyncElasticsearch("http://127.0.0.1:19200")
    yield client
    await client.close()


@pytest_asyncio.fixture(autouse=True)
async def reset_integration_state(request, mysql_managers, qdrant_client, es_client):
    if request.node.get_closest_marker("integration") is None:
        yield
        return

    meta_manager, _ = mysql_managers
    async with meta_manager.session_factory() as session:
        await session.execute(text(QUERY_AUDIT_TABLE_SQL))
        for table_name in (
            "query_audit",
            "column_metric",
            "metric_info",
            "column_info",
            "table_info",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        formula_exists = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = 'meta'
                  AND TABLE_NAME = 'metric_info'
                  AND COLUMN_NAME = 'formula'
                """
            )
        )
        if not formula_exists:
            await session.execute(
                text(
                    "ALTER TABLE metric_info "
                    "ADD COLUMN formula TEXT NOT NULL COMMENT '指标计算公式'"
                )
            )
        else:
            await session.execute(
                text(
                    "ALTER TABLE metric_info "
                    "MODIFY COLUMN formula TEXT NOT NULL COMMENT '指标计算公式'"
                )
            )
        await session.commit()

    for collection_name in (TEST_COLUMN_COLLECTION, TEST_METRIC_COLLECTION):
        if await qdrant_client.collection_exists(collection_name):
            await qdrant_client.delete_collection(collection_name)
    physical_indexes = list(
        (
            await es_client.indices.get(
                index=f"{TEST_VALUE_INDEX}-*",
                allow_no_indices=True,
                ignore_unavailable=True,
            )
        ).keys()
    )
    if (
        not await es_client.indices.exists_alias(name=TEST_VALUE_INDEX)
        and await es_client.indices.exists(index=TEST_VALUE_INDEX)
    ):
        physical_indexes.append(TEST_VALUE_INDEX)
    if physical_indexes:
        await es_client.indices.delete(index=list(set(physical_indexes)))

    yield


@pytest_asyncio.fixture
async def integration_repositories(mysql_managers, qdrant_client, es_client):
    meta_manager, dw_manager = mysql_managers
    async with (
        meta_manager.session_factory() as meta_session,
        dw_manager.session_factory() as dw_session,
    ):
        yield {
            "meta": MetaMySQLRepository(meta_session),
            "dw": DWMySQLRepository(dw_session),
            "column": ColumnQdrantRepository(qdrant_client, TEST_COLUMN_COLLECTION),
            "metric": MetricQdrantRepository(qdrant_client, TEST_METRIC_COLLECTION),
            "value": ValueESRepository(es_client, TEST_VALUE_INDEX),
        }


@pytest.fixture
def integration_service(integration_repositories):
    repositories = integration_repositories
    return MetaKnowledgeService(
        meta_mysql_repository=repositories["meta"],
        dw_mysql_repository=repositories["dw"],
        column_qdrant_repository=repositories["column"],
        embedding_client=FakeEmbeddings(),
        value_es_repository=repositories["value"],
        metric_qdrant_repository=repositories["metric"],
    )
