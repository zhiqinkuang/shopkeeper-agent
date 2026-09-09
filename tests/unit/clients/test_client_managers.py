from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.clients.embedding_client_manager import EmbeddingClientManager
from app.clients.es_client_manager import ESClientManager
from app.clients.mysql_client_manager import MySQLClientManager
from app.clients.qdrant_client_manager import QdrantClientManager
from app.conf.app_config import DBConfig, EmbeddingConfig, ESConfig, QdrantConfig

pytestmark = pytest.mark.unit


def _create_mysql_manager(mocker):
    engine = SimpleNamespace(dispose=AsyncMock())
    session_factory = object()
    create_engine = mocker.patch(
        "app.clients.mysql_client_manager.create_async_engine",
        return_value=engine,
    )
    create_factory = mocker.patch(
        "app.clients.mysql_client_manager.async_sessionmaker",
        return_value=session_factory,
    )
    manager = MySQLClientManager(DBConfig("db", 3306, "user", "password", "meta"))

    manager.init()

    assert manager.session_factory is session_factory
    create_engine.assert_called_once_with(
        "mysql+asyncmy://user:password@db:3306/meta?charset=utf8mb4",
        pool_size=10,
        pool_pre_ping=True,
    )
    create_factory.assert_called_once_with(
        engine, autoflush=True, expire_on_commit=False
    )

    return manager, engine


def test_mysql_manager_initializes(mocker):
    manager, _ = _create_mysql_manager(mocker)

    assert manager.engine is not None


async def test_mysql_manager_close(mocker):
    manager, engine = _create_mysql_manager(mocker)

    await manager.close()

    engine.dispose.assert_awaited_once()


async def test_es_manager_lifecycle(mocker):
    client = SimpleNamespace(close=AsyncMock())
    client_class = mocker.patch(
        "app.clients.es_client_manager.AsyncElasticsearch",
        return_value=client,
    )
    manager = ESClientManager(ESConfig("es", 9200, "values"))

    manager.init()
    await manager.close()

    client_class.assert_called_once_with(hosts=["http://es:9200"])
    client.close.assert_awaited_once()


async def test_qdrant_manager_lifecycle(mocker):
    client = SimpleNamespace(close=AsyncMock())
    client_class = mocker.patch(
        "app.clients.qdrant_client_manager.AsyncQdrantClient",
        return_value=client,
    )
    manager = QdrantClientManager(QdrantConfig("qdrant", 6333, 1024))

    manager.init()
    await manager.close()

    client_class.assert_called_once_with(
        url="http://qdrant:6333",
        trust_env=False,
        check_compatibility=True,
    )
    client.close.assert_awaited_once()


async def test_embedding_manager_lifecycle(mocker):
    sync_http = SimpleNamespace(close=Mock())
    async_http = SimpleNamespace(aclose=AsyncMock())
    mocker.patch(
        "app.clients.embedding_client_manager.httpx.Client",
        return_value=sync_http,
    )
    mocker.patch(
        "app.clients.embedding_client_manager.httpx.AsyncClient",
        return_value=async_http,
    )
    embedding = object()
    embedding_class = mocker.patch(
        "app.clients.embedding_client_manager.OpenAIEmbeddings",
        return_value=embedding,
    )
    manager = EmbeddingClientManager(
        EmbeddingConfig("https://embedding.test", "model", "key")
    )

    manager.init()
    await manager.close()

    assert manager.client is None
    assert manager.http_client is None
    assert manager.http_async_client is None
    embedding_class.assert_called_once()
    sync_http.close.assert_called_once()
    async_http.aclose.assert_awaited_once()


async def test_embedding_manager_close_is_idempotent():
    manager = EmbeddingClientManager(
        EmbeddingConfig("https://embedding.test", "model", "key")
    )

    await manager.close()

    assert manager.client is None
