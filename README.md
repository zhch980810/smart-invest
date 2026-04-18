# 智慧投资仓库（smart-invest）

当前包含：
- `scripts/select_a_shares.py`：A股“政策+量化”长期投资选股主入口（加载策略、筛选、输出日报）
- `scripts/evaluate_signals.py`：复盘评估脚本（最近N天样本、次日/5日收益、上涨比例、代理指标）
- `scripts/a_share_selector/data_fetch.py`：数据获取模块（快照、K线，多源自动切换）
- `scripts/a_share_selector/quant_model.py`：量化/预测模块（筛选、打分、技术指标、板块分散）
- `scripts/send_invest_email.py`：发送投资日报邮件（关键数据源异常时可中止群发并仅告警发件人）
- `research/policy_signals.json`：政策主题配置
- `research/README.md`：策略与使用说明

---

## 从 0 到“每日运行 + 复盘”完整流程

### 1) 初始化环境

```bash
cd smart-invest
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip requests pytest
```

### 2) 配置邮件发送（可选）

复制并填写：`.secrets/mail_163.env.example` -> `.secrets/mail_163.env`

```env
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USER=your_email@163.com
SMTP_PASS=your_smtp_auth_code
MAIL_TO=recipient1@example.com,recipient2@example.com
```

### 3) 每日选股主流程（生成候选 + 入库）

```bash
python3 scripts/select_a_shares.py --top 10 --max-api-calls 50
```

输出：
- `research/a_share_policy_quant/output/top10_YYYYMMDD.json`
- `research/a_share_policy_quant/output/top10_YYYYMMDD.txt`
- `research/a_share_policy_quant/output/changes_YYYYMMDD.json`
- `data/smart_invest.db`（`run_logs` + `daily_candidates`）

### 4) 发送日报邮件（可选）

```bash
MAIL_BODY="$(cat research/a_share_policy_quant/output/top10_YYYYMMDD.txt)" python3 scripts/send_invest_email.py
# 告警模式（仅发件人，不群发）
MAIL_BODY="任务失败，请检查日志" python3 scripts/send_invest_email.py --alert-only
```

### 5) 复盘评估（最小闭环）

```bash
python3 scripts/evaluate_signals.py --days 20
```

输出到 `reports/`：
- `evaluation_YYYYMMDD.json`（结构化指标）
- `evaluation_YYYYMMDD.txt`（命令行可读摘要）
- `evaluation_YYYYMMDD.md`（可视化入口：Markdown报告）

> 说明：`次日/5日收益`基于 `daily_candidates` 跨日同代码配对；若历史不够，会自动给出 `same_day_*_proxy` 代理指标，保证复盘可持续运行。

### 6) 最小测试/自检

```bash
pytest -q
python3 -m py_compile scripts/select_a_shares.py scripts/evaluate_signals.py
```

### 7) 自动调度（可选）

- Shell：`scripts/run_daily_job.sh`
- Cron示例：`deploy/cron.daily.example`
- Systemd示例：`deploy/smart-invest.service` + `deploy/smart-invest.timer`

---

## 里程碑（R1 / R2 / R3）

### R1（最小可运行）
- 新增 SQLite 入库：`run_logs`、`daily_candidates`
- 日报新增“今日 vs 昨日变化”摘要
- 新增结构化变化文件：`changes_YYYYMMDD.json`
- 新增每日调度样例和一键日跑脚本

### R2（稳态增强）
- 行情/K线多源自动切换与兜底
- 数据源异常告警信息纳入日报正文
- 邮件发送增加数据源双失效拦截（中止群发，仅告警）

### R3（收官：可复盘、可迭代）
- 新增 `scripts/evaluate_signals.py`，形成“跑数→入库→评估”闭环
- 新增 Markdown 评估报告输出（`reports/evaluation_*.md`）
- 新增最小单元测试（变化摘要关键路径）
- README 增补“从0到每日运行+复盘”全流程

---

## 快速命令清单

```bash
# 1) 选股主任务
python3 scripts/select_a_shares.py --top 10 --max-api-calls 50

# 2) 复盘评估
python3 scripts/evaluate_signals.py --days 20

# 3) 发送日报
MAIL_BODY="$(cat research/a_share_policy_quant/output/top10_YYYYMMDD.txt)" python3 scripts/send_invest_email.py
```

## 风险提示
仅供研究参考，不构成投资建议。
