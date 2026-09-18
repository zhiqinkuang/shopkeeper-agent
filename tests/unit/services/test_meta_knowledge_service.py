import copy
import uuid
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from app.entities.column_metric import ColumnMetric
from app.entities.table_info import TableInfo
from tests.conftest import FakeEmbeddings

pytestmark = pytest.mark.unit


def test_validate_text_rejects_blank(service_factory):
    service, _ = service_factory()

    with pytest.raises(ValueError, match="表名不能为空"):
        service._validate_text("表名", "  ")


def test_validate_aliases_rejects_blank_and_duplicate(service_factory):
    service, _ = service_factory()

    with pytest.raises(ValueError, match="别名不能为空"):
        service._validate_aliases("字段 x", ["正常", " "])
    with pytest.raises(ValueError, match="重复别名"):
        service._validate_aliases("字段 x", ["省份", "省份"])


def test_validate_max_length_rejects_oversized_value(service_factory):
    service, _ = service_factory()

    with pytest.raises(ValueError, match="长度不能超过 64"):
        service._validate_max_length("字段 ID", "x" * 65, 64)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda config: setattr(config.tables[0], "name", ""), "表名不能为空"),
        (lambda config: setattr(config.tables[0], "role", "unknown"), "角色无效"),
        (
            lambda config: setattr(config.tables[0].columns[0], "role", "unknown"),
            "角色无效",
        ),
        (
            lambda config: setattr(config.metrics[0], "formula", " "),
            "计算公式不能为空",
        ),
        (
            lambda config: setattr(config.metrics[0], "relevant_columns", []),
            "必须关联至少一个字段",
        ),
        (
            lambda config: setattr(
                config.metrics[0], "relevant_columns", ["dim_region.missing"]
            ),
            "引用了未配置字段",
        ),
        (
            lambda config: setattr(
                config.metrics[0], "relevant_columns", ["invalid-column"]
            ),
            "关联字段格式无效",
        ),
    ],
)
async def test_validate_meta_config_rejects_invalid_values(
    service_factory, minimal_config, mutation, message
):
    service, _ = service_factory()
    config = copy.deepcopy(minimal_config)
    mutation(config)

    with pytest.raises(ValueError, match=message):
        await service._validate_meta_config(config)


async def test_validate_meta_config_rejects_missing_dw_table(
    service_factory, minimal_config
):
    service, dependencies = service_factory()
    dependencies.dw.get_column_types.return_value = {}

    with pytest.raises(ValueError, match="数仓表不存在"):
        await service._validate_meta_config(minimal_config)


async def test_validate_meta_config_rejects_duplicate_table(
    service_factory, minimal_config
):
    service, _ = service_factory()
    config = copy.deepcopy(minimal_config)
    config.tables.append(copy.deepcopy(config.tables[0]))

    with pytest.raises(ValueError, match="存在重复表"):
        await service._validate_meta_config(config)


async def test_embed_texts_batches_and_validates_count(service_factory):
    embedding = FakeEmbeddings(dimensions=4)
    service, _ = service_factory(embedding)
    texts = [f"text-{index}" for index in range(11)]

    result = await service._embed_texts(texts)

    assert len(result) == 11
    assert [len(batch) for batch in embedding.batches] == [10, 1]

    embedding.aembed_documents = AsyncMock(return_value=[])
    with pytest.raises(ValueError, match="返回数量不匹配"):
        await service._embed_texts(["x"])


async def test_collect_table_infos_normalizes_examples(service_factory, minimal_config):
    service, dependencies = service_factory()
    dependencies.dw.get_column_values.return_value = [1, "广东省"]

    tables, columns = await service._collect_table_infos(
        minimal_config, {"dim_region": {"province": "varchar(50)"}}
    )

    assert tables == [
        TableInfo(
            id="dim_region",
            name="dim_region",
            role="dim",
            description="地区维度表",
        )
    ]
    assert columns[0].examples == ["1", "广东省"]


async def test_column_points_are_stable_and_complete(service_factory, column_info):
    service, dependencies = service_factory(FakeEmbeddings(dimensions=4))

    await service._save_column_info_to_qdrant([column_info])

    ids, embeddings, payloads = dependencies.column.sync.await_args.args
    assert len(ids) == len(embeddings) == len(payloads) == 4
    assert ids[0] == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "column:dim_region.province:name:province",
        )
    )
    assert payloads == [asdict(column_info)] * 4


async def test_metric_points_are_stable_and_complete(service_factory, metric_info):
    service, dependencies = service_factory(FakeEmbeddings(dimensions=4))

    await service._save_metrics_to_qdrant([metric_info])

    ids, embeddings, payloads = dependencies.metric.sync.await_args.args
    assert len(ids) == len(embeddings) == len(payloads) == 3
    assert ids[-1] == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "metric:RegionCount:alias:地区数",
        )
    )
    assert payloads == [asdict(metric_info)] * 3


async def test_value_sync_filters_columns_and_uses_stable_ids(
    service_factory, minimal_config, column_info
):
    service, dependencies = service_factory()
    dependencies.dw.get_column_values.return_value = [1, "1", "广东省"]

    await service._save_value_info_to_es(minimal_config, [column_info])

    values = dependencies.value.sync.await_args.args[0]
    assert [value.value for value in values] == ["1", "广东省"]
    assert values[0].id == str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            "value:dim_region.province:1",
        )
    )
    dependencies.dw.session.rollback.assert_awaited_once()

    config = copy.deepcopy(minimal_config)
    config.tables[0].columns[0].sync = False
    dependencies.value.sync.reset_mock()
    await service._save_value_info_to_es(config, [column_info])
    assert dependencies.value.sync.await_args.args[0] == []


async def test_value_sync_rejects_more_than_limit(
    service_factory, minimal_config, column_info
):
    service, dependencies = service_factory()
    dependencies.dw.get_column_values.return_value = range(100001)

    with pytest.raises(ValueError, match="超过同步上限"):
        await service._save_value_info_to_es(minimal_config, [column_info])

    dependencies.value.sync.assert_not_awaited()


async def test_save_meta_commits_all_data_once_then_finalizes_schema(
    service_factory, minimal_config, column_info, metric_info
):
    service, dependencies = service_factory()
    table = TableInfo("dim_region", "dim_region", "dim", "地区维度表")
    relation = ColumnMetric("dim_region.province", "RegionCount")

    await service._save_meta_to_db(
        minimal_config, [table], [column_info], [metric_info], [relation]
    )

    dependencies.meta.sync_table_infos.assert_awaited_once_with([table], [column_info])
    dependencies.meta.sync_metric_infos.assert_awaited_once_with(
        [metric_info], [relation]
    )
    assert dependencies.meta.session.commit.await_count == 2
    dependencies.meta.finalize_schema.assert_awaited_once()


async def test_save_meta_rolls_back_on_failure(service_factory, minimal_config):
    service, dependencies = service_factory()
    dependencies.meta.sync_table_infos.side_effect = RuntimeError("db failed")

    with pytest.raises(RuntimeError, match="db failed"):
        await service._save_meta_to_db(minimal_config, [], [], [], [])

    dependencies.meta.session.rollback.assert_awaited_once()


async def test_build_runs_complete_pipeline(service_factory, minimal_config, tmp_path):
    from omegaconf import OmegaConf

    service, dependencies = service_factory(FakeEmbeddings(dimensions=4))
    config_path = tmp_path / "meta.yaml"
    OmegaConf.save(OmegaConf.structured(minimal_config), config_path)

    await service.build(config_path)

    dependencies.meta.ensure_schema.assert_awaited_once_with(can_backfill_formula=True)
    dependencies.column.sync.assert_awaited_once()
    dependencies.value.sync.assert_awaited_once()
    dependencies.metric.sync.assert_awaited_once()
    dependencies.meta.sync_table_infos.assert_awaited_once()
    dependencies.meta.sync_metric_infos.assert_awaited_once()


async def test_build_with_empty_snapshot_clears_all_stores(service_factory, tmp_path):
    from omegaconf import OmegaConf

    service, dependencies = service_factory()
    config_path = tmp_path / "meta.yaml"
    OmegaConf.save({"tables": [], "metrics": []}, config_path)

    await service.build(config_path)

    dependencies.column.sync.assert_awaited_once_with([], [], [])
    dependencies.value.sync.assert_awaited_once_with([])
    dependencies.metric.sync.assert_awaited_once_with([], [], [])
    dependencies.meta.sync_table_infos.assert_awaited_once_with([], [])
    dependencies.meta.sync_metric_infos.assert_awaited_once_with([], [])
