#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/research/a_share_policy_quant/output"
LOG_DIR="$ROOT/logs"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-14}"
mkdir -p "$LOG_DIR"

cd "$ROOT"

TS="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/daily_job_${TS}.log"

cleanup_logs() {
  find "$LOG_DIR" -type f -name 'daily_job_*.log' -mtime "+${LOG_RETENTION_DAYS}" -print -delete || true
}

{
  echo "[$(date '+%F %T')] start daily job"
  python3 scripts/select_a_shares.py --top 10 --max-api-calls 50

  LATEST_TXT="$(find "$OUT_DIR" -maxdepth 1 -type f -name 'top10_*.txt' | sort | tail -n 1)"
  if [[ -z "${LATEST_TXT:-}" || ! -f "$LATEST_TXT" ]]; then
    echo "no report txt found" >&2
    exit 21
  fi

  MAIL_BODY="$(cat "$LATEST_TXT")" python3 scripts/send_invest_email.py
  echo "[$(date '+%F %T')] daily job done"
} >>"$LOG_FILE" 2>&1 || {
  echo "[$(date '+%F %T')] daily job failed, trigger alert path" >>"$LOG_FILE"
  ALERT_BODY="任务执行失败（请检查日志）\n日志: $LOG_FILE"
  MAIL_BODY="$ALERT_BODY" python3 scripts/send_invest_email.py --alert-only >>"$LOG_FILE" 2>&1 || true
  cleanup_logs
  exit 1
}

cleanup_logs
