from decimal import Decimal

import pytest

from app.scripts.eval_query_scenarios import (
    AGENT_SAMPLE_IDS,
    results_match,
    select_scenarios,
)

pytestmark = pytest.mark.unit


def test_select_scenarios_keeps_sample_order_and_coverage():
    scenarios = select_scenarios(AGENT_SAMPLE_IDS)

    assert [item["id"] for item in scenarios] == list(AGENT_SAMPLE_IDS)
    assert len(scenarios) == 10
    assert {item["category"] for item in scenarios} >= {
        "global_agg",
        "region",
        "customer",
        "product",
        "time",
        "group_by",
        "ranking",
        "zero",
    }


def test_select_scenarios_rejects_unknown_id():
    with pytest.raises(KeyError, match="未知场景"):
        select_scenarios(["NOPE"])


def test_results_match_ignores_column_names_and_decimals():
    gold = [{"gmv": Decimal("41099.50"), "region_name": "华北"}]
    agent = [{"销售总额": 41099.5, "大区": "华北"}]

    assert results_match(gold, agent) is True


def test_results_match_treats_null_aggregate_as_empty():
    assert results_match([{"gmv": None}], []) is True
    assert results_match([], [{"销售额": None}]) is True


def test_results_match_detects_wrong_numbers():
    assert results_match([{"gmv": 41099.5}], [{"gmv": 1}]) is False
    assert results_match([{"region_name": "华北", "gmv": 1}], [{"gmv": 1}]) is False


def test_results_match_allows_missing_metric_when_dimension_matches():
    gold = [{"region_name": "华中", "gmv": 28957.0}]

    assert results_match(gold, [{"region_name": "华中"}]) is True
    assert results_match(gold, [{"region_name": "华东"}]) is False
