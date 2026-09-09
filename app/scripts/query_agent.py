"""问数智能体骨架 CLI 入口"""

import argparse
import asyncio
import json
from dataclasses import asdict

from app.agent.context import QueryContext
from app.agent.graph import query_graph


async def run(
    question: str,
    max_correction_attempts: int,
    simulated_validation_failures: int,
) -> bool:
    """运行工作流并逐节点输出状态增量"""
    context = QueryContext(
        max_correction_attempts=max_correction_attempts,
        simulated_validation_failures=simulated_validation_failures,
    )
    succeeded = True
    async for update in query_graph.astream(
        {"question": question},
        context=asdict(context),
        stream_mode="updates",
    ):
        print(json.dumps(update, ensure_ascii=False, default=str))
        if any(
            isinstance(node_update, dict) and node_update.get("error")
            for node_update in update.values()
        ):
            succeeded = False
    return succeeded


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
