"""元数据 MySQL 仓储模块"""

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.models.column_info import ColumnInfoMySQL
from app.models.column_metric import ColumnMetricMySQL
from app.models.metric_info import MetricInfoMySQL
from app.models.table_info import TableInfoMySQL


class MetaMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

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