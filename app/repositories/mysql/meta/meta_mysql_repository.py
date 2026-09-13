"""元数据 MySQL 仓储模块"""

from dataclasses import asdict

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.models.column_info import ColumnInfoMySQL
from app.models.column_metric import ColumnMetricMySQL
from app.models.metric_info import MetricInfoMySQL
from app.models.table_info import TableInfoMySQL
from app.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from app.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper


class MetaMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_schema(self, can_backfill_formula: bool):
        """确保已有元数据库包含当前构建链路需要的字段"""
        formula_column = (
            await self.session.execute(
                text(
                    """
                    SELECT IS_NULLABLE
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'metric_info'
                      AND COLUMN_NAME = 'formula'
                    """
                )
            )
        ).first()

        if formula_column is None:
            if not can_backfill_formula:
                raise ValueError("首次增加指标公式字段时必须提供 metrics 配置")
            await self.session.execute(
                text(
                    """
                    ALTER TABLE metric_info
                    ADD COLUMN formula TEXT NULL COMMENT '指标计算公式'
                    """
                )
            )
            return

        if formula_column.IS_NULLABLE == "YES" and not can_backfill_formula:
            raise ValueError("指标公式字段升级尚未完成，必须提供 metrics 配置")

    async def finalize_schema(self):
        """确认指标公式已经回填完成，并收紧数据库非空约束"""
        missing_formula_count = await self.session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM metric_info
                WHERE formula IS NULL OR formula = ''
                """
            )
        )
        if missing_formula_count:
            raise ValueError("存在未回填计算公式的指标")

        formula_nullable = await self.session.scalar(
            text(
                """
                SELECT IS_NULLABLE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'metric_info'
                  AND COLUMN_NAME = 'formula'
                """
            )
        )
        if formula_nullable == "YES":
            await self.session.execute(
                text(
                    """
                    ALTER TABLE metric_info
                    MODIFY COLUMN formula TEXT NOT NULL COMMENT '指标计算公式'
                    """
                )
            )

    async def save_table_infos(self, table_infos: list[TableInfo]):
        for table_info in table_infos:
            await self.session.merge(TableInfoMySQL(**asdict(table_info)))

    async def save_column_infos(self, column_infos: list[ColumnInfo]):
        for column_info in column_infos:
            await self.session.merge(ColumnInfoMySQL(**asdict(column_info)))

    async def save_metric_infos(self, metric_infos: list[MetricInfo]):
        for metric_info in metric_infos:
            await self.session.merge(MetricInfoMySQL(**asdict(metric_info)))

    async def save_column_metrics(self, column_metrics: list[ColumnMetric]):
        for column_metric in column_metrics:
            await self.session.merge(ColumnMetricMySQL(**asdict(column_metric)))

    async def get_column_ids(self) -> set[str]:
        """读取当前元数据库中的全部字段标识"""
        return set((await self.session.scalars(select(ColumnInfoMySQL.id))).all())

    async def get_metric_column_ids(self) -> set[str]:
        """读取当前指标关系引用的全部字段标识"""
        return set(
            (
                await self.session.scalars(
                    select(ColumnMetricMySQL.column_id).distinct()
                )
            ).all()
        )

    async def get_column_info_by_id(self, id: str) -> ColumnInfo:
        """按字段 ID 查询完整元数据"""
        column_info = await self.session.get(ColumnInfoMySQL, id)
        if column_info is None:
            raise LookupError(f"字段元数据不存在: {id}")
        return ColumnInfoMapper.to_entity(column_info)

    async def get_table_info_by_id(self, id: str) -> TableInfo:
        """按表 ID 查询完整元数据"""
        table_info = await self.session.get(TableInfoMySQL, id)
        if table_info is None:
            raise LookupError(f"表元数据不存在: {id}")
        return TableInfoMapper.to_entity(table_info)

    async def get_key_columns_by_table_id(
        self, table_id: str
    ) -> list[ColumnInfo]:
        """查询指定表的主键和外键字段"""
        models = (
            await self.session.scalars(
                select(ColumnInfoMySQL).where(
                    ColumnInfoMySQL.table_id == table_id,
                    ColumnInfoMySQL.role.in_(("primary_key", "foreign_key")),
                )
            )
        ).all()
        return [ColumnInfoMapper.to_entity(model) for model in models]

    async def sync_table_infos(
        self, table_infos: list[TableInfo], column_infos: list[ColumnInfo]
    ):
        """同步表和字段元数据，并删除配置中已经不存在的记录"""
        await self.save_table_infos(table_infos)
        await self.save_column_infos(column_infos)

        expected_table_ids = {table_info.id for table_info in table_infos}
        expected_column_ids = {column_info.id for column_info in column_infos}
        existing_table_ids = set(
            (await self.session.scalars(select(TableInfoMySQL.id))).all()
        )
        existing_column_ids = set(
            (await self.session.scalars(select(ColumnInfoMySQL.id))).all()
        )

        stale_column_ids = existing_column_ids - expected_column_ids
        if stale_column_ids:
            await self.session.execute(
                delete(ColumnMetricMySQL).where(
                    ColumnMetricMySQL.column_id.in_(stale_column_ids)
                )
            )
            await self.session.execute(
                delete(ColumnInfoMySQL).where(ColumnInfoMySQL.id.in_(stale_column_ids))
            )

        stale_table_ids = existing_table_ids - expected_table_ids
        if stale_table_ids:
            await self.session.execute(
                delete(TableInfoMySQL).where(TableInfoMySQL.id.in_(stale_table_ids))
            )

    async def sync_metric_infos(
        self, metric_infos: list[MetricInfo], column_metrics: list[ColumnMetric]
    ):
        """同步指标及字段关系，并删除配置中已经不存在的记录"""
        await self.save_metric_infos(metric_infos)
        await self.save_column_metrics(column_metrics)

        expected_metric_ids = {metric_info.id for metric_info in metric_infos}
        expected_relations = {
            (column_metric.column_id, column_metric.metric_id)
            for column_metric in column_metrics
        }
        existing_relations = {
            (row.column_id, row.metric_id)
            for row in (
                await self.session.execute(
                    select(
                        ColumnMetricMySQL.column_id,
                        ColumnMetricMySQL.metric_id,
                    )
                )
            ).all()
        }

        for column_id, metric_id in existing_relations - expected_relations:
            await self.session.execute(
                delete(ColumnMetricMySQL).where(
                    ColumnMetricMySQL.column_id == column_id,
                    ColumnMetricMySQL.metric_id == metric_id,
                )
            )

        existing_metric_ids = set(
            (await self.session.scalars(select(MetricInfoMySQL.id))).all()
        )
        stale_metric_ids = existing_metric_ids - expected_metric_ids
        if stale_metric_ids:
            await self.session.execute(
                delete(MetricInfoMySQL).where(MetricInfoMySQL.id.in_(stale_metric_ids))
            )
