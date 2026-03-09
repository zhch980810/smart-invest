#!/usr/bin/env python3
import argparse
import html
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / 'research/a_share_policy_quant/policy_signals.json'
OUT_DIR = ROOT / 'research/a_share_policy_quant/output'

SINA_QUOTE_URL = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
SINA_SEARCH_URL = 'https://search.sina.com.cn/'
TZ = ZoneInfo('Asia/Shanghai')


def request_with_retry(request_fn, retries=3, sleep_sec=1.2):
    last_err = None
    for _ in range(retries):
        try:
            return request_fn()
        except Exception as e:
            last_err = e
            time.sleep(sleep_sec)
    raise RuntimeError(f'请求失败: {last_err}')


def to_float(v, default=0.0) -> float:
    try:
        if v is None or v == '':
            return default
        return float(v)
    except Exception:
        return default


def fetch_snapshot(max_api_calls: int = 50, per_page: int = 100) -> Tuple[List[Dict], int]:
    """从新浪免费接口抓取A股快照（分页，限制总调用次数）。"""
    if max_api_calls <= 0:
        raise RuntimeError('max_api_calls 必须大于 0。')

    rows: List[Dict] = []
    api_calls_used = 0

    for page in range(1, max_api_calls + 1):
        def do_req():
            return requests.get(
                SINA_QUOTE_URL,
                params={
                    'page': str(page),
                    'num': str(per_page),
                    'sort': 'amount',
                    'asc': '0',
                    'node': 'hs_a',
                    'symbol': '',
                    '_s_r_a': 'init',
                },
                timeout=12,
            )

        resp = request_with_retry(do_req)
        api_calls_used += 1
        resp.raise_for_status()

        data = resp.json()
        if not data:
            break

        for v in data:
            code = str(v.get('code') or '').strip()
            name = str(v.get('name') or '').strip()
            if not code or not name:
                continue

            price = to_float(v.get('trade'))
            pct_chg = to_float(v.get('changepercent'))
            high = to_float(v.get('high'))
            low = to_float(v.get('low'))
            pre_close = to_float(v.get('settlement'))
            amplitude = ((high - low) / pre_close * 100.0) if pre_close > 0 else 0.0
            amount = to_float(v.get('amount'))  # 元

            rows.append({
                'code': code,
                'name': name,
                'price': price,
                'pct_chg': pct_chg,
                'amount': amount,
                'amplitude': amplitude,
                'turnover': to_float(v.get('turnoverratio')),
                'pe_ttm': to_float(v.get('per')),
                'market_cap': to_float(v.get('mktcap')) * 10000.0,  # 万元 -> 元
                'float_cap': to_float(v.get('nmc')) * 10000.0,
                'pb': to_float(v.get('pb')),
                'industry': '',
            })

    if not rows:
        raise RuntimeError('新浪接口返回为空，无法构建股票池。')

    return rows, api_calls_used


def fetch_policy_news_24h(max_items: int = 8) -> List[Dict]:
    """从新浪站内搜索抓取过去24小时政策相关资讯（轻量摘要）。"""
    now = datetime.now(TZ)
    since = now - timedelta(hours=24)
    keywords = ['A股 政策', '证监会', '央行 降准', '财政 政策 资本市场', '两会 资本市场']
    news: List[Dict] = []
    seen = set()

    for kw in keywords:
        if len(news) >= max_items * 2:
            break

        def do_req():
            return requests.get(
                SINA_SEARCH_URL,
                params={'q': kw, 'c': 'news', 'from': 'channel'},
                timeout=12,
            )

        try:
            resp = request_with_retry(do_req, retries=2, sleep_sec=0.8)
            resp.raise_for_status()
            text = resp.text
        except Exception:
            continue

        for m in re.finditer(r'<h2>(.*?)</h2>.*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', text, re.S):
            h2 = m.group(1)
            dt_raw = m.group(2)
            a = re.search(r'href="([^"]+)"[^>]*>(.*?)</a>', h2, re.S)
            if not a:
                continue
            url = a.group(1).strip()
            title = re.sub('<.*?>', '', a.group(2))
            title = html.unescape(title).strip()

            try:
                ts = datetime.strptime(dt_raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
            except Exception:
                continue

            if ts < since:
                continue
            key = (title, url)
            if key in seen:
                continue
            seen.add(key)
            news.append({'time': ts, 'title': title, 'url': url, 'source': 'sina-search'})

    news.sort(key=lambda x: x['time'], reverse=True)
    return news[:max_items]


def load_policy() -> Dict:
    with open(POLICY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def percentile_ranks(values: List[float], reverse=False) -> List[float]:
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: values[i], reverse=reverse)
    ranks = [0.0] * n
    for rank, i in enumerate(order):
        ranks[i] = rank / (n - 1) if n > 1 else 1.0
    return ranks


def score_policy(stock: Dict, policy: Dict) -> Dict:
    text = f"{stock.get('name','')} {stock.get('industry','')}"
    hit = []
    score = 0.0
    for t in policy.get('themes', []):
        kws = t.get('keywords', [])
        if any(k in text for k in kws):
            w = float(t.get('weight', 0.0))
            score += w
            hit.append((t.get('name', ''), w))
    max_sum = sum(float(t.get('weight', 0.0)) for t in policy.get('themes', [])) or 1.0
    return {'policy_score': min(score / max_sum, 1.0), 'policy_hits': hit}


def select(top_n=10, horizon_days=30, max_api_calls: int = 50):
    raw, api_calls_used = fetch_snapshot(max_api_calls=max_api_calls)
    policy = load_policy()

    stats = {
        'total_fetched': len(raw),
        'removed_st': 0,
        'removed_low_price': 0,
        'removed_low_amount': 0,
        'removed_small_cap': 0,
        'removed_bad_pe': 0,
        'removed_bad_pb': 0,
        'remaining': 0,
    }

    universe = []
    for s in raw:
        name = s['name']
        if 'ST' in name.upper() or name.startswith('*'):
            stats['removed_st'] += 1
            continue
        if s['price'] <= 2:
            stats['removed_low_price'] += 1
            continue
        if s['amount'] < 1e8:
            stats['removed_low_amount'] += 1
            continue
        if s['market_cap'] and s['market_cap'] < 2e10:
            stats['removed_small_cap'] += 1
            continue
        if not (0 < s['pe_ttm'] < 90):
            stats['removed_bad_pe'] += 1
            continue
        if not (0 < s['pb'] < 15):
            stats['removed_bad_pb'] += 1
            continue
        universe.append(s)

    stats['remaining'] = len(universe)

    if len(universe) < top_n:
        raise RuntimeError(f'可用股票数量不足: {len(universe)}（API调用={api_calls_used}）')

    pe = [s['pe_ttm'] for s in universe]
    pb = [s['pb'] for s in universe]
    amp = [s['amplitude'] for s in universe]
    amt = [s['amount'] for s in universe]
    pct = [s['pct_chg'] for s in universe]

    pe_rank = percentile_ranks(pe, reverse=False)
    pb_rank = percentile_ranks(pb, reverse=False)
    amp_rank = percentile_ranks(amp, reverse=False)
    amt_rank = percentile_ranks(amt, reverse=True)

    mom = [max(0.0, 1.0 - abs(x - 2.0) / 8.0) for x in pct]

    picks = []
    for i, s in enumerate(universe):
        p = score_policy(s, policy)
        value_score = 0.5 * pe_rank[i] + 0.5 * pb_rank[i]
        stability_score = amp_rank[i]
        momentum_score = mom[i]
        liquidity_score = amt_rank[i]

        quant_score = 0.42 * value_score + 0.28 * stability_score + 0.30 * momentum_score
        total = 0.55 * p['policy_score'] + 0.35 * quant_score + 0.10 * liquidity_score

        reasons = []
        if p['policy_hits']:
            reasons.append('政策匹配: ' + '、'.join([x[0] for x in p['policy_hits'][:2]]))
        reasons.append(f"估值因子较优(PE={s['pe_ttm']:.1f}, PB={s['pb']:.2f})")
        reasons.append(f"成交活跃(成交额≈{s['amount']/1e8:.1f}亿元)")
        reasons.append(f"短线温度适中(当日涨跌幅={s['pct_chg']:.2f}%)")

        picks.append({
            'code': s['code'],
            'name': s['name'],
            'industry': s['industry'],
            'price': s['price'],
            'pct_chg': s['pct_chg'],
            'pe_ttm': s['pe_ttm'],
            'pb': s['pb'],
            'amount': s['amount'],
            'policy_score': round(p['policy_score'], 4),
            'quant_score': round(quant_score, 4),
            'liquidity_score': round(liquidity_score, 4),
            'total_score': round(total, 4),
            'horizon_days': horizon_days,
            'reasons': reasons,
            'api_source': 'sina',
            'api_calls_used': api_calls_used,
        })

    picks.sort(key=lambda x: x['total_score'], reverse=True)
    policy_news = fetch_policy_news_24h(max_items=8)
    return picks[:top_n], policy, api_calls_used, stats, policy_news


def dump_outputs(picks: List[Dict], policy: Dict, api_calls_used: int, max_api_calls: int, stats: Dict, policy_news: List[Dict]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = datetime.now(TZ).strftime('%Y%m%d')
    js_path = OUT_DIR / f'top10_{d}.json'
    txt_path = OUT_DIR / f'top10_{d}.txt'

    payload = {
        'generated_at': datetime.now(TZ).isoformat(),
        'method': 'policy+quant-lite',
        'policy_as_of': policy.get('as_of'),
        'api_source': 'sina',
        'api_calls_used': api_calls_used,
        'max_api_calls': max_api_calls,
        'filter_stats': stats,
        'policy_news_24h': [
            {'time': x['time'].strftime('%Y-%m-%d %H:%M:%S'), 'title': x['title'], 'url': x['url']}
            for x in policy_news
        ],
        'top10': picks,
    }
    with open(js_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    today_cn = datetime.now(TZ).strftime('%Y年%m月%d日')

    lines = []
    lines.append(f"【过去24小时政策面消息汇总】（截至 {now_str}）")
    if policy_news:
        for i, n in enumerate(policy_news, 1):
            lines.append(f"{i}. [{n['time'].strftime('%m-%d %H:%M')}] {n['title']}")
            lines.append(f"   链接: {n['url']}")
    else:
        lines.append('过去24小时未抓取到可用的政策面资讯（可能受来源时效/网络影响）。')

    lines.append('')
    lines.append('【抓取与筛选过程】')
    lines.append(
        f"{today_cn} 共抓取 {stats['total_fetched']} 只A股快照样本，收集字段包括: 价格、涨跌幅、成交额、振幅、换手率、PE(TTM)、PB、总市值、流通市值。"
    )
    lines.append(f"数据源: 新浪免费接口 | API调用: {api_calls_used}/{max_api_calls}")
    lines.append(f"初筛去除 ST/*ST: {stats['removed_st']} 只")
    lines.append(f"初筛去除低价股(低于2元): {stats['removed_low_price']} 只")
    lines.append(f"初筛去除低成交额(低于1亿元): {stats['removed_low_amount']} 只")
    lines.append(f"初筛去除小市值(低于200亿元): {stats['removed_small_cap']} 只")
    lines.append(f"初筛去除异常PE(<=0或>=90): {stats['removed_bad_pe']} 只")
    lines.append(f"初筛去除异常PB(<=0或>=15): {stats['removed_bad_pb']} 只")
    lines.append(
        f"以下为初筛后剩余 {stats['remaining']} 只股票中，综合得分（55%政策分 + 35%量化分 + 10%流动性）最高的 {len(picks)} 只："
    )
    lines.append('')

    for i, s in enumerate(picks, 1):
        lines.append(
            f"{i}. {s['name']} ({s['code']}) | 综合分={s['total_score']:.4f} | 政策分={s['policy_score']:.4f} | 量化分={s['quant_score']:.4f} | 流动性分={s['liquidity_score']:.4f}"
        )
        lines.append(f"   推荐理由: {'；'.join(s['reasons'])}")

    lines.append('')
    lines.append('风险提示：仅供研究参考，不构成投资建议。')

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return js_path, txt_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--horizon', type=int, default=30)
    ap.add_argument('--max-api-calls', type=int, default=50)
    args = ap.parse_args()

    picks, policy, api_calls_used, stats, policy_news = select(
        top_n=args.top,
        horizon_days=args.horizon,
        max_api_calls=args.max_api_calls,
    )
    js_path, txt_path = dump_outputs(picks, policy, api_calls_used, args.max_api_calls, stats, policy_news)
    print(f'JSON: {js_path}')
    print(f'TEXT: {txt_path}')
    print(f'API calls: {api_calls_used}/{args.max_api_calls}')
    print(f'Fetched: {stats["total_fetched"]}, Remaining: {stats["remaining"]}, PolicyNews24h: {len(policy_news)}')


if __name__ == '__main__':
    main()
