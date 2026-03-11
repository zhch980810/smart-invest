#!/usr/bin/env python3
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from zoneinfo import ZoneInfo

from a_share_selector.quant_model import select

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / 'research/a_share_policy_quant/policy_signals.json'
OUT_DIR = ROOT / 'research/a_share_policy_quant/output'
TZ = ZoneInfo('Asia/Shanghai')


def load_policy() -> Dict:
    with open(POLICY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def dump_outputs(
    picks: List[Dict],
    policy: Dict,
    api_calls_used: int,
    max_api_calls: int,
    stats: Dict,
    policy_news: List[Dict],
    policy_keywords: List[str],
    policy_summary: str,
    source_status: Dict,
    sector_cap: int,
):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = datetime.now(TZ).strftime('%Y%m%d')
    js_path = OUT_DIR / f'top10_{d}.json'
    txt_path = OUT_DIR / f'top10_{d}.txt'

    payload = {
        'generated_at': datetime.now(TZ).isoformat(),
        'method': 'policy+quant+tech-v3',
        'policy_as_of': policy.get('as_of'),
        'api_source': 'snapshot:sina, kline:auto, news:auto',
        'api_calls_used': api_calls_used,
        'max_api_calls': max_api_calls,
        'sector_cap': sector_cap,
        'filter_stats': stats,
        'policy_news_24h': [
            {
                'time': x['time'].strftime('%Y-%m-%d %H:%M:%S'),
                'title': x['title'],
                'url': x['url'],
                'source': x.get('source'),
                'bullish_sectors': x.get('bullish_sectors', []),
                'bearish_sectors': x.get('bearish_sectors', []),
            }
            for x in policy_news
        ],
        'policy_keywords': policy_keywords,
        'policy_summary': policy_summary,
        'source_status': source_status,
        'top10': picks,
    }
    with open(js_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    today_cn = datetime.now(TZ).strftime('%Y年%m月%d日')

    lines = []
    lines.append('【数据源状态】')
    lines.append(
        f"K线主源/备源/兜底: {source_status['kline']['primary']} / {source_status['kline']['backup']} / {source_status['kline'].get('fallback', 'none')}"
    )
    lines.append(f"K线统计: {json.dumps(source_status['kline']['stats'], ensure_ascii=False)}")
    lines.append(
        f"消息面主源/备源/兜底: {source_status['news'].get('primary')} / {source_status['news'].get('backup')} / {source_status['news'].get('fallback', 'none')}"
    )
    lines.append(f"消息面实际使用: {source_status['news'].get('used') or 'none'}")
    if source_status.get('alerts'):
        lines.append('【数据源告警】' + '；'.join(source_status['alerts']))
    if source_status['news'].get('errors'):
        lines.append('【消息面切换日志】' + '；'.join(source_status['news']['errors'][:5]))
    lines.append('')

    lines.append('【政策面关键词】')
    lines.append('、'.join(policy_keywords))
    lines.append(f'【政策面概括】{policy_summary}')
    lines.append('')
    neutral_cnt = sum(1 for n in policy_news if not n.get('bullish_sectors') and not n.get('bearish_sectors'))
    lines.append(f'【政策新闻结构】方向性 {len(policy_news) - neutral_cnt} 条 | 中性 {neutral_cnt}/5 条')
    lines.append(f'【过去24小时政策面消息（含板块影响）】（截至 {now_str}）')
    if policy_news:
        for i, n in enumerate(policy_news, 1):
            bull = '、'.join(n.get('bullish_sectors') or ['中性'])
            bear = '、'.join(n.get('bearish_sectors') or ['中性'])
            lines.append(f"{i}. [{n['time'].strftime('%m-%d %H:%M')}] {n['title']}")
            lines.append(f'   来源: {n.get("source", "unknown")}')
            lines.append(f'   利好板块: {bull} | 利空板块: {bear}')
            lines.append(f"   链接: {n['url']}")
    else:
        lines.append('过去24小时未抓取到可用资讯（可能受来源时效/网络影响）。')

    lines.append('')
    lines.append('【抓取与筛选过程（宽松版）】')
    lines.append(
        f"{today_cn} 共抓取 {stats['total_fetched']} 只A股快照样本，字段包括: 价格、涨跌幅、成交额、振幅、换手率、PE(TTM)、PB、总市值。"
    )
    lines.append(f'数据源: 新浪(快照) + 东财/腾讯/新浪(K线自动切换) + 新浪/东财/同花顺(消息面自动切换)')
    lines.append(f'快照API调用: {api_calls_used}/{max_api_calls}')
    lines.append('筛选阈值: 价格>1.5元, 成交额>0.3亿元, 市值>10亿元, 0<PE<120, 0<PB<20')
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

    return js_path, txt_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--horizon', type=int, default=30)
    ap.add_argument('--max-api-calls', type=int, default=50)
    ap.add_argument('--sector-cap', type=int, default=4)
    args = ap.parse_args()

    policy = load_policy()
    picks, api_calls_used, stats, policy_news, policy_keywords, policy_summary, source_status = select(
        policy=policy,
        top_n=args.top,
        horizon_days=args.horizon,
        max_api_calls=args.max_api_calls,
        sector_cap=args.sector_cap,
    )
    js_path, txt_path = dump_outputs(
        picks,
        policy,
        api_calls_used,
        args.max_api_calls,
        stats,
        policy_news,
        policy_keywords,
        policy_summary,
        source_status,
        args.sector_cap,
    )
    print(f'JSON: {js_path}')
    print(f'TEXT: {txt_path}')
    print(f'API calls(snapshot): {api_calls_used}/{args.max_api_calls}')
    print(f'Fetched: {stats["total_fetched"]}, Remaining: {stats["remaining"]}, PolicyNews24h: {len(policy_news)}')


if __name__ == '__main__':
    main()
