#!/usr/bin/env python3
import argparse
import os
import re
import ssl
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENV_PATH = os.path.join(ROOT, ".secrets", "mail_163.env")
LEGACY_ENV_PATH = "/home/clawbot/.openclaw/workspace/.secrets/mail_163.env"
ENV_PATH = os.environ.get("MAIL_ENV_PATH", DEFAULT_ENV_PATH if os.path.exists(DEFAULT_ENV_PATH) else LEGACY_ENV_PATH)


def load_env(path: str):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def detect_quality_issues(body: str):
    """
    仅按“数据源双失效”规则拦截发送：
    - 当正文出现【数据源告警】且包含“全部失效”时，拦截群发并仅告警发件人邮箱。
    - 其余质量波动（如个别指标未知、新闻为空）不在此处拦截，避免误报。
    """
    issues = []

    m = re.search(r"【数据源告警】(.+)", body)
    if m:
        alert_text = m.group(1).strip()
        if "全部失效" in alert_text:
            issues.append(f"数据源告警：{alert_text}")

    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alert-only", action="store_true", help="仅告警发件人邮箱，不发送订阅群发")
    args = ap.parse_args()

    body = os.environ.get("MAIL_BODY", "").strip()
    if not body:
        print("MAIL_BODY is empty", flush=True)
        raise SystemExit(2)

    env = load_env(ENV_PATH)
    host = env.get("SMTP_HOST", "smtp.163.com")
    port = int(env.get("SMTP_PORT", "465"))
    user = env["SMTP_USER"]
    password = env["SMTP_PASS"]
    to_raw = env.get("MAIL_TO", user)
    recipients = [x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()]
    if not recipients:
        recipients = [user]

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    subject = f"A股中线投资晨报 | {now:%Y-%m-%d}"

    issues = detect_quality_issues(body)
    if args.alert_only:
        subject = f"【告警】A股晨报任务异常 | {now:%Y-%m-%d}"
        recipients = [user]
    elif issues:
        subject = f"【发送中止】A股晨报数据异常 | {now:%Y-%m-%d}"
        recipients = [user]
        body = (
            "本次晨报未发送给订阅邮箱，原因如下：\n"
            + "\n".join([f"- {x}" for x in issues])
            + "\n\n请先排查数据源或脚本，再重试发送。"
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
        server.login(user, password)
        server.sendmail(user, recipients, msg.as_string())

    if args.alert_only:
        print(f"alert-only mode; sent to sender mailbox: {', '.join(recipients)}")
    elif issues:
        print(f"blocked report send; alerted sender mailbox: {', '.join(recipients)} | issues: {'; '.join(issues)}")
    else:
        print(f"sent to {', '.join(recipients)}")


if __name__ == "__main__":
    main()
