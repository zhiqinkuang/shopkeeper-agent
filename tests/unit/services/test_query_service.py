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
        assert stream_mode == "custom"
        assert context.meta_mysql_repository == "meta"
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
            [{"type": "progress", "step": "抽取关键词", "status": "running"}],
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
                {"type": "progress", "step": "抽取关键词", "status": "success"},
                {"type": "result", "data": [{"region_name": "华北"}]},
            ]
        ),
    )
    service = QueryService("meta", "emb", "dw", "col", "metric", "value")

    messages = [item async for item in service.query("统计华北地区销售额")]

    assert [_payload(item) for item in messages] == [
        {"type": "progress", "step": "抽取关键词", "status": "success"},
        {"type": "result", "data": [{"region_name": "华北"}]},
    ]
