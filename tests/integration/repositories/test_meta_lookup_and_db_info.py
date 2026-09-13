import pytest

from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo

pytestmark = pytest.mark.integration


async def test_meta_repository_looks_up_table_column_and_keys(
    integration_repositories,
):
    repository = integration_repositories["meta"]
    table = TableInfo("dim_region", "dim_region", "dim", "地区维度表")
    region = ColumnInfo(
        "dim_region.region_name",
        "region_name",
        "varchar(50)",
        "dimension",
        ["华北"],
        "地区名称",
        ["地区"],
        "dim_region",
    )
    region_id = ColumnInfo(
        "dim_region.region_id",
        "region_id",
        "bigint",
        "primary_key",
        [],
        "地区主键",
        [],
        "dim_region",
    )
    await repository.sync_table_infos([table], [region, region_id])
    await repository.session.commit()

    loaded_table = await repository.get_table_info_by_id("dim_region")
    loaded_column = await repository.get_column_info_by_id("dim_region.region_name")
    key_columns = await repository.get_key_columns_by_table_id("dim_region")

    assert loaded_table == table
    assert loaded_column == region
    assert [column.id for column in key_columns] == ["dim_region.region_id"]

    with pytest.raises(LookupError, match="字段元数据不存在"):
        await repository.get_column_info_by_id("missing.column")
    with pytest.raises(LookupError, match="表元数据不存在"):
        await repository.get_table_info_by_id("missing_table")


async def test_dw_repository_reads_dialect_and_version(integration_repositories):
    db_info = await integration_repositories["dw"].get_db_info()

    assert db_info["dialect"] == "mysql"
    assert db_info["version"]
