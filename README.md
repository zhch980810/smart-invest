# 智慧投资仓库（smart-invest）

A 股"政策 + 量化"长期投资初筛工具。采用两步流水线架构：先准备目标股票池，再采集 9 维数据并初筛输出 CSV。

---

## 项目结构

```
smart-invest/
├── requirements.txt              # Python 依赖（锁定版本）
├── test_refactor.py              # 重构验证脚本（7 项检查）
├── plan.md                       # 重构计划文档
├── scripts/
│   ├── prepare_stocks.py         # Step 1: 生成目标股票池 → stocks/stocks.txt
│   ├── collect_and_filter.py     # Step 2: 数据采集 + 初筛 → CSV
│   ├── send_invest_email.py      # 投资日报邮件发送
│   ├── run_daily_job.sh          # 一键日跑脚本（Step1 + Step2 + 邮件）
│   └── a_share_selector/         # 核心模块
│       ├── __init__.py           # 导出: collect_all, load_codes, score_policy, infer_sector
│       ├── data_fetch.py         # 数据采集统一模块（快照/K线/财务/资金面）
│       └── quant_model.py        # 量化模型（打分 + 板块推断）
├── stocks/
│   └── stocks.txt                # 当前目标股票池（代码列表）
├── user/
│   ├── user_interest.txt         # 用户感兴趣的板块关键词
│   ├── user_stocks.txt           # 用户指定的股票清单
│   ├── policy_signals.json       # 政策主题配置
│   └── README.md                 # 用户配置说明
├── data/                         # 采集输出（CSV 等）
├── reports/                      # 评估报告
├── deploy/                       # 部署配置（systemd / cron）
│   ├── smart-invest.service
│   ├── smart-invest.timer
│   ├── cron.daily.example
│   └── systemd.README.md
└── tests/                        # 测试目录（预留扩展）
```

---

## 环境配置（Conda）

本项目使用 Conda 管理 Python 环境，推荐 Python 3.12。

### 创建环境

```bash
conda create -n ashare python=3.12 -y
conda activate ashare
```

### 安装依赖

```bash
pip install -r requirements.txt
```

### 验证环境

```bash
python -c "import requests; import akshare; import pandas; print('OK')"
```

### 日常使用

```bash
# 激活环境
conda activate ashare

# 退出环境
conda deactivate
```

> **依赖说明**：`requirements.txt` 中锁定了三个直接依赖的版本号：
> - `requests` — HTTP 请求
> - `akshare` — A 股 K 线、财务、资金面数据
> - `pandas` — DataFrame 数据处理

---

## 使用方式

### 两步流水线

**Step 1：准备目标股票池**

```bash
# 从用户股票清单生成
python scripts/prepare_stocks.py --source user_stocks

# 或按板块关键词搜索
python scripts/prepare_stocks.py --source user_interest
```

输出：`stocks/stocks.txt`（每行一个股票代码）

**Step 2：数据采集 + 初筛 → CSV**

```bash
python scripts/collect_and_filter.py [--stocks-file stocks/stocks.txt] [--output-dir data/]
```

输出：`data/filtered_YYYYMMDD.csv`

### 一键执行

```bash
bash scripts/run_daily_job.sh [user_stocks|user_interest]
```

该脚本依次执行 Step 1 → Step 2 → 邮件发送，日志保存到 `logs/` 目录。

### 发送日报邮件（可选）

```bash
MAIL_BODY="$(head -50 data/filtered_YYYYMMDD.csv)" python scripts/send_invest_email.py
# 仅告警模式（不群发，仅发件人）
MAIL_BODY="任务失败，请检查日志" python scripts/send_invest_email.py --alert-only
```

---

## 测试流程

项目当前通过 `test_refactor.py` 进行脚本式验证，确保重构后的模块结构完整可用。

### 运行测试

```bash
conda activate ashare
python test_refactor.py
```

### 检查项目（共 7 项）

| 编号 | 检查内容 | 说明 |
|------|----------|------|
| 1 | `data_fetch` 模块导入 | 验证合并后的统一模块可正常导入（`http_get`, `request_with_retry`, `to_float`, `code_to_secid`, `fetch_kline`, `fetch_snapshot_by_codes`, `eastmoney_get`, `load_codes`, `collect_all`, `EASTMONEY_HEADERS`） |
| 2 | `data_collector.py` 已删除 | 确认旧文件已合并入 `data_fetch.py` |
| 3 | `quant_model` 导入 | 验证 `score_policy`、`infer_sector` 可正常导入 |
| 4 | `__init__.py` 导出 | 验证包级别导出完整（`collect_all`, `load_codes`, `score_policy`, `infer_sector`） |
| 5 | 旧 K 线函数已移除 | 确认 `fetch_kline_eastmoney`、`fetch_kline_tencent`、`fetch_kline_sina` 不再存在 |
| 6 | `collect_and_filter` 可导入 | 验证 Step 2 入口模块正常 |
| 7 | `prepare_stocks` 可导入 | 验证 Step 1 入口模块正常 |

### 预期输出

```
OK data_fetch imports (merged module)
OK data_collector.py removed (merged into data_fetch)
OK quant_model imports
OK __init__ exports
OK legacy kline functions removed
OK collect_and_filter imports
OK prepare_stocks imports

All checks passed
```

### 扩展

`tests/` 目录预留用于后续添加更细粒度的单元测试。

---

## 部署（可选）

参考 `deploy/` 目录下的配置文件：

- **Systemd**：`smart-invest.service` + `smart-invest.timer`（详见 `deploy/systemd.README.md`）
- **Cron**：`deploy/cron.daily.example`

---

## 风险提示

仅供研究参考，不构成投资建议。
