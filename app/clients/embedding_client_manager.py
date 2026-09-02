import asyncio
from typing import Optional

from langchain_openai import OpenAIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        # 客户端在模块导入阶段先不立即创建，避免启动时就发起外部依赖连接
        self.client: Optional[OpenAIEmbeddings] = None
        # 保存 Embedding 服务配置，供 init() 时组装服务访问地址使用
        self.config = config

    def init(self):
        # 百炼兼容 OpenAI Embedding 协议，连接参数统一从应用配置读取
        self.client = OpenAIEmbeddings(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            dimensions=app_config.qdrant.embedding_size,
            # text-embedding-v4 单次最多处理 10 条文本
            chunk_size=10,
            check_embedding_ctx_length=False,
        )


# 模块级单例，供其他模块按需复用同一个客户端管理器
embedding_client_manager = EmbeddingClientManager(app_config.embedding)


if __name__ == "__main__":
    # 本地调试入口：初始化客户端后执行一次最小化向量化调用
    embedding_client_manager.init()
    client = embedding_client_manager.client

    async def test():
        # 使用示例文本验证 Embedding 服务是否可正常响应
        text = "What is deep learning?"
        query_result = await client.aembed_query(text)
        # 只打印前 3 个维度，便于快速确认返回结果结构正确
        print(query_result[:3])

    # 运行调试测试
    asyncio.run(test())
