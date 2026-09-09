"""字段召回占位节点"""

from app.agent.state import QueryState


async def recall_column(_: QueryState) -> QueryState:
    """返回空字段列表，后续接入 Qdrant 召回"""
    return {"recalled_columns": []}
