"""字段值召回占位节点"""

from app.agent.state import QueryState


async def recall_value(_: QueryState) -> QueryState:
    """返回空字段值列表，后续接入 Elasticsearch 召回"""
    return {"recalled_values": []}
