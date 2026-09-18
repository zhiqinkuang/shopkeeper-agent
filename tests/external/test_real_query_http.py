import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.conf.app_config import app_config

pytestmark = pytest.mark.external

QUESTION = "统计华北地区的销售总额"
EXPECTED_PROGRESS = {
    "抽取关键词",
    "召回字段信息",
    "召回指标信息",
    "召回字段取值",
    "合并召回信息",
    "过滤表信息",
    "过滤指标信息",
    "添加额外上下文",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_HOST = "127.0.0.1"
API_PORT = 18080
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PERF_RUNS = 5


def _require_real_llm() -> None:
    if os.getenv("RUN_REAL_LLM") != "1":
        pytest.skip("仅在显式启用真实 LLM 测试时执行")
    if not app_config.llm.api_key:
        pytest.skip("缺少 LLM_API_KEY")
    if not app_config.embedding.api_key:
        pytest.skip("缺少 EMBEDDING_API_KEY")


def _percentile(samples: list[float], percent: float) -> float:
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * percent / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _parse_sse_payloads(body: str) -> list[object]:
    payloads = []
    for block in body.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            payloads.append(json.loads(line[5:].strip()))
    return payloads


def _server_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DB_META_HOST": "127.0.0.1",
            "DB_META_PORT": "13307",
            "DB_META_USER": "didilili",
            "DB_META_PASSWORD": "test-password",
            "DB_DW_HOST": "127.0.0.1",
            "DB_DW_PORT": "13307",
            "DB_DW_USER": "didilili",
            "DB_DW_PASSWORD": "test-password",
            "QDRANT_HOST": "127.0.0.1",
            "QDRANT_PORT": "16333",
            "ES_HOST": "127.0.0.1",
            "ES_PORT": "19200",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )
    for key in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        env.pop(key, None)
    return env


@pytest.fixture(scope="module")
def query_api_base_url():
    _require_real_llm()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
        ],
        cwd=PROJECT_ROOT,
        env=_server_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 30
        last_error = None
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                pytest.fail(f"问数 API 进程提前退出: {output}")
            try:
                response = httpx.get(
                    f"{API_BASE_URL}/openapi.json",
                    timeout=1.0,
                    trust_env=False,
                )
                if response.status_code == 200:
                    yield API_BASE_URL
                    return
            except httpx.HTTPError as error:
                last_error = error
            time.sleep(0.2)
        pytest.fail(f"问数 API 未能在 30 秒内就绪: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _post_query(base_url: str) -> tuple[httpx.Response, list[object], float]:
    started = time.perf_counter()
    response = httpx.post(
        f"{base_url}/api/query",
        json={"query": QUESTION},
        timeout=120.0,
        trust_env=False,
    )
    elapsed = time.perf_counter() - started
    return response, _parse_sse_payloads(response.text), elapsed


def test_real_http_query_contract_and_latency(query_api_base_url, capsys):
    samples: list[float] = []
    payloads: list[object] = []
    for _ in range(PERF_RUNS):
        response, payloads, elapsed = _post_query(query_api_base_url)
        samples.append(elapsed)

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        assert not any(
            isinstance(item, dict) and item.get("type") == "error" for item in payloads
        )
        assert EXPECTED_PROGRESS <= {
            item["step"]
            for item in payloads
            if isinstance(item, dict) and item.get("type") == "progress"
        }
        assert elapsed < 120

    p50 = _percentile(samples, 50)
    p95 = _percentile(samples, 95)
    with capsys.disabled():
        print(
            "HTTP /api/query 延迟基线 "
            f"n={len(samples)} samples={[round(item, 3) for item in samples]} "
            f"p50={p50:.3f}s p95={p95:.3f}s"
        )
