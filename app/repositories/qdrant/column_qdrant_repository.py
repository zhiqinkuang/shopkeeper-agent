"""
字段向量仓储

管理字段向量集合并把已经准备好的 point 批量写入 Qdrant

Service 层负责决定一个字段要拆成哪些 point
Repository 只关心集合存在和向量点如何稳定落库
"""

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import PointStruct
from qdrant_client.models import Distance, UpdateStatus, VectorParams

from app.conf.app_config import app_config
from app.entities.column_info import ColumnInfo


class ColumnQdrantRepository:
    """负责字段向量集合的创建 写入和基础检索"""

    collection_name = "column_info_collection"

    def __init__(
        self,
        client: AsyncQdrantClient,
        collection_name: str | None = None,
    ):
        self.client = client
        self.collection_name = collection_name or type(self).collection_name

    async def ensure_collection(self):
        """确保字段向量集合存在，并校验现有集合配置"""
        expected_size = app_config.qdrant.embedding_size
        expected_distance = Distance.COSINE

        if not await self.client.collection_exists(self.collection_name):
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=expected_size,
                    distance=expected_distance,
                ),
            )
            return

        collection = await self.client.get_collection(self.collection_name)
        vectors_config = collection.config.params.vectors
        if not isinstance(vectors_config, VectorParams):
            raise ValueError("字段向量集合必须使用单向量配置")
        if (
            vectors_config.size != expected_size
            or vectors_config.distance != expected_distance
        ):
            raise ValueError(
                "字段向量集合配置不匹配: "
                f"期望 size={expected_size}, distance={expected_distance}; "
                f"实际 size={vectors_config.size}, distance={vectors_config.distance}"
            )

    async def sync(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        payloads: list[dict],
        batch_size: int = 10,
    ):
        """写入当前字段向量点，并删除本次构建中已经不存在的 point"""
        if not (len(ids) == len(embeddings) == len(payloads)):
            raise ValueError("字段向量的 id、embedding 和 payload 数量必须一致")

        points: list[PointStruct] = [
            PointStruct(id=id, vector=embedding, payload=payload)
            for id, embedding, payload in zip(ids, embeddings, payloads)
        ]
        for i in range(0, len(points), batch_size):
            result = await self.client.upsert(
                collection_name=self.collection_name, points=points[i : i + batch_size]
            )
            if result.status != UpdateStatus.COMPLETED:
                raise RuntimeError(f"字段向量写入未完成: {result.status}")

        expected_ids = set(ids)
        stale_ids: list[int | str] = []
        offset = None
        while True:
            records, offset = await self.client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            stale_ids.extend(
                record.id for record in records if str(record.id) not in expected_ids
            )
            if offset is None:
                break

        for i in range(0, len(stale_ids), batch_size):
            result = await self.client.delete(
                collection_name=self.collection_name,
                points_selector=stale_ids[i : i + batch_size],
            )
            if result.status != UpdateStatus.COMPLETED:
                raise RuntimeError(f"陈旧字段向量删除未完成: {result.status}")

    async def search(
        self, embedding: list[float], score_threshold: float = 0.6, limit: int = 20
    ) -> list[ColumnInfo]:
        """按向量相似度检索字段元数据，并还原为 ColumnInfo 实体"""
        result = await self.client.query_points(
            collection_name=self.collection_name,
            query=embedding,
            limit=limit,
            score_threshold=score_threshold,
        )
        # Qdrant 只保存字段元数据 payload，业务层继续使用 ColumnInfo
        return [ColumnInfo(**point.payload) for point in result.points]
