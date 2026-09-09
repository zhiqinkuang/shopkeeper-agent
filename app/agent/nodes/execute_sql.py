"""SQL 执行占位节点"""

from app.agent.state import QueryState


async def execute_sql(_: QueryState) -> QueryState:
    """返回占位结果，不连接或查询真实数据库"""
    return {"execution_result": [{"placeholder": 1}], "error": None}
