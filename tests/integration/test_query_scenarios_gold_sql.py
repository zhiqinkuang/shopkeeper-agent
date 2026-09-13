import pytest
from sqlalchemy import text

from app.scripts.eval_query_scenarios import _rows_are_empty
from app.scripts.query_scenario_catalog import build_query_scenarios

pytestmark = pytest.mark.integration


async def test_gold_sql_scenarios_run_against_dw(mysql_managers):
    scenarios = build_query_scenarios()
    assert len(scenarios) == 120

    _, dw_manager = mysql_managers
    async with dw_manager.session_factory() as session:
        for scenario in scenarios:
            result = await session.execute(text(scenario["gold_sql"]))
            rows = [dict(row) for row in result.mappings().all()]
            empty = _rows_are_empty(rows)
            assert empty == scenario["expect_empty"], scenario["id"]
