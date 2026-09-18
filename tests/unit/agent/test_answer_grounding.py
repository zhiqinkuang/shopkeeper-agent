from decimal import Decimal

import pytest

from app.agent.answer_grounding import (
    answer_is_grounded,
    extract_numbers,
    fallback_answer,
    result_numbers,
)

pytestmark = pytest.mark.unit


def test_extract_numbers_handles_commas_and_decimals():
    assert extract_numbers("合计 41,099.50 元，共 12 单") == {41099.5, 12.0}


def test_result_numbers_reads_decimal_cells():
    assert result_numbers([{"gmv": Decimal("41099.50"), "name": "华北"}]) == {41099.5}


def test_answer_is_grounded_accepts_result_and_question_numbers():
    rows = [{"gmv": 41099.5}]

    assert answer_is_grounded("华北地区销售总额为 41099.5 元。", rows) is True
    assert answer_is_grounded("2025 年华北地区销售总额为 41099.5 元。", rows, "2025年华北") is True
    assert answer_is_grounded("华北地区销售总额为 99999 元。", rows) is False


def test_fallback_answer_depends_on_empty_result():
    assert fallback_answer([]) == "没有查到符合条件的数据。"
    assert fallback_answer([{"gmv": None}]) == "没有查到符合条件的数据。"
    assert fallback_answer([{"gmv": 1}]) == "查询完成，请直接查看下方结果。"