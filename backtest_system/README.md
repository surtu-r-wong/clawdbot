# backtest_system 使用说明

## 1. 项目概览

本目录是一个“自动策略回测系统”的最小实现，核心由三部分组成：

- `main.py`：Click 命令行入口（`smart / specified / history`）。
- `core/`：`DatabaseAPI`（数据/日志/结果写入）、`Supervisor`（执行监管&异常处理）、`Orchestrator`（流程编排）。
- `skills/`：可插拔的执行单元（数据校验、单策略回测、组合回测、报告生成）。
- `web/`：FastAPI 示例接口（目前多数接口为占位实现）。

## 2. 安装依赖

建议使用 Python 3.12+ 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 配置说明（重要）

本项目默认使用**环境变量**或**YAML 配置文件**（示例：`config.example.yaml`），不再在代码里写死地址/Token。

支持的环境变量（优先级最高）：

- `BACKTEST_CONFIG`：YAML 配置路径（可选）
- `BACKTEST_DB_URL`：Postgres 直连（`history`/Web 查询用）
- `BACKTEST_API_READ_URL`：行情读取 API Base URL
- `BACKTEST_API_WRITE_URL`：任务/日志/结果写入 API Base URL
- `BACKTEST_API_TOKEN`：API Token（可为空）
- `BACKTEST_API_TIMEOUT_SECONDS`：HTTP 超时（秒）
- `BACKTEST_API_TRUST_ENV`：是否信任系统代理环境变量（`HTTP(S)_PROXY/NO_PROXY`，默认 `false`）
- `BACKTEST_OUTPUT_DIR`：输出目录（默认 `output`）
- `BACKTEST_NON_INTERACTIVE`：是否禁止交互（默认 `true`）
- `BACKTEST_ON_ESCALATE`：非交互时遇到需人工升级的处理策略（`halt|retry|skip`）

## 4. 命令行使用

### 4.1 运行方式

由于 `main.py` 使用包导入（`from backtest_system...`），推荐用模块方式运行：

```bash
# 在本目录执行（通过 PYTHONPATH 把上级目录加入模块搜索路径）
PYTHONPATH=.. python3 -m backtest_system.main --help
```

你可以用 YAML 文件：

```bash
cp config.example.yaml config.yaml
PYTHONPATH=.. python3 -m backtest_system.main --config config.yaml --help
```

### 4.2 smart（智能模式）

```bash
PYTHONPATH=.. python3 -m backtest_system.main smart \
  --positions "多AU,空AG,多L-V:2:1" \
  --periods "3y,5y,10y" \
  --combo-range "3-5" \
  --portfolio-models "mean_variance,equal_weight" \
  --top-n 10 \
  --strategy-max-evals 2000
```

- `--positions`：逗号分隔的头寸列表（见“头寸格式”）。
- `--periods`：回测周期列表（会按周期切片，并为每个周期分别回测/组合）。
- `--combo-range`：组合大小范围，如 `3-5`。
- `--portfolio-models`：组合权重模型，当前支持 `mean_variance / equal_weight`。
- `--top-n`：报告中输出每个周期 Top N 的组合结果。
- `--strategy-max-evals`：单策略参数搜索最大评估次数（随机采样/小规模网格，避免组合爆炸）。

经验建议：

- 头寸池（`--positions`）一般建议 4~10 个；太少组合空间不足，太多会导致组合枚举爆炸。
- 回测周期（`--periods`）一般建议至少包含 `5y`（例如 `5y,10y`），短周期（`3m,6m`）更适合做鲁棒性/近期表现观察。

### 4.3 specified（指定模式）

```bash
PYTHONPATH=.. python3 -m backtest_system.main specified \
  --positions "多AU,空AG" \
  --period "5y" \
  --portfolio-model "mean_variance" \
  --strategy-max-evals 2000
```

### 4.4 history（任务历史）

```bash
PYTHONPATH=.. python3 -m backtest_system.main history --limit 20
```

说明：`history` 走的是数据库直连查询（`DatabaseAPI.read()`），需要配置 `BACKTEST_DB_URL`，且库内存在 `backtest_tasks` 表。

## 5. 头寸格式（`skills/backtest_strategy.py::parse_position`）

支持以下形式（不区分大小写会被转成大写）：

- 单品种
  - `多AU`：做多 AU，权重 1
  - `空AU`：做空 AU，权重 -1
  - `多AU:2`：做多 AU，权重 2
- 对冲（两个品种，用 `-` 连接，后面用 `:A:B` 指定市值比例）
  - `多L-V:1:1`：做多 L(1) + 做空 V(1)
  - `空L-V:2:1`：方向反转（代码会按 direction 调整多空符号）

## 6. 输出物

- Excel 报告默认写到 `output/{task_id}.xlsx`（可用 `BACKTEST_OUTPUT_DIR` 或 YAML 修改）。
- 执行日志会同时落一份本地文件：`output/{task_id}.logs.jsonl`（即使远程日志 API 偶发失败也不影响排查）。
- `web/app.py` 提供了一个下载接口：`GET /api/reports/{task_id}/download`。

## 7. Web 接口（可选）

```bash
PYTHONPATH=.. uvicorn backtest_system.web.app:app --host 0.0.0.0 --port 8080
```

说明：

- Web 查询 `/api/tasks*`、`/api/tasks/{task_id}/logs` 需要配置 `BACKTEST_DB_URL`（直连查询）。
- `fastapi/uvicorn` 需要通过 `pip install -r requirements.txt` 安装后才能运行 Web。
- `GET /api/reports/{task_id}/download` 用于下载 Excel。

## 8. 初始化数据库（可选）

`scripts/init_db.sql` 提供了一个基础表结构示例：

```bash
psql "$BACKTEST_DB_URL" -f scripts/init_db.sql
```

注意：本项目的日志/任务/结果写入默认走 HTTP API（见 `core/database.py`），是否使用本 SQL 取决于你的部署方式。

## 9. 已知限制（建议优先改进）

- `skills/backtest_strategy.py`：当前实现的是“基于 close/均线比值的阈值择时”示例策略，参数含义已落地但并不代表你的真实交易逻辑；如需替换为你的策略，请在该 Skill 中实现信号与交易规则。
- `skills/backtest_portfolio.py`：组合权重为简单的等权/均值方差优化，未考虑交易成本/约束/杠杆等更复杂条件。

## 10. 常见问题：HTTP 502 / 网络错误

如果你的环境里设置了全局代理（例如 `HTTP_PROXY=http://127.0.0.1:7897`），而 API 又是内网 IP（例如 `100.x.x.x`），
`curl`/`requests` 很可能会把请求转发到代理，导致看到 `502 Bad Gateway` 或连接失败。

处理方式二选一：

1) 给 `NO_PROXY/no_proxy` 增加 API 地址（建议写具体 IP，不要写 CIDR）：

```bash
export NO_PROXY="$NO_PROXY,100.75.102.44,100.67.45.63"
export no_proxy="$NO_PROXY"
```

2) 让本项目忽略代理环境变量（推荐）：

```bash
export BACKTEST_API_TRUST_ENV=false
```
