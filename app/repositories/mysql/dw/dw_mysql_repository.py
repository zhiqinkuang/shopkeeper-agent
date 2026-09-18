"""数仓 MySQL 仓储模块"""

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|REPLACE|CREATE|"
    r"GRANT|REVOKE|RENAME|LOAD|CALL)\b",
    re.IGNORECASE,
)
_SELECT_INTO_FILE = re.compile(
    r"\bINTO\s+(OUTFILE|DUMPFILE)\b",
    re.IGNORECASE,
)


def assert_readonly_sql(sql: str) -> None:
    """只允许单条只读 SELECT，拒绝写操作和多语句。"""
    normalized = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    normalized = re.sub(r"--[^\n]*", " ", normalized)
    normalized = re.sub(r"#[^\n]*", " ", normalized).strip()
    if not normalized:
        raise ValueError("SQL 不能为空")
    if ";" in normalized.rstrip().rstrip(";"):
        raise ValueError("禁止一次执行多条 SQL")
    head = re.split(r"\s+", normalized, maxsplit=1)[0].upper()
    if head not in {"SELECT", "WITH"}:
        raise ValueError(f"只允许只读 SELECT，收到: {head}")
    if _FORBIDDEN_SQL.search(normalized) or _SELECT_INTO_FILE.search(normalized):
        raise ValueError("只允许只读 SELECT")


class DWMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        result = await self.session.execute(
            text(
                """
                SELECT COLUMN_NAME, COLUMN_TYPE
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
                """
            ),
            {"table_name": table_name},
        )
        return {
            row["COLUMN_NAME"]: row["COLUMN_TYPE"] for row in result.mappings().all()
        }

    async def get_column_values(
        self, table_name: str, column_name: str, limit: int = 5
    ) -> list[Any]:
        column_types = await self.get_column_types(table_name)
        if column_name not in column_types:
            raise ValueError(f"字段不存在: {table_name}.{column_name}")

        quoted_table = table_name.replace("`", "``")
        quoted_column = column_name.replace("`", "``")
        statement = text(
            f"""
            SELECT DISTINCT `{quoted_column}`
            FROM `{quoted_table}`
            WHERE `{quoted_column}` IS NOT NULL
            ORDER BY `{quoted_column}`
            LIMIT {int(limit)}
            """
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_db_info(self) -> dict[str, str]:
        """读取当前数仓数据库的方言和版本"""
        version = (await self.session.execute(text("select version()"))).scalar()
        if version is None or self.session.bind is None:
            raise RuntimeError("无法读取数仓数据库方言或版本")
        return {
            "dialect": self.session.bind.dialect.name,
            "version": str(version),
        }

    async def validate(self, sql: str) -> None:
        """用 EXPLAIN 让数据库提前解析 SQL，发现语法或字段错误"""
        assert_readonly_sql(sql)
        await self.session.execute(text(f"EXPLAIN {sql}"))

    async def run(self, sql: str) -> list[dict[str, Any]]:
        """执行最终 SQL，并把行记录转成前端可消费的字典列表"""
        assert_readonly_sql(sql)
        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]
