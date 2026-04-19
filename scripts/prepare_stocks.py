#!/usr/bin/env python3
"""
根据用户配置生成目标股票池，输出到 stocks/stocks.txt。

用法:
  python3 scripts/prepare_stocks.py --source user_interest   # 按板块关键词搜索
  python3 scripts/prepare_stocks.py --source user_stocks      # 从用户股票清单提取
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from zoneinfo import ZoneInfo

# 让 scripts/ 目录可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a_share_selector.data_fetch import eastmoney_get

ROOT = Path(__file__).resolve().parents[1]
USER_DIR = ROOT / 'user'
STOCKS_DIR = ROOT / 'stocks'
STOCKS_FILE = STOCKS_DIR / 'stocks.txt'
TZ = ZoneInfo('Asia/Shanghai')


# ── 板块搜索相关 ──────────────────────────────────────────────


def fetch_boards(board_type: str = 'concept') -> List[Dict]:
    """获取东财板块列表。board_type: 'concept'(概念) 或 'industry'(行业)"""
    fs = 'm:90+t:3' if board_type == 'concept' else 'm:90+t:2'
    all_boards: List[Dict] = []
    page = 1
    page_size = 100  # 东财 API 服务端上限 100/页
    while True:
        data = eastmoney_get(
            'https://push2.eastmoney.com/api/qt/clist/get',
            params={
                'pn': str(page),
                'pz': str(page_size),
                'po': '1',
                'np': '1',
                'fltt': '2',
                'invt': '2',
                'fid': 'f3',
                'fs': fs,
                'fields': 'f12,f14',
            },
        )
        inner = data.get('data') or {}
        total = inner.get('total', 0)
        diff = inner.get('diff') or []
        if not diff:
            break
        for item in diff:
            if item.get('f12') and item.get('f14'):
                all_boards.append({'code': item['f12'], 'name': item['f14']})
        if len(all_boards) >= total or len(diff) < page_size:
            break
        page += 1
        time.sleep(0.3)
    return all_boards


def fetch_board_stocks(board_code: str) -> List[Dict]:
    """获取指定板块的成分股列表"""
    all_stocks: List[Dict] = []
    page = 1
    while True:
        data = eastmoney_get(
            'https://push2.eastmoney.com/api/qt/clist/get',
            params={
                'pn': str(page),
                'pz': '500',
                'po': '1',
                'np': '1',
                'fltt': '2',
                'invt': '2',
                'fid': 'f3',
                'fs': f'b:{board_code}',
                'fields': 'f12,f13,f14',
            },
        )
        diff = (data.get('data') or {}).get('diff') or []
        if not diff:
            break
        for item in diff:
            code = str(item.get('f12', '')).strip()
            name = str(item.get('f14', '')).strip()
            market = item.get('f13', -1)
            # 仅保留 A 股主板 / 中小创（market 0=深圳, 1=上海）
            if code and name and market in (0, 1):
                all_stocks.append({'code': code, 'name': name})
        if len(diff) < 500:
            break
        page += 1
        time.sleep(0.3)
    return all_stocks


def collect_by_interest(keywords: List[str]) -> List[Dict]:
    """根据兴趣关键词收集对应板块的股票"""
    print(f'[prepare] 关键词: {keywords}')

    print('[prepare] 获取板块列表...')
    concepts = fetch_boards('concept')
    industries = fetch_boards('industry')
    all_boards = concepts + industries
    print(f'[prepare] 共获取 {len(concepts)} 个概念板块, {len(industries)} 个行业板块')

    matched: List[tuple] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        for b in all_boards:
            if kw in b['name']:
                matched.append((kw, b))
                print(f'[prepare] 关键词 "{kw}" 匹配板块: {b["name"]}({b["code"]})')

    if not matched:
        print('[prepare] 警告: 没有匹配到任何板块')
        return []

    all_stocks: Dict[str, Dict] = {}
    for kw, board in matched:
        print(f'[prepare] 获取板块 {board["name"]} 的成分股...')
        stocks = fetch_board_stocks(board['code'])
        for s in stocks:
            if s['code'] not in all_stocks:
                all_stocks[s['code']] = {**s, 'source_boards': []}
            all_stocks[s['code']]['source_boards'].append(board['name'])
        print(f'[prepare] 板块 {board["name"]}: {len(stocks)} 只股票')
        time.sleep(0.5)

    result = sorted(all_stocks.values(), key=lambda x: x['code'])
    print(f'[prepare] 去重后共 {len(result)} 只股票')
    return result


# ── 用户股票清单解析 ─────────────────────────────────────────


def collect_by_stocks(content: str) -> List[Dict]:
    """从 user_stocks.txt 中提取股票代码和名称"""
    stocks: List[Dict] = []
    seen: set = set()
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.search(r'\b(\d{6})\b', line)
        if not match:
            continue
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        name_match = re.search(r'([\u4e00-\u9fa5]+)', line)
        name = name_match.group(1) if name_match else ''
        stocks.append({'code': code, 'name': name})

    print(f'[prepare] 从 user_stocks.txt 提取 {len(stocks)} 只股票')
    return stocks


# ── 输出 ──────────────────────────────────────────────────────


def write_stocks_file(stocks: List[Dict], source: str):
    """写入 stocks/stocks.txt"""
    STOCKS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        '# 目标股票池 (自动生成)',
        f'# 来源: {source}',
        f'# 生成时间: {now}',
        f'# 股票数量: {len(stocks)}',
        '#',
        '# code\tname\t[板块]',
    ]
    for s in stocks:
        boards_str = ','.join(s.get('source_boards', []))
        if boards_str:
            lines.append(f'{s["code"]}\t{s["name"]}\t# {boards_str}')
        else:
            lines.append(f'{s["code"]}\t{s["name"]}')

    with open(STOCKS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print(f'[prepare] 已写入 {STOCKS_FILE} ({len(stocks)} 只股票)')


# ── main ──────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description='生成目标股票池 -> stocks/stocks.txt')
    ap.add_argument(
        '--source',
        required=True,
        choices=['user_interest', 'user_stocks'],
        help='输入源: user_interest(按板块关键词) 或 user_stocks(指定清单)',
    )
    args = ap.parse_args()

    if args.source == 'user_interest':
        interest_file = USER_DIR / 'user_interest.txt'
        if not interest_file.exists():
            raise FileNotFoundError(f'找不到文件: {interest_file}')
        keywords = [
            line.strip()
            for line in interest_file.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]
        if not keywords:
            raise ValueError('user_interest.txt 中没有找到有效关键词')
        stocks = collect_by_interest(keywords)
    else:
        stocks_file = USER_DIR / 'user_stocks.txt'
        if not stocks_file.exists():
            raise FileNotFoundError(f'找不到文件: {stocks_file}')
        content = stocks_file.read_text(encoding='utf-8')
        stocks = collect_by_stocks(content)

    if not stocks:
        raise RuntimeError('未收集到任何股票，请检查输入文件')

    write_stocks_file(stocks, args.source)


if __name__ == '__main__':
    main()
