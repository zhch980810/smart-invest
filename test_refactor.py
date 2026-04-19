#!/usr/bin/env python3
"""验证重构结果"""
import sys, os
sys.path.insert(0, 'scripts')

# 1. data_fetch 核心导入 (合并后的统一模块)
from a_share_selector.data_fetch import (
    http_get, request_with_retry, to_float, code_to_secid,
    fetch_kline, fetch_snapshot_by_codes,
    eastmoney_get, load_codes, collect_all,
    EASTMONEY_HEADERS,
)
print('OK data_fetch imports (merged module)')

# 2. data_collector 已合并删除
assert not os.path.exists('scripts/a_share_selector/data_collector.py'), \
    'FAIL: data_collector.py still exists'
print('OK data_collector.py removed (merged into data_fetch)')

# 3. quant_model
from a_share_selector.quant_model import score_policy, infer_sector
print('OK quant_model imports')

# 4. __init__
from a_share_selector import collect_all, load_codes, score_policy, infer_sector
print('OK __init__ exports')

# 5. 旧三源 K线函数已移除
for old_fn in ('fetch_kline_eastmoney', 'fetch_kline_tencent', 'fetch_kline_sina'):
    assert not hasattr(__import__('a_share_selector.data_fetch', fromlist=[old_fn]), old_fn) \
        or old_fn not in dir(__import__('a_share_selector.data_fetch', fromlist=[old_fn])), \
        f'FAIL: {old_fn} still exists'
print('OK legacy kline functions removed')

# 6. collect_and_filter can be imported
import collect_and_filter
print('OK collect_and_filter imports')

# 7. prepare_stocks can be imported
import prepare_stocks
print('OK prepare_stocks imports')

print('\nAll checks passed')
