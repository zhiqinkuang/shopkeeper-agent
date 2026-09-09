from dataclasses import asdict

import pytest

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo

pytestmark = pytest.mark.integration


async def test_column_qdrant_sync_search_and_stale_cleanup(
    integration_repositories,
):
    repository = integration_repositories["column"]
    first = ColumnInfo(
        "dim_region.province",
        "province",
        "varchar(50)",
        "dimension",
        ["广东省"],
        "省份",
        ["所在省份"],
        "dim_region",
    )
    second = ColumnInfo(
        "dim_region.region_name",
        "region_name",
        "varchar(50)",
        "dimension",
        ["华南"],
        "大区",
        ["地区"],
        "dim_region",
    )
    await repository.ensure_collection()
    await repository.sync(
        [
            "11111111-1111-5111-8111-111111111111",
            "22222222-2222-5222-8222-222222222222",
        ],
        [[1.0] + [0.0] * 1023, [0.0, 1.0] + [0.0] * 1022],
        [asdict(first), asdict(second)],
    )

    result = await repository.search([1.0] + [0.0] * 1023, score_threshold=0.9)
    assert result == [first]

    await repository.sync(
        ["22222222-2222-5222-8222-222222222222"],
        [[0.0, 1.0] + [0.0] * 1022],
        [asdict(second)],
    )
    assert (
        await repository.client.count(repository.collection_name, exact=True)
    ).count == 1


async def test_metric_qdrant_sync_search_and_stale_cleanup(
    integration_repositories,
):
    repository = integration_repositories["metric"]
    metric = MetricInfo(
        "GMV",
        "GMV",
        "成交总额",
        ["fact_order.order_amount"],
        ["订单总额"],
        "SUM(fact_order.order_amount)",
    )
    point_id = "33333333-3333-5333-8333-333333333333"
    vector = [1.0] + [0.0] * 1023

    await repository.ensure_collection()
    await repository.sync([point_id], [vector], [asdict(metric)])

    assert await repository.search(vector, score_threshold=0.9) == [metric]
    await repository.sync([], [], [])
    assert (
        await repository.client.count(repository.collection_name, exact=True)
    ).count == 0
