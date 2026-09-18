import json

import pytest

from app.services.query_service import QueryService

pytestmark = pytest.mark.unit


class FakeGraph:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    async def astream(self, input, context, stream_mode):
        assert input["query"] == "统计华北地区销售额"
        assert stream_mode == ["updates", "custom"]
        assert context.meta_mysql_repository is not None
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


def _payload(message: str):
    return json.loads(message.removeprefix("data: ").strip())


async def test_query_service_streams_progress_and_errors(mocker):
    mocker.patch(
        "app.services.query_service.query_graph",
        FakeGraph(
            [
                (
                    "custom",
                    {"type": "progress", "step": "抽取关键词", "status": "running"},
                )
            ],
            RuntimeError("模拟失败"),
        ),
    )
    service = QueryService("meta", "emb", "dw", "col", "metric", "value")

    messages = [item async for item in service.query("统计华北地区销售额")]

    assert _payload(messages[0]) == {
        "type": "progress",
        "step": "抽取关键词",
        "status": "running",
    }
    assert _payload(messages[1]) == {"type": "error", "message": "模拟失败"}


async def test_query_service_streams_successful_progress(mocker):
    mocker.patch(
        "app.services.query_service.query_graph",
        FakeGraph(
            [
                (
                    "custom",
                    {"type": "progress", "step": "抽取关键词", "status": "success"},
                ),
                ("custom", {"type": "result", "data": [{"region_name": "华北"}]}),
            ]
        ),
    )
    service = QueryService("meta", "emb", "dw", "col", "metric", "value")

    messages = [item async for item in service.query("统计华北地区销售额")]

    assert [_payload(item) for item in messages] == [
        {"type": "progress", "step": "抽取关键词", "status": "success"},
        {"type": "result", "data": [{"region_name": "华北"}]},
    ]


class FakeMeta:
    def __init__(self):
        self.saved = []

    async def save_query_audit(self, **record):
        self.saved.append(record)
        return record["request_id"]


async def test_query_service_writes_audit_from_graph_updates(mocker):
    meta = FakeMeta()
    mocker.patch(
        "app.services.query_service.query_graph",
        FakeGraph(
            [
                (
                    "updates",
                    {
                        "execute_sql": {
                            "sql": "SELECT 1",
                            "execution_result": [{"n": 1}],
                        }
                    },
                ),
                (
                    "updates",
                    {"generate_answer": {"answer": "结果是 1"}},
                ),
                ("custom", {"type": "answer", "text": "结果是 1"}),
            ]
        ),
    )
    mocker.patch("app.services.query_service.request_id_ctx_var").get.return_value = (
        "req-1"
    )
    service = QueryService(meta, "emb", "dw", "col", "metric", "value")

    messages = [item async for item in service.query("统计华北地区销售额")]

    assert [_payload(item) for item in messages] == [
        {"type": "answer", "text": "结果是 1"}
    ]
    assert meta.saved == [
        {
            "request_id": "req-1",
            "query": "统计华北地区销售额",
            "sql_text": "SELECT 1",
            "execution_result": [{"n": 1}],
            "answer": "结果是 1",
            "error": None,
        }
    ]
