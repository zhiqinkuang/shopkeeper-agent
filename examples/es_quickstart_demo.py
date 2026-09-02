import asyncio

from elasticsearch import AsyncElasticsearch

ES_URL = "http://localhost:9200"
INDEX_NAME = "es_quickstart_demo"


async def recreate_index(client: AsyncElasticsearch):
    """为了让示例可重复运行，先删除旧索引，再重新创建"""
    if await client.indices.exists(index=INDEX_NAME):
        await client.indices.delete(index=INDEX_NAME)

    # 显式定义 mapping，关闭动态映射，便于理解字段类型
    await client.indices.create(
        index=INDEX_NAME,
        mappings={
            "dynamic": False,
            "properties": {
                "name": {"type": "text"},
                "category": {"type": "keyword"},
                "description": {"type": "text"},
            },
        },
    )
    print(f"1. 已创建索引：{INDEX_NAME}")


async def add_documents(client: AsyncElasticsearch):
    """
    写入几条示例文档

    bulk 采用“操作说明 + 文档内容”交替出现的格式：
    先写 index 动作，再写对应的文档 body
    """
    await client.bulk(
        operations=[
            {"index": {"_index": INDEX_NAME, "_id": "1"}},
            {
                "name": "订单分析",
                "category": "report",
                "description": "统计订单数量与成交金额",
            },
            {"index": {"_index": INDEX_NAME, "_id": "2"}},
            {
                "name": "销量趋势",
                "category": "metric",
                "description": "按月份查看商品销量变化",
            },
            {"index": {"_index": INDEX_NAME, "_id": "3"}},
            {
                "name": "区域销售额",
                "category": "dimension",
                "description": "按省份汇总销售额",
            },
        ],
        refresh=True,
    )
    print("2. 已写入 3 条文档。")


async def run_query(client: AsyncElasticsearch):
    """
    执行一次全文检索

    match 会对 text 字段做分词匹配，
    适合验证 Elasticsearch 的关键词检索能力
    """
    keyword = "销售"
    resp = await client.search(
        index=INDEX_NAME,
        query={"match": {"description": keyword}},
    )

    hits = resp["hits"]["hits"]
    print(f"3. 查询关键词：{keyword}")
    print(f"4. 命中数量：{resp['hits']['total']['value']}")
    print("5. 查询结果：")
    for i, hit in enumerate(hits, start=1):
        source = hit["_source"]
        print(
            f"   {i}) id={hit['_id']}, score={hit['_score']:.4f}, "
            f"name={source['name']}, category={source['category']}"
        )


async def main():
    # 直接初始化客户端，方便单独学习 Elasticsearch 的基本用法
    client = AsyncElasticsearch(hosts=[ES_URL])

    try:
        # 先确认服务可用，避免容器未启动时错误信息不清晰
        info = await client.info()
        print(f"0. Elasticsearch 已连接，版本：{info['version']['number']}")

        await recreate_index(client)
        await add_documents(client)
        await run_query(client)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
