#!/usr/bin/env python3
"""关键数据双源交叉验证。

不需要给 50 只股票都查两个源——那样只是把请求量翻倍。真正会进入报告结论、
一旦错就会误导判断的只有四类：

  1. 四个指数（全市场锚点）
  2. 当日涨跌幅绝对值最大的 N 只关注股（最容易被写进"异动追因"）
  3. 最终进入 stock_highlights 的股票
  4. 领涨 / 领跌板块的龙头股

对这些标的同时取新浪与腾讯，价格差超过阈值时**不静默选一个**，而是标记
`source_conflict`，让分析层知道"这个数字两个源对不上"。静默择一是最危险的
做法：报告读起来一样确定，但你不知道它信了哪个。
"""

CROSSCHECK_TOLERANCE_PCT = 0.5   # 双源价格差 > 0.5% 记为冲突
TOP_MOVERS = 10


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


INDEX_CODES = ('000001', '399001', '399006', '000688')


def select_crosscheck_targets(latest, highlight_codes=(), top_movers=TOP_MOVERS):
    """返回需要双源核对的证券代码集合。"""
    targets = set(INDEX_CODES)

    movers = sorted(
        (r for r in (latest.get('watchlist_technicals') or [])
         if _f(r.get('chg_pct')) is not None),
        key=lambda r: -abs(_f(r.get('chg_pct')) or 0.0),
    )[:top_movers]
    targets.update(str(r.get('code')) for r in movers if r.get('code'))

    targets.update(str(c) for c in highlight_codes if c)

    for sector in (latest.get('sectors') or []):
        for role in ('leader', 'laggard'):
            code = (sector.get(role) or {}).get('code')
            if code:
                targets.add(str(code))

    return {c for c in targets if c}


def compare_quotes(code, primary, secondary, tolerance_pct=CROSSCHECK_TOLERANCE_PCT):
    """比较同一标的在两个源上的价格。一致或数据不足返回 None。"""
    pp = _f((primary or {}).get('price'))
    sp = _f((secondary or {}).get('price'))
    if pp is None or sp is None or pp == 0 or sp == 0:
        return None
    diff_pct = abs(pp - sp) / pp * 100
    if diff_pct <= tolerance_pct:
        return None
    return {
        'code': code,
        'primary_source': (primary or {}).get('src', 'primary'),
        'primary_price': round(pp, 4),
        'secondary_source': (secondary or {}).get('src', 'secondary'),
        'secondary_price': round(sp, 4),
        'diff_pct': round(diff_pct, 3),
        'primary_date': (primary or {}).get('date', ''),
        'secondary_date': (secondary or {}).get('date', ''),
    }


def cross_validate(primary_map, secondary_map, targets,
                   tolerance_pct=CROSSCHECK_TOLERANCE_PCT):
    """对 targets 逐个比价，返回冲突列表（已按差异从大到小排序）。

    primary_map / secondary_map 的 key 是带交易所前缀的代码（如 sh600522），
    targets 是裸代码（600522）；两边用后 6 位对齐。
    """
    def index_by_bare(quote_map):
        out = {}
        for key, value in (quote_map or {}).items():
            bare = str(key)[-6:]
            out.setdefault(bare, value)
        return out

    primary_bare = index_by_bare(primary_map)
    secondary_bare = index_by_bare(secondary_map)

    conflicts = []
    for code in sorted(targets):
        bare = str(code)[-6:]
        conflict = compare_quotes(code, primary_bare.get(bare),
                                  secondary_bare.get(bare), tolerance_pct)
        if conflict:
            conflicts.append(conflict)
    conflicts.sort(key=lambda c: -c['diff_pct'])
    return conflicts


def summarize(conflicts):
    """给 data_quality 用的紧凑摘要。"""
    return {
        'checked_conflicts': len(conflicts),
        'max_diff_pct': conflicts[0]['diff_pct'] if conflicts else 0.0,
        'codes': [c['code'] for c in conflicts[:10]],
    }
