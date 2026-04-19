"""A股数据采集统一模块。

提供:
  - 行情快照获取 (PE、市值、价格等基础字段)
  - K线数据获取 (前复权日K线)
  - 财务指标采集 (ROE、净利润增长率)
  - 资金面数据 (两融差额、资金流向、户均持股)
  - 工具函数 (HTTP请求、代码转换、文件读取)

统一入口: collect_all(codes) -> pd.DataFrame

数据源说明:
  - 行情快照: 东方财富直接 API (支持批量、含行业字段)
  - K线/财务/资金面: akshare (统一封装，简化维护)
  - eastmoney_get: 保留供 prepare_stocks 等外部模块复用
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import requests

# ── 常量 & 配置 ──────────────────────────────────────────────

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

EASTMONEY_HEADERS = {'Referer': 'https://quote.eastmoney.com/'}

_DEFAULT_SLEEP = 0.6   # 每只股票之间的默认等待（秒）
_AK_SLEEP = 1.0        # akshare 调用之间的等待（秒）


# ── HTTP 基础设施 (供 prepare_stocks 等外部模块复用) ──────────


def request_with_retry(request_fn, retries=3, sleep_sec=1.2):
    last_err = None
    for _ in range(retries):
        try:
            return request_fn()
        except Exception as e:
            last_err = e
            time.sleep(sleep_sec)
    raise RuntimeError(f'请求失败: {last_err}')


def http_get(url: str, *, params: Dict = None, timeout: int = 12,
             headers: Dict = None, encoding: str = None):
    merged_headers = DEFAULT_HEADERS.copy()
    if headers:
        merged_headers.update(headers)
    resp = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
    resp.raise_for_status()
    if encoding:
        resp.encoding = encoding
    return resp


def eastmoney_get(url: str, params: Dict, retries: int = 3, sleep_sec: float = 1.0) -> dict:
    """东方财富 API 便捷请求（返回 JSON dict）。

    供外部模块（如 prepare_stocks）复用，避免重复实现请求逻辑。
    """
    resp = request_with_retry(
        lambda: http_get(url, params=params, timeout=15, headers=EASTMONEY_HEADERS),
        retries=retries,
        sleep_sec=sleep_sec,
    )
    return resp.json() if hasattr(resp, 'json') else {}


# ── 工具函数 ──────────────────────────────────────────────────


def to_float(v, default=0.0) -> float:
    try:
        if v is None or v == '':
            return default
        return float(v)
    except Exception:
        return default


def code_to_secid(code: str) -> str:
    return f'1.{code}' if code.startswith(('5', '6')) else f'0.{code}'


def load_codes(stocks_file: Path) -> list[str]:
    """从 stocks.txt 读取股票代码列表。

    文件格式: 每行以 6 位数字代码开头，可选 tab 分隔名称和注释。
    跳过空行和 #注释行。
    """
    if not stocks_file.exists():
        raise FileNotFoundError(f'文件不存在: {stocks_file}')

    codes: list[str] = []
    for line in stocks_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        code = parts[0].strip()
        if re.match(r'^\d{6}$', code):
            codes.append(code)
    return codes


def _safe_akshare_call(fn, *args, **kwargs):
    """安全调用 akshare 函数，失败返回 None"""
    try:
        result = fn(*args, **kwargs)
        time.sleep(_AK_SLEEP)
        return result
    except Exception as e:
        print(f'  [data_fetch] akshare 调用失败: {fn.__name__} — {e}')
        return None


# ── 行情快照 (东方财富批量 API，高效且含行业字段) ─────────────
#
# 说明: akshare 的 stock_zh_a_spot_em() 不含「行业」列，
# 因此快照仍使用东方财富直接 API 以保留 industry 字段。


def fetch_snapshot_by_codes(codes: List[str], batch_size: int = 50) -> Tuple[List[Dict], int]:
    """根据指定股票代码列表，批量从东方财富获取行情快照。

    返回: (rows, api_calls_used)
    """
    if not codes:
        raise RuntimeError('股票代码列表为空')

    rows: List[Dict] = []
    api_calls_used = 0

    for i in range(0, len(codes), batch_size):
        batch = codes[i : i + batch_size]
        secids = ','.join(code_to_secid(c) for c in batch)

        resp = request_with_retry(
            lambda _secids=secids: http_get(
                'https://push2.eastmoney.com/api/qt/ulist.np/get',
                params={
                    'fltt': '2',
                    'secids': _secids,
                    'fields': 'f2,f3,f6,f7,f8,f9,f12,f14,f15,f16,f18,f20,f21,f23,f100',
                },
                timeout=12,
                headers=EASTMONEY_HEADERS,
            ),
            retries=3,
            sleep_sec=1.0,
        )
        api_calls_used += 1

        data = (resp.json() if hasattr(resp, 'json') else {}).get('data') or {}
        diff = data.get('diff') or []

        for v in diff:
            code = str(v.get('f12', '')).strip()
            name = str(v.get('f14', '')).strip()
            if not code or not name or name == '-':
                continue

            rows.append(
                {
                    'code': code,
                    'name': name,
                    'price': to_float(v.get('f2')),
                    'pct_chg': to_float(v.get('f3')),
                    'amount': to_float(v.get('f6')),
                    'amplitude': to_float(v.get('f7')),
                    'turnover': to_float(v.get('f8')),
                    'pe_ttm': to_float(v.get('f9')),
                    'market_cap': to_float(v.get('f20')),
                    'float_cap': to_float(v.get('f21')),
                    'pb': to_float(v.get('f23')),
                    'industry': str(v.get('f100') or '').strip(),
                }
            )

        if i + batch_size < len(codes):
            time.sleep(0.5)

    if not rows:
        raise RuntimeError(f'东财接口返回为空 (请求 {len(codes)} 只股票)')

    return rows, api_calls_used


def _fetch_snapshot_fields(codes: List[str]) -> Dict[str, Dict]:
    """批量获取 PE(TTM)、市值、价格、涨跌幅、行业、名称等基础字段。

    返回: {code: {pe_ttm, market_cap, price, pct_chg, name, industry, ...}}
    """
    try:
        rows, _ = fetch_snapshot_by_codes(codes)
    except Exception as e:
        print(f'[data_fetch] fetch_snapshot_by_codes 失败: {e}')
        return {}
    return {row['code']: row for row in rows}


# ── K线数据 (akshare，替代原 eastmoney/tencent/sina 三源) ────


def fetch_kline(code: str, lookback: int = 60) -> Tuple[List[float], List[float], List[float]]:
    """通过 akshare 获取前复权日K线。

    返回: (closes, highs, lows) — 按日期升序排列
    """
    try:
        import akshare as ak

        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=int(lookback * 2))).strftime('%Y%m%d')

        df = _safe_akshare_call(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if df is None or df.empty:
            return [], [], []

        df = df.tail(lookback)
        closes = df['收盘'].apply(lambda x: to_float(x)).tolist()
        highs = df['最高'].apply(lambda x: to_float(x)).tolist()
        lows = df['最低'].apply(lambda x: to_float(x)).tolist()
        return closes, highs, lows
    except Exception as e:
        print(f'  [data_fetch] fetch_kline({code}) 失败: {e}')
        return [], [], []


# ── 收益率计算 ────────────────────────────────────────────────


def calc_return_5d(code: str) -> float:
    """计算近5日收益率 = (close[-1] / close[-6] - 1)"""
    try:
        closes, _, _ = fetch_kline(code, 10)
        if len(closes) >= 6 and closes[-6] > 0:
            return closes[-1] / closes[-6] - 1
    except Exception:
        pass
    return float('nan')


# ── 财务指标 (akshare) ───────────────────────────────────────


def fetch_roe(code: str) -> float:
    """获取最新 ROE（摊薄净资产收益率）"""
    try:
        import akshare as ak

        df = _safe_akshare_call(ak.stock_financial_analysis_indicator, symbol=code)
        if df is None or df.empty:
            return float('nan')
        # 列名可能为 '净资产收益率(摊薄)(%)' 或类似
        roe_cols = [c for c in df.columns if '净资产收益率' in c and '摊薄' in c]
        if not roe_cols:
            roe_cols = [c for c in df.columns if '净资产收益率' in c]
        if not roe_cols:
            return float('nan')
        val = df[roe_cols[0]].iloc[0]
        return to_float(val, float('nan'))
    except Exception as e:
        print(f'  [data_fetch] fetch_roe({code}) 失败: {e}')
        return float('nan')


def fetch_net_profit_growth(code: str) -> float:
    """获取最新净利润同比增长率（业绩报表）"""
    try:
        import akshare as ak
        import pandas as pd

        now = datetime.now()
        quarters = []
        y = now.year
        q_map = {1: '0331', 2: '0630', 3: '0930', 4: '1231'}
        current_q = (now.month - 1) // 3 + 1
        for offset in range(4):
            q = current_q - offset
            yr = y
            if q <= 0:
                q += 4
                yr -= 1
            quarters.append(f'{yr}{q_map[q]}')

        for date_str in quarters:
            df = _safe_akshare_call(ak.stock_yjbb_em, date=date_str)
            if df is None or df.empty:
                continue
            growth_cols = [c for c in df.columns if '净利润同比' in c]
            if not growth_cols:
                continue
            row = df[df['股票代码'] == code] if '股票代码' in df.columns else pd.DataFrame()
            if row.empty:
                continue
            val = row[growth_cols[0]].iloc[0]
            return to_float(val, float('nan'))
        return float('nan')
    except Exception as e:
        print(f'  [data_fetch] fetch_net_profit_growth({code}) 失败: {e}')
        return float('nan')


# ── 资金面数据 (akshare) ─────────────────────────────────────


def fetch_margin_balance(code: str) -> float:
    """获取个股融资余额 - 融券余额（两融差额）"""
    try:
        import akshare as ak

        if code.startswith(('0', '3')):
            df = _safe_akshare_call(ak.stock_margin_detail_szse, date='')
        else:
            df = _safe_akshare_call(ak.stock_margin_detail_sse, date='')

        if df is None or df.empty:
            return float('nan')

        code_cols = [c for c in df.columns if '代码' in c or 'code' in c.lower()]
        if not code_cols:
            return float('nan')

        row = df[df[code_cols[0]].astype(str).str.contains(code)]
        if row.empty:
            return float('nan')

        rz_cols = [c for c in df.columns if '融资余额' in c]
        rq_cols = [c for c in df.columns if '融券余额' in c]
        if not rz_cols or not rq_cols:
            return float('nan')

        rz = to_float(row[rz_cols[0]].iloc[0], 0.0)
        rq = to_float(row[rq_cols[0]].iloc[0], 0.0)
        return rz - rq
    except Exception as e:
        print(f'  [data_fetch] fetch_margin_balance({code}) 失败: {e}')
        return float('nan')


def fetch_fund_flow(code: str) -> Dict[str, float]:
    """获取个股资金流向，返回 {fund_flow_5d, fund_flow_10d, main_force_ratio}"""
    result = {
        'fund_flow_5d': float('nan'),
        'fund_flow_10d': float('nan'),
        'main_force_ratio': float('nan'),
    }
    try:
        import akshare as ak

        market = 'sh' if code.startswith(('5', '6')) else 'sz'
        df = _safe_akshare_call(ak.stock_individual_fund_flow, stock=code, market=market)
        if df is None or df.empty:
            return result

        main_cols = [c for c in df.columns if '主力净流入' in c and '净额' in c]
        if not main_cols:
            main_cols = [c for c in df.columns if '主力净流入' in c]

        if main_cols:
            col = main_cols[0]
            vals = df[col].apply(lambda x: to_float(x, 0.0)).tolist()
            if len(vals) >= 5:
                result['fund_flow_5d'] = sum(vals[-5:])
            if len(vals) >= 10:
                result['fund_flow_10d'] = sum(vals[-10:])

        ratio_cols = [c for c in df.columns if '主力净流入' in c and '占比' in c]
        if ratio_cols and not df.empty:
            latest = to_float(df[ratio_cols[0]].iloc[-1], float('nan'))
            result['main_force_ratio'] = latest

        return result
    except Exception as e:
        print(f'  [data_fetch] fetch_fund_flow({code}) 失败: {e}')
        return result


def fetch_avg_holding(code: str) -> float:
    """获取户均持股金额/户数"""
    try:
        import akshare as ak

        df = _safe_akshare_call(ak.stock_zh_a_gdhs_detail_em, symbol=code)
        if df is None or df.empty:
            return float('nan')

        holding_cols = [c for c in df.columns if '户均持股' in c]
        if holding_cols:
            val = df[holding_cols[0]].iloc[0]
            return to_float(val, float('nan'))

        # fallback: 如有 '总股本' 和 '股东户数' 列，手动计算
        shares_cols = [c for c in df.columns if '总股本' in c or '股本' in c]
        holder_cols = [c for c in df.columns if '户数' in c or '股东' in c]
        if shares_cols and holder_cols:
            shares = to_float(df[shares_cols[0]].iloc[0], 0)
            holders = to_float(df[holder_cols[0]].iloc[0], 0)
            if holders > 0:
                return shares / holders
        return float('nan')
    except Exception as e:
        print(f'  [data_fetch] fetch_avg_holding({code}) 失败: {e}')
        return float('nan')


# ── 统一采集入口 ──────────────────────────────────────────────


def collect_all(codes: List[str]) -> pd.DataFrame:
    """按股票代码列表获取全部 9 维数据，返回 DataFrame。

    单只失败不影响其他，失败字段填充 NaN。
    """
    if not codes:
        import pandas as pd
        return pd.DataFrame()

    import pandas as pd

    print(f'[data_fetch] 开始采集 {len(codes)} 只股票的 9 维数据...')

    # Step A: 批量获取快照数据（PE、市值、价格等）
    print('[data_fetch] (1/5) 获取行情快照...')
    snapshot = _fetch_snapshot_fields(codes)

    records: List[Dict] = []
    total = len(codes)

    for idx, code in enumerate(codes, 1):
        print(f'[data_fetch] ({idx}/{total}) 处理 {code}...')
        snap = snapshot.get(code, {})

        row: Dict = {
            'code': code,
            'name': snap.get('name', ''),
            'industry': snap.get('industry', ''),
            'market_cap': snap.get('market_cap', float('nan')),
            'pe_ttm': snap.get('pe_ttm', float('nan')),
            'price': snap.get('price', float('nan')),
            'pct_chg': snap.get('pct_chg', float('nan')),
        }

        # (2) 近5日收益率
        try:
            row['return_5d'] = calc_return_5d(code)
        except Exception:
            row['return_5d'] = float('nan')

        # (3) ROE
        row['roe'] = fetch_roe(code)

        # (4) 净利润增长率
        row['net_profit_growth'] = fetch_net_profit_growth(code)

        # (5) 两融差额
        row['margin_balance'] = fetch_margin_balance(code)

        # (6) 资金流向 + 主力持仓比例
        fund = fetch_fund_flow(code)
        row['fund_flow_5d'] = fund['fund_flow_5d']
        row['fund_flow_10d'] = fund['fund_flow_10d']
        row['main_force_ratio'] = fund['main_force_ratio']

        # (7) 户均持股
        row['avg_holding_per_account'] = fetch_avg_holding(code)

        records.append(row)

        # 限速
        if idx < total:
            time.sleep(_DEFAULT_SLEEP)

    df = pd.DataFrame(records)

    # 确保列顺序符合 CSV 定义
    desired_cols = [
        'code', 'name', 'industry', 'market_cap', 'pe_ttm',
        'roe', 'net_profit_growth', 'margin_balance',
        'fund_flow_5d', 'fund_flow_10d', 'avg_holding_per_account',
        'main_force_ratio', 'return_5d', 'price', 'pct_chg',
    ]
    for col in desired_cols:
        if col not in df.columns:
            df[col] = float('nan')
    df = df[desired_cols]

    print(f'[data_fetch] 采集完成，共 {len(df)} 条记录')
    return df
