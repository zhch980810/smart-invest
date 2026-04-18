from typing import Dict, List, Tuple

from .data_fetch import (
    fetch_kline_eastmoney,
    fetch_kline_sina,
    fetch_kline_tencent,
    fetch_snapshot,
)

SECTOR_NAME_RULES = [
    ('半导体', ['芯', '半导体', '集成电路']),
    ('电力设备', ['电力', '电网', '储能', '特高压', '变压器']),
    ('高端制造', ['激光', '机器人', '机床', '自动化', '精工', '液压']),
    ('能源', ['能源', '煤', '油', '气']),
    ('医药', ['药', '医疗', '生物']),
    ('消费', ['酒', '食品', '乳', '家电', '零售']),
    ('TMT', ['信息', '科技', '软件', '通信', '电子']),
]


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
    text = f"{stock.get('name', '')} {stock.get('industry', '')}"
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


def ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def calc_macd(closes: List[float]) -> Dict:
    if len(closes) < 30:
        return {'dif': 0.0, 'dea': 0.0, 'hist': 0.0, 'signal': '数据不足'}
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema(dif, 9)
    hist = [d - e for d, e in zip(dif, dea)]
    signal = '金叉' if dif[-1] > dea[-1] and dif[-2] <= dea[-2] else ('死叉' if dif[-1] < dea[-1] and dif[-2] >= dea[-2] else '延续')
    return {'dif': dif[-1], 'dea': dea[-1], 'hist': hist[-1], 'signal': signal}


def calc_kdj(closes: List[float], highs: List[float], lows: List[float], n: int = 9) -> Dict:
    if len(closes) < n:
        return {'k': 50.0, 'd': 50.0, 'j': 50.0, 'signal': '数据不足'}
    k, d = 50.0, 50.0
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100.0
        k = (2 / 3) * k + (1 / 3) * rsv
        d = (2 / 3) * d + (1 / 3) * k
    j = 3 * k - 2 * d
    signal = '超卖修复' if j < 20 else ('高位钝化' if j > 90 else '中性')
    return {'k': k, 'd': d, 'j': j, 'signal': signal}


def fetch_tech_metrics(code: str, lookback: int = 60, source_stats: Dict = None) -> Dict:
    providers = [
        ('eastmoney', lambda: fetch_kline_eastmoney(code, lookback)),
        ('tencent', lambda: fetch_kline_tencent(code, lookback)),
        ('sina-kline', lambda: fetch_kline_sina(code, lookback)),
    ]

    closes, highs, lows, k_source = [], [], [], 'unknown'
    for src, fn in providers:
        try:
            c, h, l = fn()
            if len(c) >= 25:
                closes, highs, lows, k_source = c, h, l, src
                if source_stats is not None:
                    source_stats.setdefault(src, {'ok': 0, 'fail': 0})
                    source_stats[src]['ok'] += 1
                break
            if source_stats is not None:
                source_stats.setdefault(src, {'ok': 0, 'fail': 0})
                source_stats[src]['fail'] += 1
        except Exception:
            if source_stats is not None:
                source_stats.setdefault(src, {'ok': 0, 'fail': 0})
                source_stats[src]['fail'] += 1
            continue

    if len(closes) < 25:
        return {
            'perf_5d': 0.0,
            'perf_20d': 0.0,
            'ma5': 0.0,
            'ma20': 0.0,
            'trend_signal': '未知',
            'macd': {'dif': 0.0, 'dea': 0.0, 'hist': 0.0, 'signal': '未知'},
            'kdj': {'k': 50.0, 'd': 50.0, 'j': 50.0, 'signal': '未知'},
            'tech_score': 0.45,
            'kline_source': k_source,
        }

    ma5_now, ma20_now = sum(closes[-5:]) / 5, sum(closes[-20:]) / 20
    ma5_prev, ma20_prev = sum(closes[-6:-1]) / 5, sum(closes[-21:-1]) / 20

    trend_signal = '金叉' if ma5_now > ma20_now and ma5_prev <= ma20_prev else ('死叉' if ma5_now < ma20_now and ma5_prev >= ma20_prev else ('多头' if ma5_now > ma20_now else '空头'))
    perf_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0.0
    perf_20d = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0.0
    macd = calc_macd(closes)
    kdj = calc_kdj(closes, highs, lows)

    tech_score = 0.0
    tech_score += 0.35 if trend_signal in ('金叉', '多头') else 0.10
    tech_score += 0.30 if macd['signal'] in ('金叉', '延续') and macd['hist'] > -0.2 else 0.10
    tech_score += 0.20 if -10 <= perf_20d <= 25 else 0.08
    tech_score += 0.15 if -5 <= perf_5d <= 10 else 0.07

    return {
        'perf_5d': perf_5d,
        'perf_20d': perf_20d,
        'ma5': ma5_now,
        'ma20': ma20_now,
        'trend_signal': trend_signal,
        'macd': macd,
        'kdj': kdj,
        'tech_score': min(1.0, max(0.0, tech_score)),
        'kline_source': k_source,
    }


def infer_sector(stock: Dict) -> str:
    txt = f"{stock.get('industry', '')} {stock.get('name', '')}"
    for sector, kws in SECTOR_NAME_RULES:
        if any(k in txt for k in kws):
            return sector
    return stock.get('industry') or '其他'
def select(policy: Dict, top_n=10, horizon_days=30, max_api_calls: int = 50, sector_cap: int = 4):
    raw, api_calls_used = fetch_snapshot(max_api_calls=max_api_calls)

    min_price = 1.5
    min_amount = 3e7
    min_market_cap = 1e9
    pe_max = 240  # 放宽PE约束：约束强度降为原来的1/2（上限由120放宽到240）
    pb_max = 20

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
        if s['price'] <= min_price:
            stats['removed_low_price'] += 1
            continue
        if s['amount'] < min_amount:
            stats['removed_low_amount'] += 1
            continue
        if s['market_cap'] and s['market_cap'] < min_market_cap:
            stats['removed_small_cap'] += 1
            continue
        if not (0 < s['pe_ttm'] < pe_max):
            stats['removed_bad_pe'] += 1
            continue
        if not (0 < s['pb'] < pb_max):
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
    mom = [max(0.0, 1.0 - abs(x - 1.5) / 10.0) for x in pct]

    prelim = []
    for i, s in enumerate(universe):
        p = score_policy(s, policy)
        value_score = 0.5 * pe_rank[i] + 0.5 * pb_rank[i]
        stability_score = amp_rank[i]
        momentum_score = mom[i]
        liquidity_score = amt_rank[i]
        quant_score = 0.42 * value_score + 0.28 * stability_score + 0.30 * momentum_score
        base_total = 0.1765 * p['policy_score'] + 0.4118 * quant_score + 0.4118 * liquidity_score

        prelim.append({
            **s,
            'policy_score': p['policy_score'],
            'policy_hits': p['policy_hits'],
            'quant_score': quant_score,
            'liquidity_score': liquidity_score,
            'base_total': base_total,
            'sector': infer_sector(s),
        })

    prelim.sort(key=lambda x: x['base_total'], reverse=True)
    tech_pool = prelim[:min(max(top_n * 8, 40), len(prelim))]

    kline_source_stats: Dict[str, Dict[str, int]] = {}
    picks_scored = []
    for s in tech_pool:
        tech = fetch_tech_metrics(s['code'], source_stats=kline_source_stats)
        total = 0.15 * s['policy_score'] + 0.35 * s['quant_score'] + 0.35 * s['liquidity_score'] + 0.15 * tech['tech_score']
        reasons = []
        if s['policy_hits']:
            reasons.append('政策匹配: ' + '、'.join([x[0] for x in s['policy_hits'][:2]]))
        reasons.append(f"板块: {s['sector']}")
        reasons.append(f"近1周/1月: {tech['perf_5d']:.1f}% / {tech['perf_20d']:.1f}%")
        reasons.append(f"均线: MA5={tech['ma5']:.2f}, MA20={tech['ma20']:.2f}, 信号={tech['trend_signal']}")
        reasons.append(f"MACD={tech['macd']['signal']}, KDJ(J={tech['kdj']['j']:.1f})")
        reasons.append(f"K线源: {tech.get('kline_source', 'unknown')}")

        picks_scored.append({
            'code': s['code'],
            'name': s['name'],
            'industry': s['industry'],
            'sector': s['sector'],
            'price': s['price'],
            'pct_chg': s['pct_chg'],
            'pe_ttm': s['pe_ttm'],
            'pb': s['pb'],
            'amount': s['amount'],
            'policy_score': round(s['policy_score'], 4),
            'quant_score': round(s['quant_score'], 4),
            'liquidity_score': round(s['liquidity_score'], 4),
            'tech_score': round(tech['tech_score'], 4),
            'kline_source': tech.get('kline_source', 'unknown'),
            'total_score': round(total, 4),
            'horizon_days': horizon_days,
            'reasons': reasons,
            'tech': {
                'perf_5d': round(tech['perf_5d'], 2),
                'perf_20d': round(tech['perf_20d'], 2),
                'ma5': round(tech['ma5'], 3),
                'ma20': round(tech['ma20'], 3),
                'trend_signal': tech['trend_signal'],
                'macd': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in tech['macd'].items()},
                'kdj': {k: (round(v, 2) if isinstance(v, float) else v) for k, v in tech['kdj'].items()},
            },
            'api_source': 'snapshot:sina;kline:auto',
            'api_calls_used': api_calls_used,
        })

    picks_scored.sort(key=lambda x: x['total_score'], reverse=True)

    selected = []
    sector_counter: Dict[str, int] = {}
    for s in picks_scored:
        sec = s['sector']
        if sector_counter.get(sec, 0) >= sector_cap:
            continue
        selected.append(s)
        sector_counter[sec] = sector_counter.get(sec, 0) + 1
        if len(selected) >= top_n:
            break

    if len(selected) < top_n:
        used_codes = {x['code'] for x in selected}
        for s in picks_scored:
            if s['code'] in used_codes:
                continue
            selected.append(s)
            if len(selected) >= top_n:
                break

    kline_all_failed = all(kline_source_stats.get(x, {}).get('ok', 0) == 0 for x in ['eastmoney', 'tencent', 'sina-kline'])
    source_alerts = []
    if kline_all_failed:
        source_alerts.append('K线数据源全部失效（eastmoney/tencent/sina-kline）')

    source_status = {
        'kline': {
            'primary': 'eastmoney',
            'backup': 'tencent',
            'fallback': 'sina-kline',
            'stats': kline_source_stats,
            'all_failed': kline_all_failed,
        },
        'alerts': source_alerts,
    }

    return selected[:top_n], api_calls_used, stats, source_status
