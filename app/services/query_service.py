"""查询接口业务服务，负责执行一次问数工作流"""

import json

from langchain_core.embeddings import Embeddings

from app.agent.context import DataAgentContext
from app.agent.graph import query_graph
from app.agent.state import DataAgentState
from app.core.context import request_id_ctx_var
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: Embeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
    ):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository

    async def query(self, query: str):
        """执行问数工作流，并把进度或异常包装成 SSE 消息"""
        state = DataAgentState(query=query)
        context = DataAgentContext(
            column_qdrant_repository=self.column_qdrant_repository,
            embedding_client=self.embedding_client,
            metric_qdrant_repository=self.metric_qdrant_repository,
            value_es_repository=self.value_es_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )
        merged = {"query": query}
        error_message = None

        try:
            async for item in query_graph.astream(
                input=state,
                context=context,
                stream_mode=["updates", "custom"],
            ):
                mode, chunk = item
                if mode == "updates" and isinstance(chunk, dict):
                    for node_update in chunk.values():
                        if isinstance(node_update, dict):
                            merged.update(node_update)
                    continue
                if mode == "custom":
                    yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as error:
            # 流式响应开始后不能再改 HTTP 状态码，异常改为 SSE 错误消息
            logger.exception("问数工作流执行失败")
            error_message = str(error)
            payload = {"type": "error", "message": error_message}
            yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
        finally:
            await self._persist_audit(query, merged, error_message)

    async def _persist_audit(
        self, query: str, merged: dict, error_message: str | None
    ) -> None:
        """把本次问答的 SQL 和结果写入审计表，失败不影响用户响应。"""
        save = getattr(self.meta_mysql_repository, "save_query_audit", None)
        if save is None:
            return
        try:
            await save(
                request_id=request_id_ctx_var.get(),
                query=query,
                sql_text=merged.get("sql"),
                execution_result=merged.get("execution_result"),
                answer=merged.get("answer"),
                error=error_message or merged.get("error"),
            )
        except Exception:
            logger.exception("写入查询审计失败")
