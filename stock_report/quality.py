#!/usr/bin/env python3
"""发送前的确定性质量门槛。

原来的关卡只有两档：通过 / 硬失败，而硬失败**照样发信**（只加降级横幅）。
结果是"数据烂到不能用"和"数据有点旧"走同一条路，自动发信没有真正的刹车。

这里把判定拆成三档，并把每一档的阈值写成常量，便于回归测试：

    PASS      正常发送
    DEGRADE   发送，但必须带降级说明，禁止出现"实时"等确定性措辞
    BLOCK     **停止正式发送**（退出码 3）。只在数据不足以支撑一份负责任的
              报告时触发：关注池覆盖率过低、或早午报闭环断裂。

阈值取值依据：指数是全市场锚点，0.3% 已经是一根明显的假数字；个股 1% 在
盘中属于正常波动区间之外的偏差；方向冲突说明两个源看到的不是同一个时点。
"""

# ---- 价格核对（收紧前：25% 硬失败、方向冲突仅软警告）----
HARD_INDEX_PCT = 0.3      # 重点指数偏差 > 0.3% -> 硬失败
HARD_STOCK_PCT = 1.0      # 重点个股偏差 > 1.0% -> 硬失败
HARD_CHG_CONFLICT_ABS = 1.0   # 涨跌方向相反且绝对差 > 1 个百分点 -> 硬失败
SOFT_PRICE_PCT = 0.5
SOFT_CHG_ABS = 0.5

# ---- 覆盖率 ----
COVERAGE_DEGRADE = 0.90   # < 90% 降级
COVERAGE_BLOCK = 0.70     # < 70% 停止正式发送

# 声称"实时"的措辞
REALTIME_CLAIMS = ('实时', '此刻', '当前最新价', '正在交易')
# 允许自称实时的两种情形：① 15 分钟以内；② 市场再没有更新的数据了（收盘价）。
# 所以判据是"落后于市场最新可得数据多少秒"，而不是"距此刻多少秒"——
# 收盘后拿当日收盘价，距此刻可能好几个小时，但它确实就是最新的。
INTRADAY_STALE_LIMIT = 900

PASS, DEGRADE, BLOCK = 'pass', 'degrade', 'block'


def _rank(*levels):
    order = {PASS: 0, DEGRADE: 1, BLOCK: 2}
    return max(levels, key=lambda lv: order[lv])


def parse_coverage(latest):
    """返回 (priced, total, ratio)。优先用真实行数，退回 data_quality 字符串。"""
    rows = latest.get('watchlist_technicals') or []
    if rows:
        priced = len([r for r in rows if r.get('chg_pct') is not None])
        total = len(rows)
        # watchlist_technicals 只含抓到的股票，分母要用宇宙规模
        declared = str((latest.get('data_quality') or {}).get('watchlist_coverage', ''))
        if '/' in declared:
            try:
                total = max(total, int(declared.split('/')[1]))
            except (ValueError, IndexError):
                pass
        return priced, total, (priced / total if total else 0.0)

    declared = str((latest.get('data_quality') or {}).get('watchlist_coverage', ''))
    if '/' in declared:
        try:
            priced, total = (int(x) for x in declared.split('/')[:2])
            return priced, total, (priced / total if total else 0.0)
        except (ValueError, IndexError):
            pass
    return 0, 0, 0.0


def evaluate_coverage(latest):
    """关注池覆盖率门槛。"""
    priced, total, ratio = parse_coverage(latest)
    detail = f'关注池覆盖率 {priced}/{total}（{ratio:.0%}）'
    if total == 0:
        return BLOCK, '关注池为空，无法核对任何数字'
    if ratio < COVERAGE_BLOCK:
        return BLOCK, f'{detail}，低于停发线 {COVERAGE_BLOCK:.0%}'
    if ratio < COVERAGE_DEGRADE:
        return DEGRADE, f'{detail}，低于降级线 {COVERAGE_DEGRADE:.0%}'
    return PASS, detail


def evaluate_continuity(mode, latest, morning_analysis):
    """早午报闭环：午报必须能对上当日早报，否则复盘结论不成立。

    返回 (level, reason, prior_result)。prior_result 为 'pending' 时，调用方
    必须把 analysis.reflection.prior_result 覆盖成 pending，并禁止出现
    "早报预测正确/错误"一类结论。
    """
    if mode != 'afternoon':
        return PASS, '早报无需闭环校验', None

    expected = latest.get('expected_data_date') or \
        (latest.get('data_freshness') or {}).get('expected_date')
    morning_date = (morning_analysis or {}).get('date')

    if not morning_date:
        return BLOCK, '当日早报 final 缺失，无法验证早报预测—午盘实际', 'pending'
    if not expected:
        return DEGRADE, 'latest 缺 expected_data_date，闭环无法判定', 'pending'
    if morning_date != expected:
        return (BLOCK,
                f'早报 final 日期 {morning_date} ≠ 本次期望行情日 {expected}，'
                f'复盘链断裂', 'pending')
    return PASS, f'早午报闭环成立（{expected}）', None


def _realtime_hits(analysis):
    haystack = ' '.join(str(analysis.get(k, '')) for k in
                        ('market_summary', 'sector_analysis', 'hk_us_summary', 'review'))
    haystack += ' ' + ' '.join(map(str, analysis.get('key_insights') or []))
    return [w for w in REALTIME_CLAIMS if w in haystack]


def evaluate_realtime_claims(latest, analysis, mode=None):
    """"不许自称实时"的两条判据。

    ① 日期级：stale_quote_count > 0，说明有报价压根不是当日的。
    ② 落后市场：数据比"市场最新可得"旧了 15 分钟以上。

    第二条刻意不用"距此刻多少秒"：收盘后拿当日收盘价，距此刻可能几个小时，
    但市场再没有更新的数据了，称其为最新完全成立。只有当市场已经走出新价格、
    而我们手上还是旧快照时，"实时"才是错的。
    """
    hits = _realtime_hits(analysis)
    if not hits:
        return PASS, ''

    stale_count = (latest.get('data_freshness') or {}).get('stale_quote_count', 0)
    if isinstance(stale_count, int) and stale_count > 0:
        return DEGRADE, f'存在 {stale_count} 条非当日报价却使用了确定性措辞 {hits}'

    behind = ((latest.get('data_quality') or {}).get('provenance') or {}) \
        .get('seconds_behind_market')
    if isinstance(behind, (int, float)) and behind > INTRADAY_STALE_LIMIT:
        return DEGRADE, (f'数据落后市场最新可得 {behind / 60:.0f} 分钟（超过 '
                         f'{INTRADAY_STALE_LIMIT // 60} 分钟）却使用了确定性措辞 {hits}')
    return PASS, ''


def combine(*levels):
    """多个门槛取最严。"""
    return _rank(PASS, *levels) if levels else PASS


def exit_code_for(level):
    """0=可发，2=硬失败但仍发（带降级横幅），3=停止正式发送。"""
    return {PASS: 0, DEGRADE: 0, BLOCK: 3}[level]
