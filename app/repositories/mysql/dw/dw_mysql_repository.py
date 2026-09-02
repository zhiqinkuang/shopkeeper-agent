"""数仓 MySQL 仓储模块"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
            LIMIT {int(limit)}
            """
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())