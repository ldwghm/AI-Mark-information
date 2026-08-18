"""价格与主力资金的背离。

要检测的是两件事：

    拉高派发   股价明显上涨，主力资金却在净流出
    逆势承接   股价明显下跌，主力资金却在净流入

**口径警告（必须随数字一起说出去）**：东财的"主力/超大单/大单/中单/小单"
是按**单笔成交金额**机械划分的，不是按账户性质。量化算法拆单会把一笔大资金
打散成中小单，龙虎榜席位也不会因为单笔小就变成散户。所以这里得到的是
"大额单方向与价格方向不一致"，**不等于"机构在出货"**。写进报告时要用
"大额资金净流出"这类表述，不要写成"机构派发"。

阈值来源：2026-08-13 早报快照 130 只样本，f184（主力净占比）中位 +7.2%、
p10 −0.5%、区间 [−11.2, +40.9]。取 ∓1.0% 大致落在分布尾部约 8%，
涨跌幅取 ∓3.0% 以排除噪声。**这是单日样本的经验标定，不是普适常数**，
样本换了要重标——所以阈值是显式参数，且会写进输出。
"""

# 单日样本标定，见模块 docstring
CHG_THRESHOLD = 3.0        # 涨跌幅绝对值下限（%）
FLOW_THRESHOLD = 1.0       # 主力净占比绝对值下限（%）

DISTRIBUTION = 'distribution'   # 涨 + 主力净流出
ACCUMULATION = 'accumulation'   # 跌 + 主力净流入

_LABEL = {
    DISTRIBUTION: '涨但大额资金净流出',
    ACCUMULATION: '跌但大额资金净流入',
}


def _num(value):
    return value if isinstance(value, (int, float)) and value == value else None


def classify(row, chg_threshold=CHG_THRESHOLD, flow_threshold=FLOW_THRESHOLD):
    """判定单行。返回 dict，或 None 表示不构成背离。

    row 用东财 clist 的原始字段：f3 涨跌幅%、f184 主力净占比%、f62 主力净额（元）、
    f66 超大单净额（元）、f8 换手率%、f12 代码、f14 名称。
    """
    chg = _num((row or {}).get('f3'))
    flow_pct = _num((row or {}).get('f184'))
    if chg is None or flow_pct is None:
        return None

    if chg >= chg_threshold and flow_pct <= -flow_threshold:
        kind = DISTRIBUTION
    elif chg <= -chg_threshold and flow_pct >= flow_threshold:
        kind = ACCUMULATION
    else:
        return None

    big = _num(row.get('f66'))
    # 超大单是否与主力同向。不同向说明"主力"这个合计口径内部就有分歧，
    # 信号该降级——这正是单笔金额分类不可靠的地方。
    if big is None:
        big_agrees = None
    elif kind == DISTRIBUTION:
        big_agrees = big < 0
    else:
        big_agrees = big > 0

    return {
        'code': row.get('f12'),
        'name': row.get('f14'),
        'kind': kind,
        'label': _LABEL[kind],
        'chg_pct': chg,
        'main_net_pct': flow_pct,
        'main_net_amount': _num(row.get('f62')),
        'super_net_amount': big,
        'super_agrees': big_agrees,
        'turnover_rate': _num(row.get('f8')),
        'strength': abs(flow_pct),
    }


def scan(rows, chg_threshold=CHG_THRESHOLD, flow_threshold=FLOW_THRESHOLD, limit=None):
    """扫一批行，按强度降序返回。同一代码只保留强度最大的一条。"""
    best = {}
    for row in rows or []:
        hit = classify(row, chg_threshold, flow_threshold)
        if not hit:
            continue
        code = hit.get('code')
        if code is None:
            continue
        if code not in best or hit['strength'] > best[code]['strength']:
            best[code] = hit
    out = sorted(best.values(), key=lambda h: h['strength'], reverse=True)
    return out[:limit] if limit else out


def collect_rows(snapshot):
    """从快照里把所有带资金字段的个股行汇总去重。

    三个来源：AI 板块涨幅榜（board_stocks）、板块跌幅榜（board_laggards）、
    全市场主力净流入榜（capital_flow_top30）。**没有 board_laggards 就
    检测不到逆势承接**——前两个来源都只装上涨股（08-13 快照 130 只里
    涨跌幅最小值是 +0.9%）。
    """
    rows = {}
    for board in (snapshot or {}).get('board_stocks') or []:
        for row in board.get('stocks') or []:
            if row.get('f12'):
                rows[row['f12']] = row
    for board in (snapshot or {}).get('board_laggards') or []:
        for row in board.get('stocks') or []:
            if row.get('f12'):
                rows.setdefault(row['f12'], row)
    for row in (snapshot or {}).get('capital_flow_top30') or []:
        if row.get('f12'):
            rows.setdefault(row['f12'], row)
    return list(rows.values())


def analyse(snapshot, limit=8):
    """快照 → 背离摘要。附口径说明，供渲染层原样带出。"""
    rows = collect_rows(snapshot)
    hits = scan(rows, limit=None)
    has_decliners = any(_num(r.get('f3')) is not None and _num(r.get('f3')) < 0
                        for r in rows)
    return {
        'scanned': len(rows),
        'thresholds': {'chg_pct': CHG_THRESHOLD, 'main_net_pct': FLOW_THRESHOLD},
        'distribution': [h for h in hits if h['kind'] == DISTRIBUTION][:limit],
        'accumulation': [h for h in hits if h['kind'] == ACCUMULATION][:limit],
        # 样本里没有下跌股时，"没检出逆势承接"是取数口径造成的，不是市场事实
        'accumulation_detectable': has_decliners,
        'caveat': ('主力/超大单按单笔成交金额机械划分，量化拆单会把大资金打散，'
                   '故本项只说明大额单方向与价格方向不一致，不等于机构在出货'),
    }
