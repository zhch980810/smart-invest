import json
import time
from typing import Dict, List, Tuple

import requests

SINA_QUOTE_URL = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
EAST_KLINE_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
TENCENT_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
SINA_KLINE_URL = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn/'}
EASTMONEY_HEADERS = {'Referer': 'https://quote.eastmoney.com/'}
TENCENT_HEADERS = {'Referer': 'https://gu.qq.com/'}


def request_with_retry(request_fn, retries=3, sleep_sec=1.2):
    last_err = None
    for _ in range(retries):
        try:
            return request_fn()
        except Exception as e:
            last_err = e
            time.sleep(sleep_sec)
    raise RuntimeError(f'请求失败: {last_err}')


def http_get(url: str, *, params: Dict = None, timeout: int = 12, headers: Dict = None, encoding: str = None):
    merged_headers = DEFAULT_HEADERS.copy()
    if headers:
        merged_headers.update(headers)
    resp = requests.get(url, params=params, headers=merged_headers, timeout=timeout)
    resp.raise_for_status()
    if encoding:
        resp.encoding = encoding
    return resp


def to_float(v, default=0.0) -> float:
    try:
        if v is None or v == '':
            return default
        return float(v)
    except Exception:
        return default


def fetch_snapshot(max_api_calls: int = 50, per_page: int = 100) -> Tuple[List[Dict], int]:
    if max_api_calls <= 0:
        raise RuntimeError('max_api_calls 必须大于 0。')

    rows: List[Dict] = []
    api_calls_used = 0

    for page in range(1, max_api_calls + 1):
        resp = request_with_retry(
            lambda: http_get(
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
                headers=SINA_HEADERS,
            )
        )
        api_calls_used += 1

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
            amount = to_float(v.get('amount'))

            rows.append({
                'code': code,
                'name': name,
                'price': price,
                'pct_chg': pct_chg,
                'amount': amount,
                'amplitude': amplitude,
                'turnover': to_float(v.get('turnoverratio')),
                'pe_ttm': to_float(v.get('per')),
                'market_cap': to_float(v.get('mktcap')) * 10000.0,
                'float_cap': to_float(v.get('nmc')) * 10000.0,
                'pb': to_float(v.get('pb')),
                'industry': str(v.get('industry') or '').strip(),
            })

    if not rows:
        raise RuntimeError('新浪接口返回为空，无法构建股票池。')

    return rows, api_calls_used


def code_to_secid(code: str) -> str:
    return f'1.{code}' if code.startswith(('5', '6')) else f'0.{code}'


def fetch_kline_eastmoney(code: str, lookback: int = 60) -> Tuple[List[float], List[float], List[float]]:
    secid = code_to_secid(code)
    resp = request_with_retry(
        lambda: http_get(
            EAST_KLINE_URL,
            params={
                'secid': secid,
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'klt': '101',
                'fqt': '1',
                'end': '20500101',
                'lmt': str(lookback),
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
            },
            timeout=10,
            headers=EASTMONEY_HEADERS,
        ),
        retries=2,
        sleep_sec=0.6,
    )
    data = resp.json().get('data') or {}
    klines = data.get('klines') or []
    closes, highs, lows = [], [], []
    for line in klines:
        parts = line.split(',')
        if len(parts) < 5:
            continue
        closes.append(to_float(parts[2]))
        highs.append(to_float(parts[3]))
        lows.append(to_float(parts[4]))
    return closes, highs, lows


def fetch_kline_tencent(code: str, lookback: int = 60) -> Tuple[List[float], List[float], List[float]]:
    symbol = ('sh' if code.startswith(('5', '6')) else 'sz') + code
    resp = request_with_retry(
        lambda: http_get(
            TENCENT_KLINE_URL,
            params={'param': f'{symbol},day,,,{lookback},qfq'},
            timeout=10,
            headers=TENCENT_HEADERS,
        ),
        retries=2,
        sleep_sec=0.6,
    )
    raw = resp.text.strip()
    if raw.startswith('jsonp'):
        raw = raw[raw.find('(') + 1: raw.rfind(')')]
    j = json.loads(raw)
    arr = (((j.get('data') or {}).get(symbol) or {}).get('qfqday') or [])
    closes, highs, lows = [], [], []
    for row in arr:
        if len(row) < 5:
            continue
        closes.append(to_float(row[2]))
        highs.append(to_float(row[3]))
        lows.append(to_float(row[4]))
    return closes, highs, lows


def fetch_kline_sina(code: str, lookback: int = 60) -> Tuple[List[float], List[float], List[float]]:
    symbol = ('sh' if code.startswith(('5', '6')) else 'sz') + code
    resp = request_with_retry(
        lambda: http_get(
            SINA_KLINE_URL,
            params={'symbol': symbol, 'scale': '240', 'ma': 'no', 'datalen': str(lookback)},
            timeout=10,
            headers=SINA_HEADERS,
        ),
        retries=2,
        sleep_sec=0.6,
    )
    rows = resp.json() or []
    closes, highs, lows = [], [], []
    for row in rows:
        closes.append(to_float(row.get('close')))
        highs.append(to_float(row.get('high')))
        lows.append(to_float(row.get('low')))
    return closes, highs, lows
