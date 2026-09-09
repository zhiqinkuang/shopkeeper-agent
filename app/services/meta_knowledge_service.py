"""
元数据知识构建服务

负责组织元数据知识库构建的核心业务流程，位于脚本入口和仓储层之间
一方面接收配置文件，另一方面协调元数据库和数仓查询仓储

当前这条主线已经覆盖表字段入库 字段向量索引 字段取值全文索引
以及指标入库和指标向量索引构建逻辑
"""

import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_core.embeddings import Embeddings
from omegaconf import OmegaConf

from app.conf.meta_config import MetaConfig
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    """负责串联元数据知识库构建流程的应用服务"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        embedding_client: Embeddings,
        value_es_repository: ValueESRepository,
        metric_qdrant_repository: MetricQdrantRepository,
    ):
        # meta repository 负责结构化元数据的落库
        self.meta_mysql_repository: MetaMySQLRepository = meta_mysql_repository
        # dw repository 负责到教学数仓中读取真实表结构和示例值
        self.dw_mysql_repository: DWMySQLRepository = dw_mysql_repository
        # 字段向量集合的创建和写入统一交给 Qdrant Repository
        self.column_qdrant_repository: ColumnQdrantRepository = column_qdrant_repository
        # 向量化动作放在 Service 层
        self.embedding_client: Embeddings = embedding_client
        # 字段值全文索引的写入统一交给 ES Repository
        self.value_es_repository: ValueESRepository = value_es_repository
        # 指标向量集合和字段向量集合分开管理，便于后续按对象类型独立召回
        self.metric_qdrant_repository: MetricQdrantRepository = metric_qdrant_repository

    @staticmethod
    def _validate_aliases(owner: str, aliases: list[str]):
        """校验名称和别名列表中的文本质量"""
        normalized_aliases = [alias.strip() for alias in aliases]
        if any(not alias for alias in normalized_aliases):
            raise ValueError(f"{owner} 的别名不能为空")
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError(f"{owner} 存在重复别名")

    @staticmethod
    def _validate_text(label: str, value: str):
        """校验参与存储或向量化的文本不为空"""
        if not value.strip():
            raise ValueError(f"{label}不能为空")

    @staticmethod
    def _validate_max_length(label: str, value: str, max_length: int):
        """校验文本不会超过结构化存储字段的长度"""
        if len(value) > max_length:
            raise ValueError(f"{label}长度不能超过 {max_length}，实际为 {len(value)}")

    async def _validate_meta_config(
        self, meta_config: MetaConfig
    ) -> dict[str, dict[str, str]]:
        """在写入任何存储前校验配置和数仓真实结构"""
        column_types_by_table: dict[str, dict[str, str]] = {}
        configured_column_ids: set[str] = set()

        if meta_config.tables is not None:
            table_names: set[str] = set()
            for table in meta_config.tables:
                self._validate_text("表名", table.name)
                self._validate_text(f"表 {table.name} 的描述", table.description)
                self._validate_max_length("表名", table.name, 64)
                if table.role not in {"fact", "dim"}:
                    raise ValueError(f"表 {table.name} 的角色无效: {table.role}")
                if table.name in table_names:
                    raise ValueError(f"存在重复表: {table.name}")
                table_names.add(table.name)

                column_types = await self.dw_mysql_repository.get_column_types(
                    table.name
                )
                if not column_types:
                    raise ValueError(f"数仓表不存在或没有字段: {table.name}")
                column_types_by_table[table.name] = column_types

                column_names: set[str] = set()
                for column in table.columns:
                    column_id = f"{table.name}.{column.name}"
                    self._validate_text(f"表 {table.name} 的字段名", column.name)
                    self._validate_text(f"字段 {column_id} 的描述", column.description)
                    self._validate_max_length(
                        f"字段 {column_id} 的名称", column.name, 64
                    )
                    self._validate_max_length("字段 ID", column_id, 64)
                    if column.role not in {
                        "primary_key",
                        "foreign_key",
                        "measure",
                        "dimension",
                    }:
                        raise ValueError(f"字段 {column_id} 的角色无效: {column.role}")
                    if column.name in column_names:
                        raise ValueError(f"存在重复字段: {column_id}")
                    if column.name not in column_types:
                        raise ValueError(f"数仓字段不存在: {column_id}")
                    self._validate_max_length(
                        f"字段 {column_id} 的类型", column_types[column.name], 64
                    )
                    column_names.add(column.name)
                    configured_column_ids.add(column_id)
                    self._validate_aliases(f"字段 {column_id}", column.alias)

        if meta_config.tables is None:
            available_column_ids = await self.meta_mysql_repository.get_column_ids()
        else:
            available_column_ids = configured_column_ids
            if meta_config.metrics is None:
                referenced_column_ids = (
                    await self.meta_mysql_repository.get_metric_column_ids()
                )
                removed_referenced_columns = (
                    referenced_column_ids - configured_column_ids
                )
                if removed_referenced_columns:
                    raise ValueError(
                        "删除指标依赖字段时必须同时提供 metrics 配置: "
                        f"{', '.join(sorted(removed_referenced_columns))}"
                    )

        if meta_config.metrics is not None:
            metric_names: set[str] = set()
            for metric in meta_config.metrics:
                self._validate_text("指标名", metric.name)
                self._validate_text(f"指标 {metric.name} 的描述", metric.description)
                self._validate_max_length("指标名", metric.name, 64)
                if metric.name in metric_names:
                    raise ValueError(f"存在重复指标: {metric.name}")
                self._validate_text(f"指标 {metric.name} 的计算公式", metric.formula)
                if not metric.relevant_columns:
                    raise ValueError(f"指标 {metric.name} 必须关联至少一个字段")

                unknown_columns = set(metric.relevant_columns) - available_column_ids
                if unknown_columns:
                    raise ValueError(
                        f"指标 {metric.name} 引用了未配置字段: "
                        f"{', '.join(sorted(unknown_columns))}"
                    )
                if len(metric.relevant_columns) != len(set(metric.relevant_columns)):
                    raise ValueError(f"指标 {metric.name} 存在重复关联字段")

                metric_names.add(metric.name)
                self._validate_aliases(f"指标 {metric.name}", metric.alias)

        return column_types_by_table

    async def _collect_table_infos(
        self,
        meta_config: MetaConfig,
        column_types_by_table: dict[str, dict[str, str]],
    ) -> tuple[list[TableInfo], list[ColumnInfo]]:
        """把配置和数仓信息整理成表字段业务实体"""
        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []

        for table in meta_config.tables or []:
            # 先把配置里的表定义整理成业务实体，后面统一交给 Meta Repository 落库
            table_info = TableInfo(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description,
            )
            table_infos.append(table_info)

            for column in table.columns:
                # 这里只拿少量示例值，目的是让字段元数据更容易被人和模型理解
                column_values = await self.dw_mysql_repository.get_column_values(
                    table.name, column.name
                )
                normalized_values = [
                    str(column_value) for column_value in column_values
                ]
                # 字段 id 使用 table.column 形式，后续在向量索引和全文索引里都会复用
                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types_by_table[table.name][column.name],
                    role=column.role,
                    examples=normalized_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name,
                )
                column_infos.append(column_info)

        return table_infos, column_infos

    async def _embed_texts(self, embedding_texts: list[str]) -> list[list[float]]:
        """分批生成向量，并保证输入和输出数量一致"""
        embeddings: list[list[float]] = []
        embedding_batch_size = 10
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            if len(batch_embeddings) != len(batch_embedding_texts):
                raise ValueError(
                    "Embedding 返回数量不匹配: "
                    f"输入 {len(batch_embedding_texts)}, "
                    f"输出 {len(batch_embeddings)}"
                )
            embeddings.extend(batch_embeddings)
        return embeddings

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfo]):
        """把字段元数据继续推进成可语义检索的 Qdrant 向量点"""
        await self.column_qdrant_repository.ensure_collection()

        points: list[dict] = []
        for column_info in column_infos:
            # 一个字段不会只生成一个向量点，而是把名字 描述 别名都拆开建立语义入口
            points.append(
                {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"column:{column_info.id}:name:{column_info.name}",
                        )
                    ),
                    "embedding_text": column_info.name,
                    "payload": asdict(column_info),
                }
            )

            points.append(
                {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"column:{column_info.id}:description:{column_info.description}",
                        )
                    ),
                    "embedding_text": column_info.description,
                    "payload": asdict(column_info),
                }
            )

            for alia in column_info.alias:
                points.append(
                    {
                        "id": str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"column:{column_info.id}:alias:{alia}",
                            )
                        ),
                        "embedding_text": alia,
                        "payload": asdict(column_info),
                    }
                )

        # 先把待向量化文本抽出来，再分批调用 Embedding 服务
        # 这样更容易控制单次请求大小
        embedding_texts = [point["embedding_text"] for point in points]
        embeddings = await self._embed_texts(embedding_texts)

        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        await self.column_qdrant_repository.sync(ids, embeddings, payloads)

    async def _save_value_info_to_es(
        self, meta_config: MetaConfig, column_infos: list[ColumnInfo]
    ):
        """把允许同步的字段真实取值写入 Elasticsearch 全文索引"""
        await self.value_es_repository.ensure_index()

        # 不是所有字段都要同步真实值，是否同步由配置里的 sync 显式控制
        column2sync: dict[str, bool] = {}
        for table in meta_config.tables or []:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        value_infos: list[ValueInfo] = []
        for column_info in column_infos:
            sync = column2sync[column_info.id]
            if sync:
                # 这里拿的是字段真实值全集，不再是第 8 章里的少量 examples
                current_column_values = (
                    await self.dw_mysql_repository.get_column_values(
                        column_info.table_id, column_info.name, 100001
                    )
                )
                if len(current_column_values) > 100000:
                    raise ValueError(
                        f"字段 {column_info.id} 的不同取值超过同步上限 100000"
                    )
                current_values_infos = []
                for current_column_value in current_column_values:
                    normalized_value = str(current_column_value)
                    current_values_infos.append(
                        ValueInfo(
                            id=str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_URL,
                                    f"value:{column_info.id}:{normalized_value}",
                                )
                            ),
                            value=normalized_value,
                            column_id=column_info.id,
                        )
                    )
                value_infos.extend(current_values_infos)

        await self.dw_mysql_repository.session.rollback()
        await self.value_es_repository.sync(value_infos)

    def _collect_metric_infos(
        self, meta_config: MetaConfig
    ) -> tuple[list[MetricInfo], list[ColumnMetric]]:
        """把配置整理成指标及字段依赖业务实体"""
        metric_infos: list[MetricInfo] = []
        column_metrics: list[ColumnMetric] = []

        for metric in meta_config.metrics or []:
            # MetricInfo 表达指标本身，当前直接用指标名作为稳定业务 id
            metric_info = MetricInfo(
                id=metric.name,
                name=metric.name,
                description=metric.description,
                relevant_columns=metric.relevant_columns,
                alias=metric.alias,
                formula=metric.formula,
            )
            metric_infos.append(metric_info)
            for column in metric.relevant_columns:
                # ColumnMetric 单独表达“某个指标依赖某个字段”这层关系
                column_metric = ColumnMetric(column_id=column, metric_id=metric.name)
                column_metrics.append(column_metric)

        return metric_infos, column_metrics

    async def _save_meta_to_db(
        self,
        meta_config: MetaConfig,
        table_infos: list[TableInfo],
        column_infos: list[ColumnInfo],
        metric_infos: list[MetricInfo],
        column_metrics: list[ColumnMetric],
    ):
        """在同一笔事务中同步本次配置包含的全部结构化元数据"""
        try:
            if meta_config.tables is not None:
                await self.meta_mysql_repository.sync_table_infos(
                    table_infos, column_infos
                )
            if meta_config.metrics is not None:
                await self.meta_mysql_repository.sync_metric_infos(
                    metric_infos, column_metrics
                )
            await self.meta_mysql_repository.session.commit()
            if meta_config.metrics is not None:
                await self.meta_mysql_repository.finalize_schema()
                await self.meta_mysql_repository.session.commit()
        except Exception:
            await self.meta_mysql_repository.session.rollback()
            raise

    async def _save_metrics_to_qdrant(self, metric_infos: list[MetricInfo]):
        """把指标元数据继续推进成可语义检索的 Qdrant 向量点"""
        await self.metric_qdrant_repository.ensure_collection()

        points: list[dict] = []
        for metric_info in metric_infos:
            # 和字段一样，一个指标也会拆成名字 描述 别名这几类语义入口
            points.append(
                {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"metric:{metric_info.id}:name:{metric_info.name}",
                        )
                    ),
                    "embedding_text": metric_info.name,
                    "payload": asdict(metric_info),
                }
            )

            points.append(
                {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"metric:{metric_info.id}:description:{metric_info.description}",
                        )
                    ),
                    "embedding_text": metric_info.description,
                    "payload": asdict(metric_info),
                }
            )

            for alia in metric_info.alias:
                points.append(
                    {
                        "id": str(
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"metric:{metric_info.id}:alias:{alia}",
                            )
                        ),
                        "embedding_text": alia,
                        "payload": asdict(metric_info),
                    }
                )

        # 先把待向量化文本抽出来，再分批调用 Embedding 服务
        # 返回的 embeddings 要继续和前面的 id payload 按顺序对齐
        embedding_texts = [point["embedding_text"] for point in points]
        embeddings = await self._embed_texts(embedding_texts)

        ids = [point["id"] for point in points]
        payloads = [point["payload"] for point in points]

        await self.metric_qdrant_repository.sync(ids, embeddings, payloads)

    async def build(self, config_path: Path):
        """读取配置并依次构建 Meta MySQL Qdrant 和 ES 中的元数据索引"""
        context = OmegaConf.load(config_path)
        schema = OmegaConf.structured(MetaConfig)
        meta_config: MetaConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))

        await self.meta_mysql_repository.ensure_schema(
            can_backfill_formula=meta_config.metrics is not None
        )
        await self.meta_mysql_repository.session.commit()
        column_types_by_table = await self._validate_meta_config(meta_config)
        await self.meta_mysql_repository.session.rollback()
        logger.info("元数据构建配置校验通过")

        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []
        metric_infos: list[MetricInfo] = []
        column_metrics: list[ColumnMetric] = []

        # 根据配置文件判断后续要进入哪条构建链路
        if meta_config.tables is not None:
            table_infos, column_infos = await self._collect_table_infos(
                meta_config, column_types_by_table
            )
            await self.dw_mysql_repository.session.rollback()
            # 对字段信息建立向量索引
            await self._save_column_info_to_qdrant(column_infos)
            logger.info("字段信息向量索引同步完成")
            # 对指定的维度字段取值建立全文索引
            await self._save_value_info_to_es(meta_config, column_infos)
            logger.info("字段取值全文索引同步完成")

        # 根据配置文件同步指定的指标信息
        if meta_config.metrics is not None:
            metric_infos, column_metrics = self._collect_metric_infos(meta_config)
            # 对指标信息建立向量索引
            await self._save_metrics_to_qdrant(metric_infos)
            logger.info("指标信息向量索引同步完成")

        if meta_config.tables is not None or meta_config.metrics is not None:
            # 所有外部索引成功后，再用一笔事务提交本次结构化元数据
            await self._save_meta_to_db(
                meta_config,
                table_infos,
                column_infos,
                metric_infos,
                column_metrics,
            )
            logger.info("结构化元数据同步到 Meta MySQL")
