import pytest

from app.entities.value_info import ValueInfo

pytestmark = pytest.mark.integration


async def test_value_es_sync_search_and_stale_cleanup(
    integration_repositories,
):
    repository = integration_repositories["value"]
    values = [
        ValueInfo("value-1", "华南", "dim_region.region_name"),
        ValueInfo("value-2", "华东", "dim_region.region_name"),
    ]

    await repository.ensure_index()
    await repository.sync(values)

    result = await repository.search("华南", score_threshold=0.0)
    assert result == [values[0]]

    await repository.sync([values[1]])
    assert (await repository.client.count(index=repository.index_name))["count"] == 1
    assert await repository.search("华南", score_threshold=0.0) == []

    await repository.sync([])
    assert (await repository.client.count(index=repository.index_name))["count"] == 0
