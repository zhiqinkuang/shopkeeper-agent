# shopkeeper-agent

电商问数智能体：用自然语言查教学订单数仓，走完「召回元数据 → 生成 SQL → EXPLAIN 校验 → 必要时校正 → 执行 → 中文回答」。

后端是 LangGraph + FastAPI，元数据在 MySQL，字段/指标向量在 Qdrant，字段取值在 Elasticsearch。前端是 React 聊天页，通过 SSE 展示进度、结果表和回答。

## 能做什么

对隔离测试数仓提问，例如：

```text
统计华北地区的销售总额
```

一次问答会：

1. 抽关键词，召回表、指标和取值
2. 过滤出生成 SQL 需要的上下文
3. 生成只读 `SELECT`，用 `EXPLAIN` 校验，失败则校正后再校验
4. 执行查询，生成中文回答（回答里的数字必须能在结果或原问题里对上）
5. 把问题、SQL、结果和回答写入 `query_audit`，可用请求头 `X-Request-ID` 回放

华北 GMV 的金标结果是 **41099.5**。

## 架构

```text
浏览器  --SSE-->  FastAPI /api/query
                     |
                     v
               LangGraph 问数图
                     |
     +---------------+---------------+
     |               |               |
  Meta MySQL      Qdrant            ES
  (表/指标/审计)   (字段/指标向量)   (字段取值)
                     |
                  DW MySQL
                (只读 SELECT)
```

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/query` | SSE：`progress` / `result` / `answer` / `error` |
| `GET` | `/api/audits/{request_id}` | 按 `X-Request-ID` 回放 SQL 和结果 |

SSE 不会推送审计事件，避免前端把未知类型当成失败。

## 环境

- Python 3.13、[uv](https://docs.astral.sh/uv/)
- Node.js + pnpm（前端）
- Docker：MySQL 8、Qdrant、Elasticsearch
- DashScope Embedding、DeepSeek 对话模型（密钥放在 `.env`，不要提交）

```bash
cp .env.example .env
```

至少填 `DB_*`、`EMBEDDING_API_KEY`、`LLM_API_KEY`。本地开发库默认端口是 `3307` / `6333` / `9200`；隔离测试栈映射到 `13307` / `16333` / `19200`。

## 启动

开发依赖（MySQL / Qdrant / ES）：

```bash
cd docker
docker compose up -d --build
```

构建元数据知识库：

```bash
uv sync --group dev
PYTHONPATH=. uv run python app/scripts/build_meta_knowledge.py -c conf/meta_config.yaml
```

后端：

```bash
PYTHONPATH=. uv run fastapi dev main.py --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

打开 http://127.0.0.1:5173 。开发时代理会把 `/api` 转到 `8000`。

隔离测试栈（给 pytest / eval 用，不要和开发栈抢端口）：

```bash
cd docker
docker compose -p shopkeeper-agent-test -f docker-compose.test.yml up -d --build --wait
```

测试库账号是 `didilili` / `test-password`，只用于本地 Docker，不是线上密钥。

## 测试

```bash
# 静态检查
uv run ruff check app tests
uv run python -m compileall -q app main.py

# 单元测试
PYTHONPATH=. uv run pytest tests/unit

# 单元 + 隔离 Docker 集成测试
# 注意：integration 会清空 meta 表，跑完需要重新 build_meta_knowledge
PYTHONPATH=. uv run pytest tests/unit tests/integration

# 前端
cd frontend && pnpm test
```

真实模型抽检（需密钥，且测试 Docker 上已构建知识库）：

```bash
NO_PROXY='*' no_proxy='*' RUN_REAL_LLM=1 \
  PYTHONPATH=. uv run pytest tests/external/test_agent_gold_sample.py -q
```

120 条场景目录在 `app/scripts/query_scenario_catalog.py`。评测脚本：

```bash
# 只打金标 SQL
PYTHONPATH=. uv run python app/scripts/eval_query_scenarios.py

# 40 条智能体结果抽检（对比取值，不要求 SQL 字面量一致）
PYTHONPATH=. uv run python app/scripts/eval_query_scenarios.py --agent --sample
```

CI（`.github/workflows/ci.yml`）在 PR 上跑质量检查、单元和集成测试；push 到 `main` 或手动触发时，还会跑真实 Embedding 冒烟，以及 40 条智能体对账（需要仓库 Secrets：`EMBEDDING_API_KEY`、`LLM_API_KEY`）。

## 测试结果（2026-09-13，隔离测试 Docker + 真实模型）

环境：MySQL `127.0.0.1:13307`，Qdrant `16333`，ES `19200`，Embedding `text-embedding-v4`，对话模型 `deepseek-v4-flash`。

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| Gold SQL 120 条 | **120/120** | 标准答案能在数仓跑通，空结果标记正确 |
| 召回/过滤（表+指标） | **117/120** | 表 118/120，指标 119/120。T007/T008 是目录期望 `dim_date`、gold SQL 实际用 `fact_order.date_id`；B011 是真漏，交叉分组时 GMV 被滤空 |
| 智能体结果抽检 | **10/10** | 对比取值不比 SQL。覆盖全局聚合、华北 GMV、分组、排名、空结果。K012 初跑只答「华中」、没带回 GMV，放宽排名规则后通过 |
| HTTP `POST /api/query` | 5 次，p50 **12.1s**，p95 **14.2s** | 问题「统计华北地区的销售总额」，瓶颈在多次串行 LLM，不是 MySQL |
| 端到端金标 | 华北 GMV **41099.5** | 生成 SQL → EXPLAIN → 执行 |
| 自动化回归（同日晚） | 单元+集成 **133 passed**，行/分支覆盖 **91.70%**；核心构建模块 **97.51%**；前端 vitest **6 passed**；外部真实 API **4 passed** | 覆盖率门禁：全局 80%，核心构建 90% |

这 10 条抽检说明当前模型和知识库在这些口径上对得上，**不能外推到另外 110 条**。40 条抽检集合已经写进 `AGENT_SAMPLE_IDS`（含 B011 回归），完整 40 次真实 LLM 对账还没有在本地重跑。

回答数字校验、查询审计表是后续补上的能力：编造数字会被替换成兜底文案；任意一次 `/api/query` 可用：

```bash
curl --noproxy '*' -D - http://127.0.0.1:8000/docs
# 记下 X-Request-ID
curl --noproxy '*' http://127.0.0.1:8000/api/audits/<request-id>
```

## 只读约束

数仓仓储只接受单条 `SELECT` / `WITH`。`INSERT` / `UPDATE` / `DELETE` 会在校验和执行前被拒绝。
