from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.scripts import query_agent

pytestmark = pytest.mark.unit


class SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def _patch_managers(mocker, graph_updates):
    qdrant = SimpleNamespace(init=Mock(), close=AsyncMock(), client="qdrant")
    embedding = SimpleNamespace(init=Mock(), close=AsyncMock(), client="embedding")
    es = SimpleNamespace(init=Mock(), close=AsyncMock(), client="es")
    meta = SimpleNamespace(
        init=Mock(),
        close=AsyncMock(),
        session_factory=lambda: SessionContext("meta"),
    )
    dw = SimpleNamespace(
        init=Mock(),
        close=AsyncMock(),
        session_factory=lambda: SessionContext("dw"),
    )
    mocker.patch.object(query_agent, "qdrant_client_manager", qdrant)
    mocker.patch.object(query_agent, "embedding_client_manager", embedding)
    mocker.patch.object(query_agent, "es_client_manager", es)
    mocker.patch.object(query_agent, "meta_mysql_client_manager", meta)
    mocker.patch.object(query_agent, "dw_mysql_client_manager", dw)

    async def astream(input, context, stream_mode):
        assert input == {"query": "统计华北地区销售额"}
        assert stream_mode == "updates"
        for update in graph_updates:
            yield update

    mocker.patch.object(
        query_agent, "query_graph", SimpleNamespace(astream=astream)
    )
    return qdrant, embedding, es, meta, dw


async def test_query_agent_run_succeeds_and_closes_clients(mocker):
    managers = await _patch_managers(
        mocker,
        [
            {
                "execute_sql": {
                    "execution_result": [{"n": 1}],
                    "error": None,
                }
            }
        ],
    )

    succeeded = await query_agent.run("统计华北地区销售额", 2, 0)

    assert succeeded is True
    for manager in managers:
        manager.close.assert_awaited_once()


async def test_query_agent_run_marks_error_updates_as_failure(mocker):
    await _patch_managers(mocker, [{"validate_sql": {"error": "SQL 失败"}}])

    succeeded = await query_agent.run("统计华北地区销售额", 2, 0)

    assert succeeded is False


async def test_query_agent_run_ignores_intermediate_validation_error(mocker):
    await _patch_managers(
        mocker,
        [
            {"validate_sql": {"sql_valid": False, "error": "Unknown column"}},
            {
                "execute_sql": {
                    "execution_result": [{"gmv": 41099.5}],
                    "error": None,
                }
            },
        ],
    )

    succeeded = await query_agent.run("统计华北地区销售额", 2, 0)

    assert succeeded is True


def test_query_agent_main_rejects_negative_attempts(mocker):
    mocker.patch(
        "sys.argv",
        ["query_agent", "问题", "--max-correction-attempts", "-1"],
    )

    with pytest.raises(SystemExit):
        query_agent.main()
