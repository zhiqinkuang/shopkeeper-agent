"""SQL 生成占位节点"""

from app.agent.state import QueryState


async def generate_sql(_: QueryState) -> QueryState:
    """返回不会访问业务表的安全占位 SQL"""
    return {
        "sql": "SELECT 1 AS placeholder",
        "sql_valid": False,
        "validation_error": None,
        "correction_attempts": 0,
    }
