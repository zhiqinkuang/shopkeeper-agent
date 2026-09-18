import pytest

from app.repositories.mysql.dw.dw_mysql_repository import assert_readonly_sql

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select sum(order_amount) from fact_order",
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
        "SELECT 1;  ",
    ],
)
def test_assert_readonly_sql_allows_select(sql):
    assert_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO fact_order (order_id) VALUES (1)",
        "DELETE FROM fact_order",
        "UPDATE fact_order SET order_amount = 0",
        "DROP TABLE fact_order",
        "ALTER TABLE fact_order ADD COLUMN x INT",
        "SELECT 1; DELETE FROM fact_order",
        "SELECT * FROM fact_order INTO OUTFILE '/tmp/x.csv'",
        "",
        "```sql SELECT 1 ```",
    ],
)
def test_assert_readonly_sql_rejects_writes(sql):
    with pytest.raises(ValueError):
        assert_readonly_sql(sql)
