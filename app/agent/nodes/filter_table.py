"""表信息过滤占位节点"""

from app.agent.state import QueryState


async def filter_table(_: QueryState) -> QueryState:
    """返回空表列表，后续接入表结构筛选"""
    return {"selected_tables": []}
