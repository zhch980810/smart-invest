# A股“政策 + 量化”选股器

这是一个可学习、可修改的轻量选股程序（无第三方量化框架依赖），目标是从**政策支持强度**与**量化因子**两个维度，筛出未来30天值得重点跟踪的A股候选。

## 路径
- 主程序：`scripts/select_a_shares.py`
- 政策配置：`research/a_share_policy_quant/policy_signals.json`
- 输出目录：`research/a_share_policy_quant/output/`

## 设计思路（借鉴开源框架理念）
- 借鉴 `microsoft/qlib` 的“因子化评分 + 可解释输出”思路
- 借鉴 `backtrader` 的“策略参数显式化”思路
- 借鉴 `alphalens` 的“因子分层比较”思路（这里做了简化版）

> 说明：本实现是教学/研究版，不是回测引擎，也不保证收益。

## 数据源
- 行情快照：新浪免费接口（无需API Key）
- 政策信号：本地 `policy_signals.json`（你可按官方政策口径持续维护）

> 为控制免费接口频率，脚本内置 `--max-api-calls`（默认 50）。

## 如何运行
```bash
python3 scripts/select_a_shares.py --top 10 --horizon 30
```

## 输出
- `top10_YYYYMMDD.json`：结构化候选池
- `top10_YYYYMMDD.txt`：可直接贴入邮件的文本（含每只股票理由）

## 你可以怎么改
1. 调整 `policy_signals.json` 的政策主题权重（例如更偏重“新质生产力/电网投资/国产替代”）
2. 调整脚本里的因子权重（估值、动量、稳定性、流动性）
3. 增加排除规则（如剔除ST、剔除波动过高、剔除低成交额）
4. 接入你信任的官方数据源（统计局、证监会、交易所公告）

## 风险提示
仅供研究学习，不构成投资建议。
