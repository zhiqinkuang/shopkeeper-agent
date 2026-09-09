"""指标召回占位节点"""

from app.agent.state import QueryState


async def recall_metric(_: QueryState) -> QueryState:
    """返回空指标列表，后续接入 Qdrant 召回"""
    return {"recalled_metrics": []}
