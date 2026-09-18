"""问数智能体骨架 CLI 入口"""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack

from app.agent.context import DataAgentContext
from app.agent.graph import query_graph
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


async def run(
    question: str,
    max_correction_attempts: int,
    simulated_validation_failures: int,
) -> bool:
    """运行工作流并逐节点输出状态增量"""
    async with AsyncExitStack() as exit_stack:
        qdrant_client_manager.init()
        exit_stack.push_async_callback(qdrant_client_manager.close)
        embedding_client_manager.init()
        exit_stack.push_async_callback(embedding_client_manager.close)
        es_client_manager.init()
        exit_stack.push_async_callback(es_client_manager.close)
        meta_mysql_client_manager.init()
        exit_stack.push_async_callback(meta_mysql_client_manager.close)
        dw_mysql_client_manager.init()
        exit_stack.push_async_callback(dw_mysql_client_manager.close)

        assert qdrant_client_manager.client is not None
        assert embedding_client_manager.client is not None
        assert es_client_manager.client is not None
        assert meta_mysql_client_manager.session_factory is not None
        assert dw_mysql_client_manager.session_factory is not None
        meta_session = await exit_stack.enter_async_context(
            meta_mysql_client_manager.session_factory()
        )
        dw_session = await exit_stack.enter_async_context(
            dw_mysql_client_manager.session_factory()
        )
        context = DataAgentContext(
            column_qdrant_repository=ColumnQdrantRepository(
                qdrant_client_manager.client
            ),
            embedding_client=embedding_client_manager.client,
            metric_qdrant_repository=MetricQdrantRepository(
                qdrant_client_manager.client
            ),
            value_es_repository=ValueESRepository(es_client_manager.client),
            meta_mysql_repository=MetaMySQLRepository(meta_session),
            dw_mysql_repository=DWMySQLRepository(dw_session),
            max_correction_attempts=max_correction_attempts,
            simulated_validation_failures=simulated_validation_failures,
        )

        execution_result = None
        last_error = None
        async for update in query_graph.astream(
            {"query": question},
            context=context,
            stream_mode="updates",
        ):
            print(json.dumps(update, ensure_ascii=False, default=str))
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                if "execution_result" in node_update:
                    execution_result = node_update["execution_result"]
                if "error" in node_update:
                    last_error = node_update["error"]
        return execution_result is not None and not last_error


def main() -> int:
    """解析命令行参数并返回进程退出码"""
    parser = argparse.ArgumentParser(description="运行问数智能体骨架")
    parser.add_argument("question", help="自然语言问题")
    parser.add_argument(
        "--max-correction-attempts",
        type=int,
        default=2,
        help="最大 SQL 纠错次数",
    )
    parser.add_argument(
        "--simulate-validation-failures",
        type=int,
        default=0,
        help="前 N 次 SQL 校验返回失败",
    )
    args = parser.parse_args()

    if args.max_correction_attempts < 0 or args.simulate_validation_failures < 0:
        parser.error("纠错次数和模拟失败次数不能小于 0")

    succeeded = asyncio.run(
        run(
            question=args.question,
            max_correction_attempts=args.max_correction_attempts,
            simulated_validation_failures=args.simulate_validation_failures,
        )
    )
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
