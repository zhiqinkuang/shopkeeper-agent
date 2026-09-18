"""问数智能体统一使用的大模型客户端"""

from langchain.chat_models import init_chat_model

from app.conf.app_config import app_config

# 召回扩展和 SQL 生成更看重结果稳定性，因此关闭随机发散
llm = init_chat_model(
    model=app_config.llm.model_name,
    model_provider="openai",
    base_url=app_config.llm.base_url,
    api_key=app_config.llm.api_key,
    temperature=0,
)


if __name__ == "__main__":
    print(llm.invoke("你好").content)
