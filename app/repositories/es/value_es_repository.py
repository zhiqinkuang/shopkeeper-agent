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
        """确保查询名称可作为别名，并校验当前物理索引映射"""
        if not await self.client.indices.exists_alias(name=self.index_name):
            if await self.client.indices.exists(index=self.index_name):
                raise ValueError(
                    f"字段取值查询别名与同名物理索引冲突: {self.index_name}"
                )
            return

        mapping_response = await self.client.indices.get_mapping(index=self.index_name)
        if len(mapping_response) != 1:
            raise ValueError("字段取值查询别名必须只指向一个物理索引")
        actual_mapping = next(iter(mapping_response.values()))["mappings"]
        if actual_mapping.get("dynamic") not in (False, "false"):
            raise ValueError("字段取值索引必须关闭动态映射")

        actual_properties = actual_mapping.get("properties", {})
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
        """构建新物理索引，校验完成后原子切换查询别名"""
        physical_index = f"{self.index_name}-{uuid.uuid4().hex}"
        alias_switched = False
        await self.client.indices.create(
            index=physical_index,
            mappings=self.index_mappings,
        )
        try:
            for i in range(0, len(value_infos), batch_size):
                batch_value_infos = value_infos[i : i + batch_size]
                batch_operations = []
                for value_info in batch_value_infos:
                    batch_operations.append(
                        {"index": {"_index": physical_index, "_id": value_info.id}}
                    )
                    batch_operations.append(asdict(value_info))
                response = await self.client.bulk(operations=batch_operations)
                if response.get("errors"):
                    failures = [
                        item["index"]
                        for item in response["items"]
                        if item["index"].get("error")
                    ]
                    raise RuntimeError(f"字段取值批量写入失败: {failures}")

            await self.client.indices.refresh(index=physical_index)
            actual_count = (await self.client.count(index=physical_index))["count"]
            if actual_count != len(value_infos):
                raise RuntimeError(
                    "字段取值写入数量不匹配: "
                    f"期望 {len(value_infos)}, 实际 {actual_count}"
                )

            old_indexes: list[str] = []
            if await self.client.indices.exists_alias(name=self.index_name):
                old_indexes = list(
                    (await self.client.indices.get_alias(name=self.index_name)).keys()
                )
            alias_actions = [
                {
                    "remove": {
                        "index": old_index,
                        "alias": self.index_name,
                    }
                }
                for old_index in old_indexes
            ]
            alias_actions.append(
                {
                    "add": {
                        "index": physical_index,
                        "alias": self.index_name,
                    }
                }
            )
            await self.client.indices.update_aliases(actions=alias_actions)
            alias_switched = True

            all_physical_indexes = list(
                (
                    await self.client.indices.get(
                        index=f"{self.index_name}-*",
                        allow_no_indices=True,
                        ignore_unavailable=True,
                    )
                ).keys()
            )
            stale_indexes = [
                index_name
                for index_name in all_physical_indexes
                if index_name != physical_index
            ]
            if stale_indexes:
                await self.client.indices.delete(index=stale_indexes)
        except Exception:
            if (
                not alias_switched
                and await self.client.indices.exists(index=physical_index)
            ):
                await self.client.indices.delete(index=physical_index)
            raise

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
