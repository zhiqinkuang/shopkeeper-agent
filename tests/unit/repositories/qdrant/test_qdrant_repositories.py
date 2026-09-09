from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qdrant_client.models import Distance, UpdateStatus, VectorParams

from app.repositories.qdrant.column_qdrant_repository import (
    ColumnQdrantRepository,
)
from app.repositories.qdrant.metric_qdrant_repository import (
    MetricQdrantRepository,
)

pytestmark = pytest.mark.unit


@pytest.fixture(params=[ColumnQdrantRepository, MetricQdrantRepository])
def repository(request):
    client = SimpleNamespace(
        collection_exists=AsyncMock(),
        create_collection=AsyncMock(),
        get_collection=AsyncMock(),
        upsert=AsyncMock(return_value=SimpleNamespace(status=UpdateStatus.COMPLETED)),
        scroll=AsyncMock(return_value=([], None)),
        delete=AsyncMock(return_value=SimpleNamespace(status=UpdateStatus.COMPLETED)),
        query_points=AsyncMock(),
    )
    return request.param(client), client


async def test_ensure_collection_creates_missing_collection(repository):
    repo, client = repository
    client.collection_exists.return_value = False

    await repo.ensure_collection()

    client.create_collection.assert_awaited_once()
    config = client.create_collection.await_args.kwargs["vectors_config"]
    assert config.size == 1024
    assert config.distance == Distance.COSINE


async def test_ensure_collection_accepts_matching_config(repository):
    repo, client = repository
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=VectorParams(size=1024, distance=Distance.COSINE)
            )
        )
    )

    await repo.ensure_collection()

    client.create_collection.assert_not_awaited()


async def test_ensure_collection_rejects_multi_vector_config(repository):
    repo, client = repository
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors={"a": {}}))
    )

    with pytest.raises(ValueError, match="必须使用单向量配置"):
        await repo.ensure_collection()


async def test_ensure_collection_rejects_mismatch(repository):
    repo, client = repository
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors=VectorParams(size=10, distance=Distance.DOT))
        )
    )

    with pytest.raises(ValueError, match="集合配置不匹配"):
        await repo.ensure_collection()


async def test_sync_rejects_different_input_lengths(repository):
    repo, _ = repository

    with pytest.raises(ValueError, match="数量必须一致"):
        await repo.sync(["id"], [], [{}])


async def test_sync_batches_and_deletes_stale_points(repository):
    repo, client = repository
    ids = [f"id-{index}" for index in range(21)]
    embeddings = [[0.1] * 4 for _ in ids]
    payloads = [{"id": point_id} for point_id in ids]
    client.scroll.side_effect = [
        (
            [
                SimpleNamespace(id="id-0"),
                SimpleNamespace(id="stale-1"),
            ],
            "next",
        ),
        ([SimpleNamespace(id="stale-2")], None),
    ]

    await repo.sync(ids, embeddings, payloads, batch_size=10)

    assert client.upsert.await_count == 3
    assert client.scroll.await_count == 2
    client.delete.assert_awaited_once()
    assert client.delete.await_args.kwargs["points_selector"] == [
        "stale-1",
        "stale-2",
    ]


async def test_sync_rejects_incomplete_upsert(repository):
    repo, client = repository
    client.upsert.return_value = SimpleNamespace(status=UpdateStatus.ACKNOWLEDGED)

    with pytest.raises(RuntimeError, match="写入未完成"):
        await repo.sync(["id"], [[0.1]], [{"id": "id"}])


async def test_sync_rejects_incomplete_delete(repository):
    repo, client = repository
    client.scroll.return_value = ([SimpleNamespace(id="stale")], None)
    client.delete.return_value = SimpleNamespace(status=UpdateStatus.ACKNOWLEDGED)

    with pytest.raises(RuntimeError, match="删除未完成"):
        await repo.sync([], [], [])


async def test_search_restores_entity(repository, column_info, metric_info):
    repo, client = repository
    entity = column_info if isinstance(repo, ColumnQdrantRepository) else metric_info
    client.query_points.return_value = SimpleNamespace(
        points=[SimpleNamespace(payload=entity.__dict__)]
    )

    result = await repo.search([0.1], score_threshold=0.7, limit=3)

    assert result == [entity]
    client.query_points.assert_awaited_once_with(
        collection_name=repo.collection_name,
        query=[0.1],
        limit=3,
        score_threshold=0.7,
    )
