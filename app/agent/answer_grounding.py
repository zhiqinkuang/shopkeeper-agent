"""校验自然语言回答里的数字是否来自查询结果或原问题。"""

import re
from decimal import Decimal

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+")


def extract_numbers(text: str) -> set[float]:
    """抽出文本中的阿拉伯数字，统一到两位小数。"""
    values = set()
    for match in _NUMBER.finditer(text):
        values.add(round(float(match.group().replace(",", "")), 2))
    return values


def result_numbers(rows: list[dict]) -> set[float]:
    """抽出结果单元格里的数字。"""
    values = set()
    for row in rows:
        for cell in row.values():
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, Decimal):
                values.add(round(float(cell), 2))
            elif isinstance(cell, (int, float)):
                values.add(round(float(cell), 2))
    return values


def answer_is_grounded(answer: str, rows: list[dict], query: str = "") -> bool:
    """回答中的数字必须出现在结果或原问题里。"""
    allowed = result_numbers(rows) | extract_numbers(query)
    for number in extract_numbers(answer):
        if not any(abs(number - allowed_number) < 0.011 for allowed_number in allowed):
            return False
    return True


def fallback_answer(rows: list[dict]) -> str:
    """数字对不上时，不用模型自由发挥。"""
    if not rows or (
        len(rows) == 1 and all(value is None for value in rows[0].values())
    ):
        return "没有查到符合条件的数据。"
    return "查询完成，请直接查看下方结果。"
