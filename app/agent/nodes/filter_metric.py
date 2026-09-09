"""指标信息过滤占位节点"""

from app.agent.state import QueryState


async def filter_metric(state: QueryState) -> QueryState:
    """暂时保留全部召回指标"""
    return {"selected_metrics": state.get("recalled_metrics", [])}
