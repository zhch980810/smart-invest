#!/usr/bin/env python3
import os
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


def main():
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

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
        server.login(user, password)
        server.sendmail(user, recipients, msg.as_string())

    print(f"sent to {', '.join(recipients)}")


if __name__ == "__main__":
    main()
