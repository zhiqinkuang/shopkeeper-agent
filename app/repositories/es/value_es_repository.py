"""
字段取值 ES 仓储

把字段真实取值组织成 Elasticsearch 全文索引，并提供索引创建 批量写入和关键词检索能力

Service 层负责决定哪些字段需要同步
Repository 只关心索引是否存在 ValueInfo 如何写进 ES 以及如何按关键词召回
"""

import uuid
from dataclasses import asdict

from elasticsearch import AsyncElasticsearch

from app.conf.app_config import app_config
from app.entities.value_info import ValueInfo


class ValueESRepository:
    """负责字段取值全文索引的创建 写入和基础检索"""

    index_name = app_config.es.index_name
    # value 字段使用 IK 分词，这样地区 会员等级 品类等中文值才能按全文方式检索
    index_mappings = {
        "dynamic": False,
        "properties": {
            "id": {"type": "keyword"},
            "value": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_max_word",
            },
            "column_id": {"type": "keyword"},
            "build_id": {"type": "keyword"},
        },
    }

    def __init__(
        self,
        client: AsyncElasticsearch,
        index_name: str | None = None,
    ):
        self.client = client
        self.index_name = index_name or type(self).index_name

    async def ensure_index(self):
        """确保字段取值索引存在，并校验现有映射"""
        if not await self.client.indices.exists(index=self.index_name):
            await self.client.indices.create(
                index=self.index_name, mappings=self.index_mappings
            )
            return

        mapping_response = await self.client.indices.get_mapping(index=self.index_name)
        actual_mapping = mapping_response[self.index_name]["mappings"]
        if actual_mapping.get("dynamic") not in (False, "false"):
            raise ValueError("字段取值索引必须关闭动态映射")

        actual_properties = actual_mapping.get("properties", {})
        if "build_id" not in actual_properties:
            await self.client.indices.put_mapping(
                index=self.index_name,
                properties={"build_id": self.index_mappings["properties"]["build_id"]},
            )
            actual_properties["build_id"] = self.index_mappings["properties"][
                "build_id"
            ]

        for field_name, expected_mapping in self.index_mappings["properties"].items():
            actual_field_mapping = actual_properties.get(field_name)
            if actual_field_mapping is None:
                raise ValueError(f"字段取值索引缺少映射字段: {field_name}")
            for key, expected_value in expected_mapping.items():
                actual_value = actual_field_mapping.get(key)
                if key == "search_analyzer" and actual_value is None:
                    actual_value = actual_field_mapping.get("analyzer")
                if actual_value != expected_value:
                    raise ValueError(
                        f"字段取值索引映射不匹配: {field_name}.{key} "
                        f"期望 {expected_value}, 实际 {actual_value}"
                    )

    async def sync(self, value_infos: list[ValueInfo], batch_size: int = 20):
        """写入当前字段取值，并删除本次构建中已经不存在的文档"""
        build_id = str(uuid.uuid4())
        for i in range(0, len(value_infos), batch_size):
            batch_value_infos = value_infos[i : i + batch_size]
            batch_operations = []
            for value_info in batch_value_infos:
                # 用 ValueInfo.id 作为文档 id，这样重复构建时会覆盖同一条值记录
                batch_operations.append(
                    {"index": {"_index": self.index_name, "_id": value_info.id}}
                )
                document = asdict(value_info)
                document["build_id"] = build_id
                batch_operations.append(document)
            response = await self.client.bulk(operations=batch_operations)
            if response.get("errors"):
                failures = [
                    item["index"]
                    for item in response["items"]
                    if item["index"].get("error")
                ]
                raise RuntimeError(f"字段取值批量写入失败: {failures}")

        if value_infos:
            await self.client.indices.refresh(index=self.index_name)
            stale_query = {"bool": {"must_not": [{"term": {"build_id": build_id}}]}}
        else:
            stale_query = {"match_all": {}}

        delete_response = await self.client.delete_by_query(
            index=self.index_name,
            query=stale_query,
            refresh=True,
        )
        if (
            delete_response.get("timed_out")
            or delete_response.get("version_conflicts")
            or delete_response.get("failures")
        ):
            raise RuntimeError(
                "陈旧字段取值删除失败: "
                f"timed_out={delete_response.get('timed_out')}, "
                f"version_conflicts={delete_response.get('version_conflicts')}, "
                f"failures={delete_response.get('failures')}"
            )

    async def search(
        self, keyword: str, score_threshold: float = 0.6, limit: int = 20
    ) -> list[ValueInfo]:
        """按关键词全文检索字段取值，并还原为 ValueInfo 实体"""

        resp = await self.client.search(
            index=self.index_name,
            # value 字段启用了 IK 分词，match 查询可以处理中文短语和枚举值匹配
            query={"match": {"value": keyword}},
            size=limit,
            # 过滤掉相关度过低的命中，避免把明显无关的取值带入后续上下文
            min_score=score_threshold,
        )
        # ES 文档 _source 中保存的是 ValueInfo 的字段结构，业务层继续使用实体对象
        return [
            ValueInfo(
                id=hit["_source"]["id"],
                value=hit["_source"]["value"],
                column_id=hit["_source"]["column_id"],
            )
            for hit in resp["hits"]["hits"]
        ]
