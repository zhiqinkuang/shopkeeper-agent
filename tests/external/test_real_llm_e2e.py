import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from elasticsearch import AsyncElasticsearch
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text

from app.agent.context import DataAgentContext
from app.agent.graph import query_graph
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import EmbeddingClientManager
from app.clients.mysql_client_manager import MySQLClientManager
from app.conf.app_config import DBConfig, app_config
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository

pytestmark = pytest.mark.external

QUESTION = "统计华北地区的销售总额"
EXPECTED_PROGRESS = {
    "抽取关键词",
    "召回字段信息",
    "召回指标信息",
    "召回字段取值",
    "合并召回信息",
    "过滤表信息",
    "过滤指标信息",
    "添加额外上下文",
}


def _require_real_llm() -> None:
    if os.getenv("RUN_REAL_LLM") != "1":
        pytest.skip("仅在显式启用真实 LLM 测试时执行")
    if not app_config.llm.api_key:
        pytest.skip("缺少 LLM_API_KEY")
    if not app_config.embedding.api_key:
        pytest.skip("缺少 EMBEDDING_API_KEY")


@asynccontextmanager
async def _real_agent_context() -> AsyncIterator[DataAgentContext]:
    """连接隔离测试基础设施，并使用与线上一致的集合名。"""
    meta_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "meta")
    )
    dw_manager = MySQLClientManager(
        DBConfig("127.0.0.1", 13307, "didilili", "test-password", "dw")
    )
    embedding_manager = EmbeddingClientManager(app_config.embedding)
    qdrant_client = AsyncQdrantClient(
        url="http://127.0.0.1:16333",
        trust_env=False,
        check_compatibility=False,
    )
    es_client = AsyncElasticsearch("http://127.0.0.1:19200")
    meta_manager.init()
    dw_manager.init()
    embedding_manager.init()
    try:
        async with (
            meta_manager.session_factory() as meta_session,
            dw_manager.session_factory() as dw_session,
        ):
            yield DataAgentContext(
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client),
                embedding_client=embedding_manager.client,
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client),
                value_es_repository=ValueESRepository(es_client),
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=DWMySQLRepository(dw_session),
            )
    finally:
        await embedding_manager.close()
        await qdrant_client.close()
        await es_client.close()
        await meta_manager.close()
        await dw_manager.close()


async def _assert_knowledge_ready(context: DataAgentContext) -> None:
    table_count = await context.meta_mysql_repository.session.scalar(
        text("SELECT COUNT(*) FROM table_info")
    )
    if table_count < 5:
        pytest.fail(
            "测试环境尚未构建完整元数据知识库，"
            "请先对隔离 Docker 执行 build_meta_knowledge"
        )
    if not await context.column_qdrant_repository.client.collection_exists(
        ColumnQdrantRepository.collection_name
    ):
        pytest.fail("Qdrant 缺少 column_info_collection，请先构建元数据知识库")
    if not await context.metric_qdrant_repository.client.collection_exists(
        MetricQdrantRepository.collection_name
    ):
        pytest.fail("Qdrant 缺少 metric_info_collection，请先构建元数据知识库")


async def test_real_llm_query_graph_end_to_end():
    _require_real_llm()

    async with _real_agent_context() as context:
        await _assert_knowledge_ready(context)

        progress: list[str] = []
        merged: DataAgentState = {"query": QUESTION}
        async for mode, chunk in query_graph.astream(
            {"query": QUESTION},
            context=context,
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom":
                if isinstance(chunk, dict) and chunk.get("type") == "progress":
                    progress.append(chunk["step"])
                continue
            for node_update in chunk.values():
                if isinstance(node_update, dict):
                    merged.update(node_update)

        assert EXPECTED_PROGRESS <= set(progress)
        assert {"生成SQL", "校验SQL", "执行SQL"} <= set(progress)

        keywords = merged.get("keywords") or []
        assert QUESTION in keywords
        assert any("华北" in keyword or "销售" in keyword for keyword in keywords)

        table_names = {table["name"] for table in merged.get("table_infos") or []}
        assert "dim_region" in table_names
        assert "fact_order" in table_names

        metric_names = {metric["name"] for metric in merged.get("metric_infos") or []}
        assert "GMV" in metric_names

        assert merged.get("date_info", {}).get("date")
        assert merged.get("db_info", {}).get("dialect") == "mysql"
        sql = merged.get("sql") or ""
        assert "SELECT" in sql.upper()
        assert "placeholder" not in sql.lower()
        assert "fact_order" in sql
        result = merged.get("execution_result") or []
        assert result
        assert any(
            isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit()
            for row in result
            for value in row.values()
        )
        assert merged.get("error") is None
