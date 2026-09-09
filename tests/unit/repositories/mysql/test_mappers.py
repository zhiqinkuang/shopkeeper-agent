import pytest

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.metric_info import MetricInfo
from app.entities.table_info import TableInfo
from app.repositories.mysql.meta.mappers.column_info_mapper import (
    ColumnInfoMapper,
)
from app.repositories.mysql.meta.mappers.column_metric_mapper import (
    ColumnMetricMapper,
)
from app.repositories.mysql.meta.mappers.metric_info_mapper import (
    MetricInfoMapper,
)
from app.repositories.mysql.meta.mappers.table_info_mapper import (
    TableInfoMapper,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("mapper", "entity"),
    [
        (
            TableInfoMapper,
            TableInfo("dim_region", "dim_region", "dim", "地区维度表"),
        ),
        (
            ColumnInfoMapper,
            ColumnInfo(
                "dim_region.province",
                "province",
                "varchar(50)",
                "dimension",
                ["广东省"],
                "省份",
                ["所在省份"],
                "dim_region",
            ),
        ),
        (
            MetricInfoMapper,
            MetricInfo(
                "GMV",
                "GMV",
                "成交总额",
                ["fact_order.order_amount"],
                ["订单总额"],
                "SUM(fact_order.order_amount)",
            ),
        ),
        (
            ColumnMetricMapper,
            ColumnMetric("fact_order.order_amount", "GMV"),
        ),
    ],
)
def test_mapper_round_trip(mapper, entity):
    model = mapper.to_model(entity)

    assert mapper.to_entity(model) == entity
