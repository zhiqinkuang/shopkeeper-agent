from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.scripts import build_meta_knowledge

pytestmark = pytest.mark.unit


class AsyncSessionContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture
def managers(mocker):
    meta_session = object()
    dw_session = object()
    meta = SimpleNamespace(
        engine=object(),
        session_factory=Mock(return_value=AsyncSessionContext(meta_session)),
        init=Mock(),
        close=AsyncMock(),
    )
    dw = SimpleNamespace(
        engine=object(),
        session_factory=Mock(return_value=AsyncSessionContext(dw_session)),
        init=Mock(),
        close=AsyncMock(),
    )
    qdrant = SimpleNamespace(
        client=object(),
        init=Mock(),
        close=AsyncMock(),
    )
    es = SimpleNamespace(
        client=object(),
        init=Mock(),
        close=AsyncMock(),
    )
    embedding = SimpleNamespace(
        client=object(),
        http_client=object(),
        http_async_client=object(),
        init=Mock(),
        close=AsyncMock(),
    )
    mocker.patch.object(build_meta_knowledge, "meta_mysql_client_manager", meta)
    mocker.patch.object(build_meta_knowledge, "dw_mysql_client_manager", dw)
    mocker.patch.object(build_meta_knowledge, "qdrant_client_manager", qdrant)
    mocker.patch.object(build_meta_knowledge, "es_client_manager", es)
    mocker.patch.object(build_meta_knowledge, "embedding_client_manager", embedding)
    service = SimpleNamespace(build=AsyncMock())
    service_class = mocker.patch.object(
        build_meta_knowledge,
        "MetaKnowledgeService",
        return_value=service,
    )
    return SimpleNamespace(
        meta=meta,
        dw=dw,
        qdrant=qdrant,
        es=es,
        embedding=embedding,
        service=service,
        service_class=service_class,
    )


async def test_build_rejects_missing_config(tmp_path):
    with pytest.raises(FileNotFoundError, match="配置文件不存在"):
        await build_meta_knowledge.build(tmp_path / "missing.yaml")


async def test_build_wires_service_and_closes_resources(tmp_path, managers):
    config_path = tmp_path / "meta.yaml"
    config_path.write_text("tables: []\nmetrics: []\n", encoding="utf-8")

    await build_meta_knowledge.build(config_path)

    managers.service.build.assert_awaited_once_with(config_path)
    managers.service_class.assert_called_once()
    for manager in (
        managers.meta,
        managers.dw,
        managers.qdrant,
        managers.es,
        managers.embedding,
    ):
        manager.init.assert_called_once()
        manager.close.assert_awaited_once()


async def test_build_success_raises_close_errors(tmp_path, managers):
    config_path = tmp_path / "meta.yaml"
    config_path.touch()
    managers.qdrant.close.side_effect = RuntimeError("close failed")

    with pytest.raises(ExceptionGroup, match="关闭构建资源失败"):
        await build_meta_knowledge.build(config_path)

    managers.es.close.assert_awaited_once()
    managers.embedding.close.assert_awaited_once()


async def test_build_failure_preserves_original_error(tmp_path, managers, mocker):
    config_path = tmp_path / "meta.yaml"
    config_path.touch()
    managers.service.build.side_effect = ValueError("build failed")
    managers.qdrant.close.side_effect = RuntimeError("close failed")
    log_error = mocker.patch.object(build_meta_knowledge.logger, "error")

    with pytest.raises(ValueError, match="build failed"):
        await build_meta_knowledge.build(config_path)

    log_error.assert_called_once()
    managers.es.close.assert_awaited_once()


async def test_partial_initialization_still_closes_created_clients(tmp_path, managers):
    config_path = tmp_path / "meta.yaml"
    config_path.touch()
    managers.embedding.client = None
    managers.embedding.init.side_effect = RuntimeError("init failed")

    with pytest.raises(RuntimeError, match="init failed"):
        await build_meta_knowledge.build(config_path)

    managers.embedding.close.assert_awaited_once()
    managers.qdrant.close.assert_awaited_once()
