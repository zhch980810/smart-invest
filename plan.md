## 计划：重构数据采集流程 + 生成 CSV 候选表

**概要**：将项目改造为两步流水线。Step 1（已有 `prepare_stocks.py`）从用户输入生成 `stocks.txt`；Step 2（新建 `collect_and_filter.py`）读取 `stocks.txt`，通过 akshare + 东财现有接口获取 9 维数据，经初筛后输出 CSV 供后续量化模块使用。同时精简掉不再需要的旧代码。

---

**Steps**

### 1. 安装 akshare 依赖

在项目环境中 `pip install akshare`，并在项目根目录添加 `requirements.txt`（新建），包含 `requests` 和 `akshare`。

### 2. 新建数据采集模块 `scripts/a_share_selector/data_collector.py`

新文件，负责按股票代码获取 9 维数据，每个数据点一个函数：

| 数据点 | akshare 函数 / 现有接口 | 字段 |
|---|---|---|
| **PE (TTM)** | 现有 `fetch_snapshot_by_codes()` → `f9` | `pe_ttm` |
| **市值** | 现有 `fetch_snapshot_by_codes()` → `f20` | `market_cap` |
| **近5日收益率** | 现有 K 线函数计算 `(close[-1]/close[-6] - 1)` | `return_5d` |
| **ROE** | `ak.stock_financial_analysis_indicator(symbol, start_date)` → 净资产收益率(摊薄) | `roe` |
| **净利润增长率** | `ak.stock_yjbb_em(date)` (业绩报表) → 净利润同比增长率列 | `net_profit_growth` |
| **两融差额** | `ak.stock_margin_detail_szse()` / `ak.stock_margin_detail_sse()` → 融资余额 - 融券余额 | `margin_balance` |
| **资金流向(5日/10日)** | `ak.stock_individual_fund_flow(stock, market)` → 近5日/10日主力净流入累计 | `fund_flow_5d`, `fund_flow_10d` |
| **户均持股** | `ak.stock_zh_a_gdhs_detail_em(symbol)` → 户均持股金额/户数 | `avg_holding_per_account` |
| **主力持仓比例** | `ak.stock_individual_fund_flow()` → 主力净流入占比作为代理指标 | `main_force_ratio` |

设计一个统一入口函数 `collect_all(codes: List[str]) -> pd.DataFrame`，按遍历每只股票获取全部字段，内置限速（`time.sleep`）和异常处理（单只失败不影响其他），返回 DataFrame。

### 3. 新建主脚本 `scripts/collect_and_filter.py`

从 `stocks/stocks.txt` 读取股票代码列表 → 调用 Step 2 的 `collect_all()` → 执行初筛 → 输出 CSV。

**初筛规则**（在 DataFrame 上直接过滤）：
- 仅保留主板：代码以 `000/001/002/003/600/601/603/605` 开头，排除 `300xxx`（创业板）和 `688xxx`（科创板）
- `market_cap > 1e10`（100 亿元）
- `0 < pe_ttm < 200`

**输出**：
- `data/candidates_YYYYMMDD.csv` — 全字段 CSV（含所有 9 维数据 + 股票代码/名称/行业）
- 控制台打印初筛统计摘要

**CLI 接口**：
```
python3 scripts/collect_and_filter.py [--stocks-file stocks/stocks.txt] [--output-dir data/]
```

CSV 列定义（供后续量化模块消费）：
`code, name, industry, market_cap, pe_ttm, roe, net_profit_growth, margin_balance, fund_flow_5d, fund_flow_10d, avg_holding_per_account, main_force_ratio, return_5d, price, pct_chg`

### 4. 验证 akshare 数据源可用性

在实现前，先编写一个小的验证脚本/测试块，针对 2–3 只已知股票（如 `600406` 国电南瑞、`000938` 紫光股份），逐一调用上述 akshare 函数，确认：
- 接口可调通且返回非空
- 字段名/列名与代码预期一致
- 限速要求（避免被封）

若某项接口不可用或变更，记录到 `data_collector.py` 的 fallback 逻辑中（返回 `NaN`，在 CSV 中标注缺失）。

### 5. 修改 `scripts/a_share_selector/__init__.py` 导出

当前仅导出 `select`，需额外导出 `collect_all`（或按需调整）。

### 6. 修改 `scripts/run_daily_job.sh` 调用链

更新为：
```
prepare_stocks.py --source $SOURCE     # Step 1: 生成 stocks.txt
collect_and_filter.py                  # Step 2: 采集+筛选 → CSV
# (未来) 量化模块读取 CSV            # Step 3: 未来量化模块
```

### 7. 代码精简/删除 规划

| 文件 | 处理方式 | 原因 |
|---|---|---|
| `quant_model.py` 中的 `select()` | **重构** — 剥离筛选逻辑移入 `collect_and_filter.py`，函数体改为读取 CSV 后做量化打分（Step 3 实现） | 原函数混杂了数据获取+筛选+打分+技术分析，不符合新两步分离设计 |
| `quant_model.py` 中的 `fetch_tech_metrics()` | **移入** `data_collector.py` | 技术指标属于"数据采集"层 |
| `quant_model.py` 中的 `calc_macd()`, `calc_kdj()`, `ema()`, `percentile_ranks()` | **删除** | 后续量化仅基于 CSV 数据做投资推荐，不再需要这些技术指标计算函数 |
| `quant_model.py` 中的 `score_policy()`, `infer_sector()` | **保留** | 后续量化模块可复用 |
| `data_fetch.py` 中的 `fetch_snapshot()` | **保留但标记为 legacy** | 全市场扫描模式在新流程中不再使用，但不删除以兼容旧流程 |
| `data_fetch.py` 中的 `fetch_snapshot_by_codes()` | **保留** | 新流程仍需要 |
| `data_fetch.py` 中的 K 线三源函数 | **保留** | 仍需用于计算近 5 日收益率 |
| `data_fetch.py` 中的 `code_to_secid()` 与 `_code_to_eastmoney_secid()` | **合并**为一个 | 功能完全重复 |
| `select_a_shares.py` | **暂保留**，标注为 legacy，删除复盘相关函数 | 现有的一体化选股+DB 入库+日报生成在新流程中被替代，但可保留用于对比验证 |
| **`evaluate_signals.py`** | **删除** | 复盘逻辑不再需要，数据库仅供用户查看历史记录 |
| **`tests/test_change_summary.py`** | **删除** | 测试的是 `build_change_summary()`，属于复盘相关逻辑，随之移除 |
| `select_a_shares.py` 中的 `build_change_summary()` | **删除** | 复盘对比功能不再需要 |
| `select_a_shares.py` 中的 `fetch_previous_day_candidates()` | **删除** | 仅被 `build_change_summary()` 使用，随之移除 |
| `send_invest_email.py` | **保留不动** | 邮件发送与数据层无关 |

### 8. 新增目录结构

```
smart-invest/
├── data/                         # 运行时数据（.gitignore）
│   ├── candidates_YYYYMMDD.csv   # 新增 CSV 输出
│   └── smart_invest.db           # 保留，仅供用户查看历史
├── stocks/
│   └── stocks.txt                # prepare_stocks.py 产出
├── scripts/
│   ├── prepare_stocks.py         # Step 1
│   ├── collect_and_filter.py     # Step 2 (新建)
│   ├── a_share_selector/
│   │   ├── data_fetch.py         # 行情快照 + K线 (保留)
│   │   ├── data_collector.py     # 9 维数据采集 (新建)
│   │   ├── quant_model.py        # 仅保留 score_policy/infer_sector (精简)
│   │   └── __init__.py           # 更新导出
│   ├── select_a_shares.py        # legacy (暂保留，删除复盘相关函数)
│   └── send_invest_email.py      # 保留
├── tests/                        # 清空旧测试，后续按需新增
└── requirements.txt              # 新建
```

已删除文件：
- `scripts/evaluate_signals.py`
- `tests/test_change_summary.py`

---

**Verification**

1. **数据源验证**：先对 2–3 只测试股票手动调用每个 akshare 函数，打印返回值确认字段正确
2. **端到端测试**：`python3 scripts/prepare_stocks.py --source user_stocks` → `python3 scripts/collect_and_filter.py` → 检查 `data/candidates_YYYYMMDD.csv` 内容完整性
3. **初筛验证**：确认 CSV 中不含 300xxx/688xxx 代码、市值 < 100 亿、PE > 200 的记录
4. **数据完整度检查**：统计 CSV 各列的非空率，对缺失率高的字段排查数据源问题

---

**Decisions**
- 数据源：使用 akshare 作为 ROE/净利润增长率/两融/资金流向/股东户数/主力持仓的统一获取层
- 002 股票：保留（已并入深交所主板）
- 市值门槛：100 亿元人民币
- `select_a_shares.py`：暂保留为 legacy，删除其中复盘相关函数（`build_change_summary`、`fetch_previous_day_candidates`）
- **`evaluate_signals.py` + `test_change_summary.py`：直接删除，不再做复盘**
- **`quant_model.py` 中的 `calc_macd/calc_kdj/ema/percentile_ranks`：直接删除，后续量化仅基于 CSV 数据**
- **数据库保留仅供用户查看历史，不做复盘分析**
- CSV 直接放到 `data/` 目录下，命名含日期后缀
