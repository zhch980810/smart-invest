"""
量化工具模块。

提供:
  - score_policy(stock, policy) — 根据政策信号对股票打分
  - infer_sector(stock) — 根据名称/行业推断板块分类
"""

from typing import Dict

SECTOR_NAME_RULES = [
    ('半导体', ['芯', '半导体', '集成电路']),
    ('电力设备', ['电力', '电网', '储能', '特高压', '变压器']),
    ('高端制造', ['激光', '机器人', '机床', '自动化', '精工', '液压']),
    ('能源', ['能源', '煤', '油', '气']),
    ('医药', ['药', '医疗', '生物']),
    ('消费', ['酒', '食品', '乳', '家电', '零售']),
    ('TMT', ['信息', '科技', '软件', '通信', '电子']),
]


def score_policy(stock: Dict, policy: Dict) -> Dict:
    """根据政策主题关键词匹配打分，返回 {policy_score, policy_hits}"""
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


def infer_sector(stock: Dict) -> str:
    """根据行业/名称推断板块分类"""
    txt = f"{stock.get('industry', '')} {stock.get('name', '')}"
    for sector, kws in SECTOR_NAME_RULES:
        if any(k in txt for k in kws):
            return sector
    return stock.get('industry') or '其他'
