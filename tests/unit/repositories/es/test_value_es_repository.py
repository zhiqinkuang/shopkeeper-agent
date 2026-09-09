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
        exists=AsyncMock(),
        create=AsyncMock(),
        get_mapping=AsyncMock(),
        put_mapping=AsyncMock(),
        refresh=AsyncMock(),
    )
    client = SimpleNamespace(
        indices=indices,
        bulk=AsyncMock(return_value={"errors": False, "items": []}),
        delete_by_query=AsyncMock(
            return_value={
                "timed_out": False,
                "version_conflicts": 0,
                "failures": [],
            }
        ),
        search=AsyncMock(),
    )
    repo = ValueESRepository(client)
    repo.index_name = "test_values"
    return repo, client


def valid_mapping(repo):
    mapping = deepcopy(repo.index_mappings)
    mapping["dynamic"] = "false"
    mapping["properties"]["value"].pop("search_analyzer")
    return {repo.index_name: {"mappings": mapping}}


async def test_ensure_index_creates_missing_index(repository):
    repo, client = repository
    client.indices.exists.return_value = False

    await repo.ensure_index()

    client.indices.create.assert_awaited_once_with(
        index=repo.index_name,
        mappings=repo.index_mappings,
    )


async def test_ensure_index_accepts_valid_mapping(repository):
    repo, client = repository
    client.indices.exists.return_value = True
    client.indices.get_mapping.return_value = valid_mapping(repo)

    await repo.ensure_index()

    client.indices.put_mapping.assert_not_awaited()


async def test_ensure_index_upgrades_build_id_mapping(repository):
    repo, client = repository
    client.indices.exists.return_value = True
    mapping = valid_mapping(repo)
    mapping[repo.index_name]["mappings"]["properties"].pop("build_id")
    client.indices.get_mapping.return_value = mapping

    await repo.ensure_index()

    client.indices.put_mapping.assert_awaited_once_with(
        index=repo.index_name,
        properties={"build_id": {"type": "keyword"}},
    )


async def test_ensure_index_rejects_dynamic_mapping(repository):
    repo, client = repository
    client.indices.exists.return_value = True
    mapping = valid_mapping(repo)
    mapping[repo.index_name]["mappings"]["dynamic"] = True
    client.indices.get_mapping.return_value = mapping

    with pytest.raises(ValueError, match="必须关闭动态映射"):
        await repo.ensure_index()


async def test_ensure_index_rejects_missing_or_wrong_mapping(repository):
    repo, client = repository
    client.indices.exists.return_value = True
    mapping = valid_mapping(repo)
    mapping[repo.index_name]["mappings"]["properties"].pop("column_id")
    client.indices.get_mapping.return_value = mapping

    with pytest.raises(ValueError, match="缺少映射字段"):
        await repo.ensure_index()

    mapping = valid_mapping(repo)
    mapping[repo.index_name]["mappings"]["properties"]["value"]["analyzer"] = "standard"
    client.indices.get_mapping.return_value = mapping
    with pytest.raises(ValueError, match="映射不匹配"):
        await repo.ensure_index()


async def test_sync_writes_build_marker_and_deletes_stale(repository):
    repo, client = repository
    values = [
        ValueInfo("id-1", "华南", "dim_region.region_name"),
        ValueInfo("id-2", "华东", "dim_region.region_name"),
    ]

    await repo.sync(values, batch_size=1)

    assert client.bulk.await_count == 2
    first_operations = client.bulk.await_args_list[0].kwargs["operations"]
    assert first_operations[0] == {"index": {"_index": repo.index_name, "_id": "id-1"}}
    build_id = first_operations[1]["build_id"]
    assert first_operations[1]["value"] == "华南"
    second_operations = client.bulk.await_args_list[1].kwargs["operations"]
    assert second_operations[1]["build_id"] == build_id
    client.indices.refresh.assert_awaited_once_with(index=repo.index_name)
    assert client.delete_by_query.await_args.kwargs["query"] == {
        "bool": {"must_not": [{"term": {"build_id": build_id}}]}
    }


async def test_sync_empty_values_clears_index(repository):
    repo, client = repository

    await repo.sync([])

    client.bulk.assert_not_awaited()
    client.indices.refresh.assert_not_awaited()
    assert client.delete_by_query.await_args.kwargs["query"] == {"match_all": {}}


async def test_sync_raises_for_bulk_failure(repository):
    repo, client = repository
    client.bulk.return_value = {
        "errors": True,
        "items": [{"index": {"_id": "id-1", "error": {"type": "bad"}}}],
    }

    with pytest.raises(RuntimeError, match="批量写入失败"):
        await repo.sync([ValueInfo("id-1", "华南", "column")])

    client.delete_by_query.assert_not_awaited()


@pytest.mark.parametrize(
    "delete_result",
    [
        {"timed_out": True, "version_conflicts": 0, "failures": []},
        {"timed_out": False, "version_conflicts": 1, "failures": []},
        {
            "timed_out": False,
            "version_conflicts": 0,
            "failures": [{"cause": "failed"}],
        },
    ],
)
async def test_sync_raises_for_delete_failure(repository, delete_result):
    repo, client = repository
    client.delete_by_query.return_value = delete_result

    with pytest.raises(RuntimeError, match="陈旧字段取值删除失败"):
        await repo.sync([])


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
                        "build_id": "build",
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
