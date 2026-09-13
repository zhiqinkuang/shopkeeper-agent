import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from omegaconf import OmegaConf
from omegaconf.errors import MissingMandatoryValue
from sqlalchemy import text

from app.clients.es_client_manager import ESClientManager
from app.clients.mysql_client_manager import MySQLClientManager
from app.clients.qdrant_client_manager import QdrantClientManager
from app.conf.app_config import DBConfig, ESConfig, QdrantConfig
from app.scripts import build_meta_knowledge
from tests.conftest import FakeEmbeddings

pytestmark = pytest.mark.integration


async def metadata_counts(repositories):
    session = repositories["meta"].session
    mysql = {}
    for table_name in ("table_info", "column_info", "metric_info", "column_metric"):
        mysql[table_name] = await session.scalar(
            text(f"SELECT COUNT(*) FROM {table_name}")
        )
    return {
        "mysql": mysql,
        "columns": (
            await repositories["column"].client.count(
                repositories["column"].collection_name,
                exact=True,
            )
        ).count,
        "metrics": (
            await repositories["metric"].client.count(
                repositories["metric"].collection_name,
                exact=True,
            )
        ).count,
        "values": (
            await repositories["value"].client.count(
                index=repositories["value"].index_name
            )
        )["count"],
    }


async def test_full_build_is_idempotent_and_removes_stale_data(
    integration_service,
    integration_repositories,
    minimal_config,
    tmp_path,
):
    config_path = tmp_path / "meta.yaml"
    OmegaConf.save(OmegaConf.structured(minimal_config), config_path)

    await integration_service.build(config_path)
    first = await metadata_counts(integration_repositories)
    await integration_service.build(config_path)
    second = await metadata_counts(integration_repositories)

    assert first == second
    assert second == {
        "mysql": {
            "table_info": 1,
            "column_info": 1,
            "metric_info": 1,
            "column_metric": 1,
        },
        "columns": 4,
        "metrics": 3,
        "values": 6,
    }

    reduced = copy.deepcopy(minimal_config)
    reduced.tables[0].columns[0].alias = ["省份"]
    reduced.tables[0].columns[0].sync = False
    reduced.metrics = []
    OmegaConf.save(OmegaConf.structured(reduced), config_path)
    await integration_service.build(config_path)

    assert await metadata_counts(integration_repositories) == {
        "mysql": {
            "table_info": 1,
            "column_info": 1,
            "metric_info": 0,
            "column_metric": 0,
        },
        "columns": 3,
        "metrics": 0,
        "values": 0,
    }

    OmegaConf.save({"tables": [], "metrics": []}, config_path)
    await integration_service.build(config_path)
    assert await metadata_counts(integration_repositories) == {
        "mysql": {
            "table_info": 0,
            "column_info": 0,
            "metric_info": 0,
            "column_metric": 0,
        },
        "columns": 0,
        "metrics": 0,
        "values": 0,
    }


async def test_missing_snapshot_section_is_rejected(
    integration_service,
    integration_repositories,
    tmp_path,
):
    config_path = tmp_path / "meta.yaml"
    OmegaConf.save({"tables": []}, config_path)

    with pytest.raises(MissingMandatoryValue, match="metrics"):
        await integration_service.build(config_path)

    session = integration_repositories["meta"].session
    assert await session.scalar(text("SELECT COUNT(*) FROM table_info")) == 0


async def test_invalid_config_fails_before_index_writes(
    integration_service,
    integration_repositories,
    minimal_config,
    tmp_path,
):
    invalid = copy.deepcopy(minimal_config)
    invalid.metrics[0].relevant_columns = ["dim_region.missing"]
    config_path = tmp_path / "invalid.yaml"
    OmegaConf.save(OmegaConf.structured(invalid), config_path)

    with pytest.raises(ValueError, match="引用了未配置字段"):
        await integration_service.build(config_path)

    session = integration_repositories["meta"].session
    assert await session.scalar(text("SELECT COUNT(*) FROM table_info")) == 0
    assert not await integration_repositories["column"].client.collection_exists(
        integration_repositories["column"].collection_name
    )


async def test_build_entry_wires_real_isolated_clients(
    integration_repositories,
    minimal_config,
    tmp_path,
    mocker,
):
    config_path = tmp_path / "entry-meta.yaml"
    OmegaConf.save(OmegaConf.structured(minimal_config), config_path)
    meta_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "meta")
    )
    dw_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "dw")
    )
    qdrant_manager = QdrantClientManager(
        QdrantConfig("127.0.0.1", 16333, 1024),
        check_compatibility=False,
    )
    es_manager = ESClientManager(ESConfig("127.0.0.1", 19200, "unused"))
    embedding_manager = SimpleNamespace(
        client=None,
        http_client=None,
        http_async_client=None,
        init=lambda: setattr(embedding_manager, "client", FakeEmbeddings()),
        close=AsyncMock(),
    )

    mocker.patch.object(build_meta_knowledge, "meta_mysql_client_manager", meta_manager)
    mocker.patch.object(build_meta_knowledge, "dw_mysql_client_manager", dw_manager)
    mocker.patch.object(build_meta_knowledge, "qdrant_client_manager", qdrant_manager)
    mocker.patch.object(build_meta_knowledge, "es_client_manager", es_manager)
    mocker.patch.object(
        build_meta_knowledge, "embedding_client_manager", embedding_manager
    )
    mocker.patch.object(
        build_meta_knowledge.ValueESRepository,
        "index_name",
        integration_repositories["value"].index_name,
    )
    mocker.patch.object(
        build_meta_knowledge.ColumnQdrantRepository,
        "collection_name",
        integration_repositories["column"].collection_name,
    )
    mocker.patch.object(
        build_meta_knowledge.MetricQdrantRepository,
        "collection_name",
        integration_repositories["metric"].collection_name,
    )

    await build_meta_knowledge.build(config_path)

    assert await metadata_counts(integration_repositories) == {
        "mysql": {
            "table_info": 1,
            "column_info": 1,
            "metric_info": 1,
            "column_metric": 1,
        },
        "columns": 4,
        "metrics": 3,
        "values": 6,
    }
    embedding_manager.close.assert_awaited_once()
