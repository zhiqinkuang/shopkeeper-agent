"""从用户问题中抽取召回关键词"""

import jieba.analyse
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.nodes.progress import progress_event
from app.agent.state import DataAgentState
from app.core.log import logger


async def extract_keywords(
    state: DataAgentState, runtime: Runtime[DataAgentContext]
) -> DataAgentState:
    """使用 TF-IDF 提取有业务含义的关键词"""
    step = "抽取关键词"
    writer = runtime.stream_writer
    writer(progress_event(step, "running"))

    try:
        query = state["query"]

        # 只保留更可能承载业务含义的词性，减少助词和口语表达带来的检索噪声
        allow_pos = (
            "n",
            "nr",
            "ns",
            "nt",
            "nz",
            "v",
            "vn",
            "a",
            "an",
            "eng",
            "i",
            "l",
        )
        keywords = jieba.analyse.extract_tags(query, allowPOS=allow_pos)
        keywords = list(set([*keywords, query]))

        writer(progress_event(step, "success"))
        logger.info(f"抽取关键词成功：{keywords}")
        return {"keywords": keywords}
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer(progress_event(step, "error"))
        raise
