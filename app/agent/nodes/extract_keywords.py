"""关键词抽取占位节点"""

from app.agent.state import QueryState


async def extract_keywords(state: QueryState) -> QueryState:
    """暂时把完整问题作为唯一关键词"""
    return {"keywords": [state["question"]]}
