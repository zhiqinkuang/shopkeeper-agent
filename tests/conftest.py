from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.embeddings import Embeddings

from app.conf.meta_config import (
    ColumnConfig,
    MetaConfig,
    MetricConfig,
    TableConfig,
)
from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.services.meta_knowledge_service import MetaKnowledgeService


class FakeEmbeddings(Embeddings):
    """生成固定维度且可重复的测试向量"""

    def __init__(self, dimensions: int = 1024):
        self.dimensions = dimensions
        self.batches: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        seed = sum(ord(char) for char in text) % 97
        return [float((seed + index) % 97) / 97 for index in range(self.dimensions)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [self._vector(text) for text in texts]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


@pytest.fixture
def minimal_config() -> MetaConfig:
    return MetaConfig(
        tables=[
            TableConfig(
                name="dim_region",
                role="dim",
                description="地区维度表",
                columns=[
                    ColumnConfig(
                        name="province",
                        role="dimension",
                        description="省份名称",
                        alias=["省份", "所在省份"],
                        sync=True,
                    )
                ],
            )
        ],
        metrics=[
            MetricConfig(
                name="RegionCount",
                description="地区数量",
                relevant_columns=["dim_region.province"],
                alias=["地区数"],
                formula="COUNT(DISTINCT dim_region.province)",
            )
        ],
    )


@pytest.fixture
def column_info() -> ColumnInfo:
    return ColumnInfo(
        id="dim_region.province",
        name="province",
        type="varchar(50)",
        role="dimension",
        examples=["广东省"],
        description="省份名称",
        alias=["省份", "所在省份"],
        table_id="dim_region",
    )


@pytest.fixture
def metric_info() -> MetricInfo:
    return MetricInfo(
        id="RegionCount",
        name="RegionCount",
        description="地区数量",
        relevant_columns=["dim_region.province"],
        alias=["地区数"],
        formula="COUNT(DISTINCT dim_region.province)",
    )


@pytest.fixture
def service_factory():
    def create(embedding_client: Embeddings | None = None):
        meta_session = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        dw_session = SimpleNamespace(rollback=AsyncMock())
        meta_repository = SimpleNamespace(
            session=meta_session,
            ensure_schema=AsyncMock(),
            finalize_schema=AsyncMock(),
            get_column_ids=AsyncMock(return_value=set()),
            get_metric_column_ids=AsyncMock(return_value=set()),
            sync_table_infos=AsyncMock(),
            sync_metric_infos=AsyncMock(),
        )
        dw_repository = SimpleNamespace(
            session=dw_session,
            get_column_types=AsyncMock(return_value={"province": "varchar(50)"}),
            get_column_values=AsyncMock(return_value=["广东省", "浙江省"]),
        )
        column_repository = SimpleNamespace(
            ensure_collection=AsyncMock(),
            sync=AsyncMock(),
        )
        value_repository = SimpleNamespace(
            ensure_index=AsyncMock(),
            sync=AsyncMock(),
        )
        metric_repository = SimpleNamespace(
            ensure_collection=AsyncMock(),
            sync=AsyncMock(),
        )
        service = MetaKnowledgeService(
            meta_mysql_repository=meta_repository,
            dw_mysql_repository=dw_repository,
            column_qdrant_repository=column_repository,
            embedding_client=embedding_client or FakeEmbeddings(),
            value_es_repository=value_repository,
            metric_qdrant_repository=metric_repository,
        )
        return service, SimpleNamespace(
            meta=meta_repository,
            dw=dw_repository,
            column=column_repository,
            value=value_repository,
            metric=metric_repository,
        )

    return create
