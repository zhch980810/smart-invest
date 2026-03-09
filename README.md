# 智慧投资仓库（smart-invest）

当前包含：
- `scripts/select_a_shares.py`：A股“政策+量化”选股脚本（新浪免费接口，支持 API 调用上限）
- `scripts/send_invest_email.py`：发送投资日报邮件
- `research/a_share_policy_quant/policy_signals.json`：政策主题配置
- `research/a_share_policy_quant/README.md`：策略与使用说明

## 快速开始

```bash
python3 scripts/select_a_shares.py --top 10 --max-api-calls 50
MAIL_BODY="$(cat research/a_share_policy_quant/output/top10_YYYYMMDD.txt)" python3 scripts/send_invest_email.py
```

## 邮件环境变量

默认读取：`.secrets/mail_163.env`

建议格式：

```env
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USER=your_email@163.com
SMTP_PASS=your_smtp_auth_code
MAIL_TO=recipient1@example.com,recipient2@example.com
```
