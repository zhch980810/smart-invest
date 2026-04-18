#!/usr/bin/env python3
import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data/smart_invest.db'
DEFAULT_OUT_DIR = ROOT / 'reports'
TZ = ZoneInfo('Asia/Shanghai')


def _safe_mean(values: List[float]) -> Optional[float]:
    return mean(values) if values else None


def _ratio_positive(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(1 for v in values if v > 0) / len(values)


def _fetch_trade_dates(conn: sqlite3.Connection, days: int) -> List[str]:
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT DISTINCT dc.trade_date
        FROM daily_candidates dc
        JOIN run_logs rl ON rl.run_id = dc.run_id
        WHERE rl.status = 'success'
        ORDER BY dc.trade_date DESC
        LIMIT ?
        ''',
        (days,),
    )
    rows = [r[0] for r in cur.fetchall()]
    return list(reversed(rows))


def _fetch_candidates(conn: sqlite3.Connection, trade_dates: List[str]) -> List[Dict]:
    if not trade_dates:
        return []

    cur = conn.cursor()
    latest_run_by_date = {}
    for d in trade_dates:
        cur.execute(
            '''
            SELECT run_id
            FROM run_logs
            WHERE run_date = ? AND status = 'success'
            ORDER BY finished_at DESC
            LIMIT 1
            ''',
            (d,),
        )
        row = cur.fetchone()
        if row:
            latest_run_by_date[d] = row[0]

    rows: List[Dict] = []
    for d, run_id in latest_run_by_date.items():
        cur.execute(
            '''
            SELECT trade_date, rank_no, code, name, price, pct_chg, total_score
            FROM daily_candidates
            WHERE run_id = ?
            ORDER BY rank_no ASC
            ''',
            (run_id,),
        )
        for r in cur.fetchall():
            rows.append(
                {
                    'trade_date': r[0],
                    'rank_no': int(r[1]),
                    'code': r[2],
                    'name': r[3],
                    'price': float(r[4] or 0.0),
                    'pct_chg': float(r[5] or 0.0),
                    'total_score': float(r[6] or 0.0),
                }
            )
    rows.sort(key=lambda x: (x['trade_date'], x['rank_no']))
    return rows


def evaluate(days: int) -> Dict:
    if not DB_PATH.exists():
        raise FileNotFoundError(f'数据库不存在: {DB_PATH}')

    conn = sqlite3.connect(DB_PATH)
    try:
        trade_dates = _fetch_trade_dates(conn, days)
        rows = _fetch_candidates(conn, trade_dates)
    finally:
        conn.close()

    by_date_code = {(r['trade_date'], r['code']): r for r in rows}
    ordered_dates = sorted({r['trade_date'] for r in rows})
    date_to_idx = {d: i for i, d in enumerate(ordered_dates)}

    next1_returns: List[float] = []
    next5_returns: List[float] = []
    same_day_proxy_pct_chg: List[float] = []

    for r in rows:
        same_day_proxy_pct_chg.append(r['pct_chg'] / 100.0)
        i = date_to_idx.get(r['trade_date'])
        if i is None or r['price'] <= 0:
            continue

        if i + 1 < len(ordered_dates):
            d1 = ordered_dates[i + 1]
            nxt = by_date_code.get((d1, r['code']))
            if nxt and nxt['price'] > 0:
                next1_returns.append(nxt['price'] / r['price'] - 1.0)

        if i + 5 < len(ordered_dates):
            d5 = ordered_dates[i + 5]
            nxt5 = by_date_code.get((d5, r['code']))
            if nxt5 and nxt5['price'] > 0:
                next5_returns.append(nxt5['price'] / r['price'] - 1.0)

    result = {
        'generated_at': datetime.now(TZ).isoformat(),
        'window_days_requested': days,
        'window_trade_dates': ordered_dates,
        'sample_count': len(rows),
        'date_count': len(ordered_dates),
        'metrics': {
            'next_day_return_mean': _safe_mean(next1_returns),
            'next_day_up_ratio': _ratio_positive(next1_returns),
            'next_day_coverage': len(next1_returns),
            'five_day_return_mean': _safe_mean(next5_returns),
            'five_day_up_ratio': _ratio_positive(next5_returns),
            'five_day_coverage': len(next5_returns),
            'same_day_pct_chg_mean_proxy': _safe_mean(same_day_proxy_pct_chg),
            'same_day_up_ratio_proxy': _ratio_positive(same_day_proxy_pct_chg),
            'same_day_proxy_coverage': len(same_day_proxy_pct_chg),
            'avg_total_score': _safe_mean([r['total_score'] for r in rows]),
        },
        'notes': [
            'next_day/five_day 基于 daily_candidates 的跨日同代码价格配对，覆盖率受连续入选影响。',
            '当跨日配对不足时，请参考 same_day_*_proxy 指标作为可得替代。',
        ],
    }
    return result


def render_text(result: Dict) -> str:
    m = result['metrics']

    def pct(v: Optional[float]) -> str:
        return 'N/A' if v is None else f'{v * 100:.2f}%'

    lines = [
        'A股策略信号复盘（最小闭环）',
        f"生成时间: {result['generated_at']}",
        f"评估窗口(请求): 最近 {result['window_days_requested']} 天",
        f"覆盖交易日: {len(result['window_trade_dates'])} 天",
        f"样本数: {result['sample_count']}",
        '',
        '[核心指标]',
        f"次日收益均值: {pct(m['next_day_return_mean'])} (coverage={m['next_day_coverage']})",
        f"次日上涨比例: {pct(m['next_day_up_ratio'])}",
        f"5日收益均值: {pct(m['five_day_return_mean'])} (coverage={m['five_day_coverage']})",
        f"5日上涨比例: {pct(m['five_day_up_ratio'])}",
        '',
        '[可得替代指标]',
        f"当日涨跌幅均值(代理): {pct(m['same_day_pct_chg_mean_proxy'])} (coverage={m['same_day_proxy_coverage']})",
        f"当日上涨比例(代理): {pct(m['same_day_up_ratio_proxy'])}",
        f"平均综合评分: {m['avg_total_score']:.4f}" if m['avg_total_score'] is not None else '平均综合评分: N/A',
        '',
        '[说明]',
    ]
    lines.extend([f'- {x}' for x in result.get('notes', [])])
    return '\n'.join(lines)


def render_markdown(result: Dict) -> str:
    m = result['metrics']

    def pct(v: Optional[float]) -> str:
        return 'N/A' if v is None else f'{v * 100:.2f}%'

    return '\n'.join(
        [
            '# A股策略信号复盘（最小闭环）',
            '',
            f"- 生成时间：`{result['generated_at']}`",
            f"- 评估窗口（请求）：最近 **{result['window_days_requested']}** 天",
            f"- 覆盖交易日：**{len(result['window_trade_dates'])}** 天",
            f"- 样本数：**{result['sample_count']}**",
            '',
            '## 核心指标',
            '',
            '| 指标 | 数值 | 备注 |',
            '|---|---:|---|',
            f"| 次日收益均值 | {pct(m['next_day_return_mean'])} | coverage={m['next_day_coverage']} |",
            f"| 次日上涨比例 | {pct(m['next_day_up_ratio'])} | 仅统计有次日配对样本 |",
            f"| 5日收益均值 | {pct(m['five_day_return_mean'])} | coverage={m['five_day_coverage']} |",
            f"| 5日上涨比例 | {pct(m['five_day_up_ratio'])} | 仅统计有5日配对样本 |",
            '',
            '## 可得替代指标',
            '',
            '| 指标 | 数值 | 备注 |',
            '|---|---:|---|',
            f"| 当日涨跌幅均值（代理） | {pct(m['same_day_pct_chg_mean_proxy'])} | coverage={m['same_day_proxy_coverage']} |",
            f"| 当日上涨比例（代理） | {pct(m['same_day_up_ratio_proxy'])} | 数据不足时兜底 |",
            f"| 平均综合评分 | {('N/A' if m['avg_total_score'] is None else format(m['avg_total_score'], '.4f'))} | daily_candidates.total_score |",
            '',
            '## 说明',
            '',
            *[f'- {x}' for x in result.get('notes', [])],
            '',
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=20, help='评估最近N个有成功记录的交易日')
    ap.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR, help='输出目录')
    args = ap.parse_args()

    result = evaluate(days=args.days)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    d = datetime.now(TZ).strftime('%Y%m%d')

    json_path = out_dir / f'evaluation_{d}.json'
    txt_path = out_dir / f'evaluation_{d}.txt'
    md_path = out_dir / f'evaluation_{d}.md'

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(render_text(result))
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(render_markdown(result))

    print(f'EVAL_JSON: {json_path}')
    print(f'EVAL_TXT: {txt_path}')
    print(f'EVAL_MD: {md_path}')
    print(f"Samples: {result['sample_count']}, Dates: {result['date_count']}")


if __name__ == '__main__':
    main()
