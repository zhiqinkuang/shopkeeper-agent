import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import (
    _require,
    get_column_qdrant_repository,
    get_dw_mysql_repository,
    get_dw_session,
    get_embedding_client,
    get_meta_mysql_repository,
    get_meta_session,
    get_metric_qdrant_repository,
    get_query_service,
    get_value_es_repository,
)
from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var
from app.services.query_service import QueryService
from main import add_request_id

pytestmark = pytest.mark.unit


class FakeService:
    async def query(self, query: str):
        yield f'data: {json.dumps({"type": "progress", "step": query}, ensure_ascii=False)}\n\n'


def _query_app(service=None) -> FastAPI:
    app = FastAPI()
    app.include_router(query_router)
    if service is not None:
        app.dependency_overrides[get_query_service] = lambda: service
    return app


def test_request_id_middleware_sets_unique_context():
    captured = {}
    app = FastAPI()
    app.middleware("http")(add_request_id)

    @app.get("/ping")
    async def ping():
        captured["request_id"] = request_id_ctx_var.get()
        return {"ok": True}

    with TestClient(app) as client:
        first = client.get("/ping")
        first_id = captured["request_id"]
        second = client.get("/ping")
        second_id = captured["request_id"]

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["x-request-id"] == first_id
    assert second.headers["x-request-id"] == second_id
    assert first_id != "1"
    assert second_id != "1"
    assert first_id != second_id


def test_query_router_streams_service_output():
    with TestClient(_query_app(FakeService())) as client:
        response = client.post("/api/query", json={"query": "统计华北地区销售额"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "统计华北地区销售额" in response.text


def test_get_query_audit_replays_sql():
    class FakeMeta:
        async def get_query_audit(self, request_id: str):
            assert request_id == "req-1"
            return {
                "id": "req-1",
                "request_id": "req-1",
                "query": "统计华北地区销售额",
                "sql_text": "SELECT 1",
                "execution_result": [{"n": 1}],
                "answer": "结果是 1",
                "error": None,
                "created_at": None,
            }

    app = _query_app()
    app.dependency_overrides[get_meta_mysql_repository] = lambda: FakeMeta()

    with TestClient(app) as client:
        response = client.get("/api/audits/req-1")

    assert response.status_code == 200
    assert response.json()["sql"] == "SELECT 1"
    assert response.json()["query"] == "统计华北地区销售额"


def test_get_query_audit_returns_404_when_missing():
    class FakeMeta:
        async def get_query_audit(self, request_id: str):
            return None

    app = _query_app()
    app.dependency_overrides[get_meta_mysql_repository] = lambda: FakeMeta()

    with TestClient(app) as client:
        response = client.get("/api/audits/missing")

    assert response.status_code == 404


def test_query_router_rejects_invalid_contract():
    with TestClient(_query_app(FakeService())) as client:
        missing = client.post("/api/query", json={})
        wrong_type = client.post("/api/query", json={"query": 1})
        no_body = client.post("/api/query")
        wrong_method = client.get("/api/query")

    assert missing.status_code == 422
    assert wrong_type.status_code == 422
    assert no_body.status_code == 422
    assert wrong_method.status_code == 405


def test_query_router_streams_error_event_as_sse():
    class ErrorService:
        async def query(self, query: str):
            yield f"data: {json.dumps({'type': 'error', 'message': query}, ensure_ascii=False)}\n\n"

    with TestClient(_query_app(ErrorService())) as client:
        response = client.post("/api/query", json={"query": "boom"})

    assert response.status_code == 200
    assert json.loads(response.text.removeprefix("data: ").strip()) == {
        "type": "error",
        "message": "boom",
    }


def test_query_router_returns_503_when_clients_uninitialized(mocker):
    mocker.patch(
        "app.api.dependencies.meta_mysql_client_manager",
        SimpleNamespace(session_factory=None),
    )

    with TestClient(_query_app()) as client:
        response = client.post("/api/query", json={"query": "统计华北地区销售额"})

    assert response.status_code == 503
    assert "meta_mysql_client_manager" in response.json()["detail"]


def test_require_uninitialized_dependency_returns_503():
    with pytest.raises(HTTPException) as error:
        _require(None, "qdrant_client_manager")

    assert error.value.status_code == 503
    assert "qdrant_client_manager" in error.value.detail


async def test_repository_dependencies_assemble_from_injected_resources(mocker):
    mocker.patch(
        "app.api.dependencies.qdrant_client_manager",
        SimpleNamespace(client="qdrant"),
    )
    mocker.patch(
        "app.api.dependencies.es_client_manager",
        SimpleNamespace(client="es"),
    )
    mocker.patch(
        "app.api.dependencies.embedding_client_manager",
        SimpleNamespace(client="embedding"),
    )

    column = await get_column_qdrant_repository()
    metric = await get_metric_qdrant_repository()
    value = await get_value_es_repository()
    embedding = await get_embedding_client()
    meta = await get_meta_mysql_repository("meta-session")
    dw = await get_dw_mysql_repository("dw-session")
    service = await get_query_service(meta, embedding, dw, column, metric, value)

    assert isinstance(service, QueryService)
    assert service.embedding_client == "embedding"
    assert service.meta_mysql_repository.session == "meta-session"
    assert service.dw_mysql_repository.session == "dw-session"


async def test_session_dependencies_yield_and_close(mocker):
    class SessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    mocker.patch(
        "app.api.dependencies.meta_mysql_client_manager",
        SimpleNamespace(session_factory=lambda: SessionContext("meta")),
    )
    mocker.patch(
        "app.api.dependencies.dw_mysql_client_manager",
        SimpleNamespace(session_factory=lambda: SessionContext("dw")),
    )

    meta_gen = get_meta_session()
    dw_gen = get_dw_session()
    assert await meta_gen.__anext__() == "meta"
    assert await dw_gen.__anext__() == "dw"
    with pytest.raises(StopAsyncIteration):
        await meta_gen.__anext__()
    with pytest.raises(StopAsyncIteration):
        await dw_gen.__anext__()


async def test_lifespan_initializes_and_closes_managers(mocker):
    managers = {
        "qdrant": SimpleNamespace(init=Mock(), close=AsyncMock()),
        "embedding": SimpleNamespace(init=Mock(), close=AsyncMock()),
        "es": SimpleNamespace(init=Mock(), close=AsyncMock()),
        "meta": SimpleNamespace(init=Mock(), close=AsyncMock()),
        "dw": SimpleNamespace(init=Mock(), close=AsyncMock()),
    }
    mocker.patch("app.api.lifespan.qdrant_client_manager", managers["qdrant"])
    mocker.patch("app.api.lifespan.embedding_client_manager", managers["embedding"])
    mocker.patch("app.api.lifespan.es_client_manager", managers["es"])
    mocker.patch("app.api.lifespan.meta_mysql_client_manager", managers["meta"])
    mocker.patch("app.api.lifespan.dw_mysql_client_manager", managers["dw"])

    async with lifespan(SimpleNamespace()):
        for manager in managers.values():
            manager.init.assert_called_once()

    for manager in managers.values():
        manager.close.assert_awaited_once()
