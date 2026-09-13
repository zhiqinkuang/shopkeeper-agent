import os

import pytest

from app.conf.app_config import app_config
from app.scripts.eval_query_scenarios import (
    AGENT_SAMPLE_IDS,
    eval_agent,
    select_scenarios,
)
from tests.external.test_real_llm_e2e import (
    _assert_knowledge_ready,
    _real_agent_context,
)

pytestmark = pytest.mark.external


def _require_real_llm() -> None:
    if os.getenv("RUN_REAL_LLM") != "1":
        pytest.skip("仅在显式启用真实 LLM 测试时执行")
    if not app_config.llm.api_key:
        pytest.skip("缺少 LLM_API_KEY")
    if not app_config.embedding.api_key:
        pytest.skip("缺少 EMBEDDING_API_KEY")


async def test_agent_sample_matches_gold_results():
    _require_real_llm()

    async with _real_agent_context() as context:
        await _assert_knowledge_ready(context)

    results = await eval_agent(select_scenarios(AGENT_SAMPLE_IDS))
    failed = [
        {
            "id": item["id"],
            "question": item["question"],
            "error": item["error"],
            "gold_sample": item["gold_sample"],
            "agent_sample": item["agent_sample"],
            "sql": item["sql"],
        }
        for item in results
        if not item["passed"]
    ]

    assert not failed, failed
