#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT/data"
LOG_DIR="$ROOT/logs"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"
mkdir -p "$LOG_DIR"

cd "$ROOT"

# 股票池输入源: user_interest (按板块关键词) 或 user_stocks (指定清单)
SOURCE="${1:-user_stocks}"

TS="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/daily_job_${TS}.log"

cleanup_logs() {
  find "$LOG_DIR" -type f -name 'daily_job_*.log' -mtime "+${LOG_RETENTION_DAYS}" -print -delete || true
}

{
  echo "[$(date '+%F %T')] start daily job (source=$SOURCE)"

  # 第 1 步: 准备目标股票池 -> stocks/stocks.txt
  echo "[$(date '+%F %T')] prepare stocks (source=$SOURCE)"
  python3 scripts/prepare_stocks.py --source "$SOURCE"

  # 第 2 步: 数据采集 + 初筛 → CSV
  echo "[$(date '+%F %T')] collect and filter → CSV"
  python3 scripts/collect_and_filter.py

  # (未来) 第 3 步: 量化模块读取 CSV 做投资推荐

  LATEST_CSV="$(find "$DATA_DIR" -maxdepth 1 -type f -name 'candidates_*.csv' | sort | tail -n 1)"
  if [[ -z "${LATEST_CSV:-}" || ! -f "$LATEST_CSV" ]]; then
    echo "no candidates csv found" >&2
    exit 21
  fi

  # 以 CSV 摘要作为邮件正文
  MAIL_BODY="$(head -1 "$LATEST_CSV" && echo '---' && tail -n +2 "$LATEST_CSV" | head -30)" python3 scripts/send_invest_email.py
  echo "[$(date '+%F %T')] daily job done"
} >>"$LOG_FILE" 2>&1 || {
  echo "[$(date '+%F %T')] daily job failed, trigger alert path" >>"$LOG_FILE"
  ALERT_BODY="任务执行失败（请检查日志）\n日志: $LOG_FILE"
  MAIL_BODY="$ALERT_BODY" python3 scripts/send_invest_email.py --alert-only >>"$LOG_FILE" 2>&1 || true
  cleanup_logs
  exit 1
}

cleanup_logs
