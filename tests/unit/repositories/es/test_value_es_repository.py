from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def repository():
    indices = SimpleNamespace(
        exists=AsyncMock(return_value=False),
        exists_alias=AsyncMock(return_value=False),
        create=AsyncMock(),
        get_mapping=AsyncMock(),
        get_alias=AsyncMock(return_value={}),
        update_aliases=AsyncMock(),
        refresh=AsyncMock(),
        get=AsyncMock(return_value={}),
        delete=AsyncMock(),
    )
    client = SimpleNamespace(
        indices=indices,
        bulk=AsyncMock(return_value={"errors": False, "items": []}),
        count=AsyncMock(return_value={"count": 0}),
        search=AsyncMock(),
    )
    return ValueESRepository(client, "test_values"), client


def valid_mapping(repo, physical_index="test_values-current"):
    mapping = deepcopy(repo.index_mappings)
    mapping["dynamic"] = "false"
    mapping["properties"]["value"].pop("search_analyzer")
    return {physical_index: {"mappings": mapping}}


async def test_ensure_index_allows_missing_alias(repository):
    repo, client = repository

    await repo.ensure_index()

    client.indices.create.assert_not_awaited()


async def test_ensure_index_rejects_concrete_name_conflict(repository):
    repo, client = repository
    client.indices.exists.return_value = True

    with pytest.raises(ValueError, match="同名物理索引冲突"):
        await repo.ensure_index()


async def test_ensure_index_accepts_valid_single_alias(repository):
    repo, client = repository
    client.indices.exists_alias.return_value = True
    client.indices.get_mapping.return_value = valid_mapping(repo)

    await repo.ensure_index()

    client.indices.get_mapping.assert_awaited_once_with(index=repo.index_name)


async def test_ensure_index_rejects_multiple_alias_targets(repository):
    repo, client = repository
    client.indices.exists_alias.return_value = True
    mapping = valid_mapping(repo)
    mapping["test_values-other"] = mapping["test_values-current"]
    client.indices.get_mapping.return_value = mapping

    with pytest.raises(ValueError, match="只指向一个物理索引"):
        await repo.ensure_index()


async def test_ensure_index_rejects_wrong_mapping(repository):
    repo, client = repository
    client.indices.exists_alias.return_value = True
    mapping = valid_mapping(repo)
    mapping["test_values-current"]["mappings"]["dynamic"] = True
    client.indices.get_mapping.return_value = mapping
    with pytest.raises(ValueError, match="必须关闭动态映射"):
        await repo.ensure_index()

    mapping = valid_mapping(repo)
    mapping["test_values-current"]["mappings"]["properties"].pop("column_id")
    client.indices.get_mapping.return_value = mapping
    with pytest.raises(ValueError, match="缺少映射字段"):
        await repo.ensure_index()

    mapping = valid_mapping(repo)
    mapping["test_values-current"]["mappings"]["properties"]["value"]["analyzer"] = (
        "standard"
    )
    client.indices.get_mapping.return_value = mapping
    with pytest.raises(ValueError, match="映射不匹配"):
        await repo.ensure_index()


async def test_sync_builds_index_switches_alias_and_removes_stale(repository):
    repo, client = repository
    values = [
        ValueInfo("id-1", "华南", "dim_region.region_name"),
        ValueInfo("id-2", "华东", "dim_region.region_name"),
    ]
    client.count.return_value = {"count": 2}
    client.indices.exists_alias.return_value = True
    client.indices.get_alias.return_value = {"test_values-old": {}}
    client.indices.get.return_value = {
        "test_values-old": {},
        "test_values-orphan": {},
    }

    await repo.sync(values, batch_size=1)

    assert client.bulk.await_count == 2
    physical_index = client.indices.create.await_args.kwargs["index"]
    assert physical_index.startswith("test_values-")
    first_operations = client.bulk.await_args_list[0].kwargs["operations"]
    assert first_operations == [
        {"index": {"_index": physical_index, "_id": "id-1"}},
        {
            "id": "id-1",
            "value": "华南",
            "column_id": "dim_region.region_name",
        },
    ]
    client.indices.refresh.assert_awaited_once_with(index=physical_index)
    client.indices.update_aliases.assert_awaited_once_with(
        actions=[
            {
                "remove": {
                    "index": "test_values-old",
                    "alias": "test_values",
                }
            },
            {"add": {"index": physical_index, "alias": "test_values"}},
        ]
    )
    client.indices.delete.assert_awaited_once_with(
        index=["test_values-old", "test_values-orphan"]
    )


async def test_sync_empty_snapshot_still_switches_to_empty_index(repository):
    repo, client = repository

    await repo.sync([])

    physical_index = client.indices.create.await_args.kwargs["index"]
    client.bulk.assert_not_awaited()
    client.indices.refresh.assert_awaited_once_with(index=physical_index)
    client.count.assert_awaited_once_with(index=physical_index)
    client.indices.update_aliases.assert_awaited_once()


async def test_sync_removes_new_index_when_bulk_fails(repository):
    repo, client = repository
    client.bulk.return_value = {
        "errors": True,
        "items": [{"index": {"_id": "id-1", "error": {"type": "bad"}}}],
    }
    client.indices.exists.return_value = True

    with pytest.raises(RuntimeError, match="批量写入失败"):
        await repo.sync([ValueInfo("id-1", "华南", "column")])

    physical_index = client.indices.create.await_args.kwargs["index"]
    client.indices.delete.assert_awaited_once_with(index=physical_index)
    client.indices.update_aliases.assert_not_awaited()


async def test_sync_rejects_count_mismatch_before_alias_switch(repository):
    repo, client = repository
    client.indices.exists.return_value = True

    with pytest.raises(RuntimeError, match="写入数量不匹配"):
        await repo.sync([ValueInfo("id-1", "华南", "column")])

    client.indices.update_aliases.assert_not_awaited()


async def test_sync_keeps_new_index_after_alias_switch_failure(repository):
    repo, client = repository
    client.indices.get.return_value = {"test_values-old": {}}
    client.indices.delete.side_effect = RuntimeError("delete failed")

    with pytest.raises(RuntimeError, match="delete failed"):
        await repo.sync([])

    assert client.indices.delete.await_count == 1


async def test_search_restores_value_entities(repository):
    repo, client = repository
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "id": "id-1",
                        "value": "华南",
                        "column_id": "dim_region.region_name",
                    }
                }
            ]
        }
    }

    result = await repo.search("华南", score_threshold=0.8, limit=2)

    assert result == [ValueInfo("id-1", "华南", "dim_region.region_name")]
    client.search.assert_awaited_once_with(
        index=repo.index_name,
        query={"match": {"value": "华南"}},
        size=2,
        min_score=0.8,
    )
