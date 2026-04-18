#!/usr/bin/env python3
import argparse
import json
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from zoneinfo import ZoneInfo

from a_share_selector.quant_model import select

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / 'research/a_share_policy_quant/policy_signals.json'
OUT_DIR = ROOT / 'research/a_share_policy_quant/output'
DATA_DIR = ROOT / 'data'
DB_PATH = DATA_DIR / 'smart_invest.db'
TZ = ZoneInfo('Asia/Shanghai')


def load_policy() -> Dict:
    with open(POLICY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS run_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                run_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                top_n INTEGER,
                max_api_calls INTEGER,
                api_calls_used INTEGER,
                json_path TEXT,
                txt_path TEXT,
                changes_path TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS daily_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                rank_no INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                sector TEXT,
                total_score REAL,
                policy_score REAL,
                quant_score REAL,
                liquidity_score REAL,
                tech_score REAL,
                price REAL,
                pct_chg REAL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, code)
            )
            '''
        )
        cur.execute('CREATE INDEX IF NOT EXISTS idx_daily_candidates_date_rank ON daily_candidates(trade_date, rank_no)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_daily_candidates_code ON daily_candidates(code)')

        cur.execute("PRAGMA table_info(run_logs)")
        run_log_columns = {r[1] for r in cur.fetchall()}
        if 'changes_path' not in run_log_columns:
            cur.execute('ALTER TABLE run_logs ADD COLUMN changes_path TEXT')

        conn.commit()
    finally:
        conn.close()


def fetch_previous_day_candidates(today_yyyymmdd: str) -> Tuple[Optional[str], List[Dict]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT MAX(dc.trade_date) AS prev_date
            FROM daily_candidates dc
            JOIN run_logs rl ON rl.run_id = dc.run_id
            WHERE dc.trade_date < ? AND rl.status = 'success'
            ''',
            (today_yyyymmdd,),
        )
        row = cur.fetchone()
        prev_date = row['prev_date'] if row and row['prev_date'] else None
        if not prev_date:
            return None, []

        cur.execute(
            '''
            SELECT rl.run_id
            FROM run_logs rl
            WHERE rl.run_date = ? AND rl.status = 'success'
            ORDER BY rl.finished_at DESC
            LIMIT 1
            ''',
            (prev_date,),
        )
        run_row = cur.fetchone()
        if not run_row:
            return prev_date, []

        cur.execute(
            '''
            SELECT dc.rank_no, dc.code, dc.name, dc.total_score
            FROM daily_candidates dc
            WHERE dc.run_id = ?
            ORDER BY dc.rank_no ASC
            ''',
            (run_row['run_id'],),
        )
        rows = cur.fetchall()
        return prev_date, [dict(r) for r in rows]
    finally:
        conn.close()


def build_change_summary(
    picks: List[Dict], prev_date: Optional[str], prev_rows: List[Dict], rank_top_n: int = 10
) -> Tuple[List[str], Dict]:
    lines: List[str] = ['【今日 vs 昨日变化】']
    summary = {
        'baseline_date': prev_date,
        'has_baseline': bool(prev_date and prev_rows),
        'added': [],
        'removed': [],
        'rank_changes': [],
    }
    if not prev_date or not prev_rows:
        lines.append('昨日无可用成功记录，暂无对比。')
        lines.append('')
        return lines, summary

    curr_rank = {x['code']: i for i, x in enumerate(picks, 1)}
    prev_rank = {x['code']: int(x['rank_no']) for x in prev_rows}
    code_to_name = {x['code']: x['name'] for x in picks}
    for x in prev_rows:
        code_to_name.setdefault(x['code'], x['name'])

    curr_codes = set(curr_rank.keys())
    prev_codes = set(prev_rank.keys())

    added = sorted(curr_codes - prev_codes, key=lambda c: curr_rank[c])
    removed = sorted(prev_codes - curr_codes, key=lambda c: prev_rank[c])

    summary['added'] = [{'code': c, 'name': code_to_name[c], 'rank': curr_rank[c]} for c in added]
    summary['removed'] = [{'code': c, 'name': code_to_name[c], 'prev_rank': prev_rank[c]} for c in removed]

    lines.append(f'对比基准: {prev_date}')
    lines.append('新增标的: ' + ('、'.join([f"{code_to_name[c]}({c})" for c in added]) if added else '无'))
    lines.append('移除标的: ' + ('、'.join([f"{code_to_name[c]}({c})" for c in removed]) if removed else '无'))

    changed = []
    for c in curr_codes & prev_codes:
        delta = prev_rank[c] - curr_rank[c]  # 正值=名次上升
        if delta != 0:
            changed.append((abs(delta), delta, c))
    changed.sort(reverse=True)

    lines.append(f'排名变化(Top {rank_top_n}):')
    if not changed:
        lines.append('  无明显排名变化')
    else:
        for _, delta, c in changed[:rank_top_n]:
            direction = '↑' if delta > 0 else '↓'
            lines.append(f"  {code_to_name[c]}({c}): {prev_rank[c]} -> {curr_rank[c]} ({direction}{abs(delta)})")
            summary['rank_changes'].append(
                {
                    'code': c,
                    'name': code_to_name[c],
                    'prev_rank': prev_rank[c],
                    'curr_rank': curr_rank[c],
                    'delta': delta,
                }
            )

    lines.append('')
    return lines, summary


def persist_to_db(
    run_id: str,
    trade_date: str,
    started_at: str,
    finished_at: str,
    status: str,
    top_n: int,
    max_api_calls: int,
    api_calls_used: int = 0,
    json_path: str = '',
    txt_path: str = '',
    changes_path: str = '',
    error_message: str = '',
    picks: Optional[List[Dict]] = None,
):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            INSERT INTO run_logs (
                run_id, run_date, started_at, finished_at, status,
                top_n, max_api_calls, api_calls_used, json_path, txt_path,
                changes_path, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                run_id,
                trade_date,
                started_at,
                finished_at,
                status,
                top_n,
                max_api_calls,
                api_calls_used,
                json_path,
                txt_path,
                changes_path,
                error_message,
                finished_at,
            ),
        )

        if status == 'success' and picks:
            rows = []
            for i, s in enumerate(picks, 1):
                rows.append(
                    (
                        run_id,
                        trade_date,
                        i,
                        s['code'],
                        s['name'],
                        s.get('sector', ''),
                        s.get('total_score', 0.0),
                        s.get('policy_score', 0.0),
                        s.get('quant_score', 0.0),
                        s.get('liquidity_score', 0.0),
                        s.get('tech_score', 0.0),
                        s.get('price', 0.0),
                        s.get('pct_chg', 0.0),
                        finished_at,
                    )
                )
            cur.executemany(
                '''
                INSERT INTO daily_candidates (
                    run_id, trade_date, rank_no, code, name, sector,
                    total_score, policy_score, quant_score, liquidity_score, tech_score,
                    price, pct_chg, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                rows,
            )

        conn.commit()
    finally:
        conn.close()


def dump_outputs(
    picks: List[Dict],
    policy: Dict,
    api_calls_used: int,
    max_api_calls: int,
    stats: Dict,
    source_status: Dict,
    sector_cap: int,
    change_summary_lines: List[str],
    change_summary_json: Dict,
):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = datetime.now(TZ).strftime('%Y%m%d')
    js_path = OUT_DIR / f'top10_{d}.json'
    txt_path = OUT_DIR / f'top10_{d}.txt'
    changes_path = OUT_DIR / f'changes_{d}.json'

    payload = {
        'generated_at': datetime.now(TZ).isoformat(),
        'method': 'policy+quant+tech-v3',
        'policy_as_of': policy.get('as_of'),
        'api_source': 'snapshot:sina, kline:auto',
        'api_calls_used': api_calls_used,
        'max_api_calls': max_api_calls,
        'sector_cap': sector_cap,
        'filter_stats': stats,
        'source_status': source_status,
        'top10': picks,
    }
    with open(js_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    changes_payload = {
        'generated_at': datetime.now(TZ).isoformat(),
        'trade_date': d,
        'summary': change_summary_json,
    }
    with open(changes_path, 'w', encoding='utf-8') as f:
        json.dump(changes_payload, f, ensure_ascii=False, indent=2)

    now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    today_cn = datetime.now(TZ).strftime('%Y年%m月%d日')

    lines = []
    lines.append('【数据源状态】')
    lines.append(
        f"K线主源/备源/兜底: {source_status['kline']['primary']} / {source_status['kline']['backup']} / {source_status['kline'].get('fallback', 'none')}"
    )
    lines.append(f"K线统计: {json.dumps(source_status['kline']['stats'], ensure_ascii=False)}")
    if source_status.get('alerts'):
        lines.append('【数据源告警】' + '；'.join(source_status['alerts']))
    lines.append('')

    lines.extend(change_summary_lines)

    lines.append('')
    lines.append('【抓取与筛选过程（宽松版）】')
    lines.append(
        f"{today_cn} 共抓取 {stats['total_fetched']} 只A股快照样本，字段包括: 价格、涨跌幅、成交额、振幅、换手率、PE(TTM)、PB、总市值。"
    )
    lines.append('数据源: 新浪(快照) + 东财/腾讯/新浪(K线自动切换)')
    lines.append(f'快照API调用: {api_calls_used}/{max_api_calls}')
    lines.append('筛选阈值: 价格>1.5元, 成交额>0.3亿元, 市值>10亿元, 0<PE<240, 0<PB<20')
    lines.append(f"去除 ST/*ST: {stats['removed_st']} 只")
    lines.append(f"去除低价股: {stats['removed_low_price']} 只")
    lines.append(f"去除低成交额: {stats['removed_low_amount']} 只")
    lines.append(f"去除小市值: {stats['removed_small_cap']} 只")
    lines.append(f"去除异常PE: {stats['removed_bad_pe']} 只")
    lines.append(f"去除异常PB: {stats['removed_bad_pb']} 只")
    lines.append(f"剩余股票: {stats['remaining']} 只 | 板块分散约束: 同一板块最多 {sector_cap} 只")
    lines.append('综合评分权重: 政策15% + 量化35% + 流动性35% + 技术面15%')
    lines.append('')

    for i, s in enumerate(picks, 1):
        lines.append(
            f"{i}. {s['name']} ({s['code']}) [{s['sector']}] | 综合分={s['total_score']:.4f} | 政策={s['policy_score']:.4f} | 量化={s['quant_score']:.4f} | 技术={s['tech_score']:.4f}"
        )
        lines.append(f"   推荐理由: {'；'.join(s['reasons'])}")

    lines.append('')
    lines.append('风险提示：仅供研究参考，不构成投资建议。')

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return js_path, txt_path, changes_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--horizon', type=int, default=30)
    ap.add_argument('--max-api-calls', type=int, default=50)
    ap.add_argument('--sector-cap', type=int, default=4)
    args = ap.parse_args()

    init_db()

    run_id = str(uuid4())
    started_at = datetime.now(TZ).isoformat()
    trade_date = datetime.now(TZ).strftime('%Y%m%d')

    try:
        policy = load_policy()
        prev_date, prev_rows = fetch_previous_day_candidates(trade_date)

        picks, api_calls_used, stats, source_status = select(
            policy=policy,
            top_n=args.top,
            horizon_days=args.horizon,
            max_api_calls=args.max_api_calls,
            sector_cap=args.sector_cap,
        )
        change_summary_lines, change_summary_json = build_change_summary(
            picks, prev_date, prev_rows, rank_top_n=min(args.top, 10)
        )

        js_path, txt_path, changes_path = dump_outputs(
            picks,
            policy,
            api_calls_used,
            args.max_api_calls,
            stats,
            source_status,
            args.sector_cap,
            change_summary_lines,
            change_summary_json,
        )

        finished_at = datetime.now(TZ).isoformat()
        persist_to_db(
            run_id=run_id,
            trade_date=trade_date,
            started_at=started_at,
            finished_at=finished_at,
            status='success',
            top_n=args.top,
            max_api_calls=args.max_api_calls,
            api_calls_used=api_calls_used,
            json_path=str(js_path),
            txt_path=str(txt_path),
            changes_path=str(changes_path),
            picks=picks,
        )

        print(f'RunID: {run_id}')
        print(f'DB: {DB_PATH}')
        print(f'JSON: {js_path}')
        print(f'TEXT: {txt_path}')
        print(f'CHANGES: {changes_path}')
        print(f'API calls(snapshot): {api_calls_used}/{args.max_api_calls}')
        print(f'Fetched: {stats["total_fetched"]}, Remaining: {stats["remaining"]}')
    except Exception as e:
        finished_at = datetime.now(TZ).isoformat()
        err = f'{e}\n{traceback.format_exc()}'
        persist_to_db(
            run_id=run_id,
            trade_date=trade_date,
            started_at=started_at,
            finished_at=finished_at,
            status='failed',
            top_n=args.top,
            max_api_calls=args.max_api_calls,
            error_message=err,
        )
        print(f'RunID: {run_id}')
        print(f'DB: {DB_PATH}')
        raise


if __name__ == '__main__':
    main()
