#!/usr/bin/env python3
"""
Step 2: 数据采集 + 初筛 → CSV

从 stocks/stocks.txt 读取股票代码列表，调用 data_collector.collect_all() 获取 9 维数据，
执行初筛后输出 CSV。

用法:
  python3 scripts/collect_and_filter.py [--stocks-file stocks/stocks.txt] [--output-dir data/]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from zoneinfo import ZoneInfo

# 让 scripts/ 目录可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a_share_selector.data_fetch import collect_all, load_codes

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOCKS_FILE = ROOT / 'stocks' / 'stocks.txt'
DEFAULT_OUTPUT_DIR = ROOT / 'data'
TZ = ZoneInfo('Asia/Shanghai')

# ── 主板代码前缀白名单 ───────────────────────────────────────
MAIN_BOARD_PREFIXES = ('000', '001', '002', '003', '600', '601', '603', '605')


def apply_filters(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """执行初筛，返回 (筛选后 DataFrame, 统计摘要)"""
    stats = {
        'total_before_filter': len(df),
        'removed_non_main_board': 0,
        'removed_small_cap': 0,
        'removed_bad_pe': 0,
        'remaining': 0,
    }

    if df.empty:
        return df, stats

    # 1. 仅保留主板：排除 300xxx（创业板）和 688xxx（科创板）
    mask_main = df['code'].apply(lambda c: c.startswith(MAIN_BOARD_PREFIXES))
    stats['removed_non_main_board'] = int((~mask_main).sum())
    df = df[mask_main].copy()

    # 2. 市值 > 100 亿元
    mask_cap = df['market_cap'] > 1e10
    stats['removed_small_cap'] = int((~mask_cap).sum())
    df = df[mask_cap].copy()

    # 3. 0 < PE(TTM) < 200
    mask_pe = (df['pe_ttm'] > 0) & (df['pe_ttm'] < 200)
    stats['removed_bad_pe'] = int((~mask_pe).sum())
    df = df[mask_pe].copy()

    stats['remaining'] = len(df)
    return df.reset_index(drop=True), stats


def main():
    ap = argparse.ArgumentParser(description='数据采集 + 初筛 → CSV')
    ap.add_argument(
        '--stocks-file',
        type=str,
        default=str(DEFAULT_STOCKS_FILE),
        help=f'目标股票池文件路径 (默认: {DEFAULT_STOCKS_FILE})',
    )
    ap.add_argument(
        '--output-dir',
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f'CSV 输出目录 (默认: {DEFAULT_OUTPUT_DIR})',
    )
    args = ap.parse_args()

    stocks_file = Path(args.stocks_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取股票代码
    codes = load_codes(stocks_file)
    if not codes:
        print('[collect_and_filter] 股票代码列表为空，退出')
        sys.exit(1)
    print(f'[collect_and_filter] 从 {stocks_file} 读取 {len(codes)} 只股票')

    # 采集 9 维数据
    df = collect_all(codes)
    if df.empty:
        print('[collect_and_filter] 数据采集结果为空，退出')
        sys.exit(1)

    # 初筛
    df_filtered, stats = apply_filters(df)

    # 输出 CSV
    today = datetime.now(TZ).strftime('%Y%m%d')
    csv_path = output_dir / f'candidates_{today}.csv'
    df_filtered.to_csv(csv_path, index=False, encoding='utf-8-sig')

    # 打印统计摘要
    print()
    print('=' * 60)
    print('初筛统计摘要')
    print('=' * 60)
    print(f"  总采集数:         {stats['total_before_filter']}")
    print(f"  去除非主板:       {stats['removed_non_main_board']}")
    print(f"  去除市值<100亿:   {stats['removed_small_cap']}")
    print(f"  去除PE异常:       {stats['removed_bad_pe']}")
    print(f"  剩余候选数:       {stats['remaining']}")
    print(f'  输出文件:         {csv_path}')
    print('=' * 60)

    # 数据完整度检查
    if not df_filtered.empty:
        print()
        print('数据完整度（非空率）:')
        for col in df_filtered.columns:
            non_null = df_filtered[col].notna().sum()
            total = len(df_filtered)
            pct = non_null / total * 100 if total > 0 else 0
            print(f'  {col:30s} {non_null}/{total}  ({pct:.1f}%)')


if __name__ == '__main__':
    main()
