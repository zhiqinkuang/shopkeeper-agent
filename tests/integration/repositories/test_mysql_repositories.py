import pytest
from sqlalchemy import text

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo

pytestmark = pytest.mark.integration


async def test_dw_repository_reads_types_and_distinct_values(
    integration_repositories,
):
    repository = integration_repositories["dw"]

    column_types = await repository.get_column_types("dim_region")
    values = await repository.get_column_values("dim_region", "region_name", 3)

    assert "province" in column_types
    assert values == sorted(set(values))
    assert len(values) == 3


async def test_dw_repository_rejects_missing_column(integration_repositories):
    repository = integration_repositories["dw"]

    with pytest.raises(ValueError, match="字段不存在"):
        await repository.get_column_values("dim_region", "missing")


async def test_meta_repository_syncs_and_removes_stale_data(
    integration_repositories,
):
    repository = integration_repositories["meta"]
    table = TableInfo("dim_region", "dim_region", "dim", "地区维度表")
    province = ColumnInfo(
        "dim_region.province",
        "province",
        "varchar(50)",
        "dimension",
        ["广东省"],
        "省份",
        ["所在省份"],
        "dim_region",
    )
    region = ColumnInfo(
        "dim_region.region_name",
        "region_name",
        "varchar(50)",
        "dimension",
        ["华南"],
        "大区",
        ["地区"],
        "dim_region",
    )
    metric = MetricInfo(
        "RegionCount",
        "RegionCount",
        "地区数",
        ["dim_region.province"],
        ["地区数量"],
        "COUNT(DISTINCT dim_region.province)",
    )
    relation = ColumnMetric("dim_region.province", "RegionCount")

    await repository.sync_table_infos([table], [province, region])
    await repository.sync_metric_infos([metric], [relation])
    await repository.session.commit()
    assert await repository.get_column_ids() == {
        "dim_region.province",
        "dim_region.region_name",
    }
    assert await repository.get_metric_column_ids() == {"dim_region.province"}

    await repository.sync_table_infos([table], [region])
    await repository.sync_metric_infos([], [])
    await repository.session.commit()

    assert await repository.get_column_ids() == {"dim_region.region_name"}
    counts = {}
    for table_name in ("table_info", "column_info", "metric_info", "column_metric"):
        counts[table_name] = await repository.session.scalar(
            text(f"SELECT COUNT(*) FROM {table_name}")
        )
    assert counts == {
        "table_info": 1,
        "column_info": 1,
        "metric_info": 0,
        "column_metric": 0,
    }


async def test_meta_repository_migrates_legacy_formula_column(
    integration_repositories,
):
    repository = integration_repositories["meta"]
    await repository.session.execute(
        text("ALTER TABLE metric_info DROP COLUMN formula")
    )
    await repository.session.execute(
        text(
            """
            INSERT INTO metric_info
                (id, name, description, relevant_columns, alias)
            VALUES
                ('GMV', 'GMV', '成交总额',
                 JSON_ARRAY('fact_order.order_amount'),
                 JSON_ARRAY('订单总额'))
            """
        )
    )
    await repository.session.commit()

    with pytest.raises(ValueError, match="必须提供 metrics"):
        await repository.ensure_schema(can_backfill_formula=False)
    await repository.session.rollback()

    await repository.ensure_schema(can_backfill_formula=True)
    await repository.session.commit()
    metric = MetricInfo(
        "GMV",
        "GMV",
        "成交总额",
        ["fact_order.order_amount"],
        ["订单总额"],
        "SUM(fact_order.order_amount)",
    )
    await repository.sync_metric_infos([metric], [])
    await repository.session.commit()
    await repository.finalize_schema()
    await repository.session.commit()

    nullable = await repository.session.scalar(
        text(
            """
            SELECT IS_NULLABLE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = 'meta'
              AND TABLE_NAME = 'metric_info'
              AND COLUMN_NAME = 'formula'
            """
        )
    )
    assert nullable == "NO"


async def test_finalize_schema_rejects_missing_formula(
    integration_repositories,
):
    repository = integration_repositories["meta"]
    await repository.session.execute(
        text("ALTER TABLE metric_info MODIFY COLUMN formula TEXT NULL")
    )
    await repository.session.execute(
        text(
            """
            INSERT INTO metric_info
                (id, name, description, relevant_columns, alias, formula)
            VALUES ('bad', 'bad', 'bad', JSON_ARRAY(), JSON_ARRAY(), NULL)
            """
        )
    )
    await repository.session.commit()

    with pytest.raises(ValueError, match="未回填计算公式"):
        await repository.finalize_schema()
