import math
import os

import pytest

from app.clients.embedding_client_manager import EmbeddingClientManager
from app.conf.app_config import EmbeddingConfig

pytestmark = pytest.mark.external


async def test_real_embedding_returns_expected_vector():
    if os.getenv("RUN_REAL_EMBEDDING") != "1":
        pytest.skip("仅在显式启用真实 Embedding 测试时执行")

    api_key = os.environ["EMBEDDING_API_KEY"]
    manager = EmbeddingClientManager(
        EmbeddingConfig(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="text-embedding-v4",
            api_key=api_key,
        )
    )
    manager.init()
    try:
        vector = await manager.client.aembed_query("元数据知识库测试")
    finally:
        await manager.close()

    assert len(vector) == 1024
    assert all(math.isfinite(value) for value in vector)
