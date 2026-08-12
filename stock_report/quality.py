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
import re

try:
    from . import timeutil
except ImportError:      # 平铺执行
    import timeutil

# ---- 价格核对（收紧前：25% 硬失败、方向冲突仅软警告）----
HARD_INDEX_PCT = 0.3      # 重点指数偏差 > 0.3% -> 硬失败
HARD_STOCK_PCT = 1.0      # 重点个股偏差 > 1.0% -> 硬失败
HARD_CHG_CONFLICT_ABS = 1.0   # 涨跌方向相反且绝对差 > 1 个百分点 -> 硬失败
SOFT_PRICE_PCT = 0.5
SOFT_CHG_ABS = 0.5

# ---- 覆盖率 ----
COVERAGE_DEGRADE = 0.90   # < 90% 降级
COVERAGE_BLOCK = 0.70     # < 70% 停止正式发送

# ---- 数据活性 ----
# 覆盖率只回答"有没有数字"，回答不了"是不是今天的数字"。2026-08-11 午报实测：
# watchlist_coverage=51/51（100%），而 51 行全部来自 klines_cache/efinance 回填，
# 0 行是当日实时报价——覆盖率门槛判了满分。活性必须单独判。
LIVE_RATIO_DEGRADE = 0.50   # 当日实时报价占比 < 50% 降级

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


INTRADAY_KEYS = ('ai_boards_rt', 'board_stocks_rt', 'capital_flow_top30_rt')


def count_live_rows(latest):
    """返回 (live, total)。live = 当次实时抓取、非回填的行数。

    `is_fallback` 由 provenance 打标：sina/tencent/yfinance 为实时，
    efinance_backfill / klines_cache / stooq 为回填。
    """
    rows = latest.get('watchlist_technicals') or []
    if not rows:
        return 0, 0
    return len([r for r in rows if not r.get('is_fallback')]), len(rows)


def has_intraday_layer(latest):
    """当日盘中层是否存在（板块/成分股/资金流实时榜）。

    观察池全是昨收、但板块与资金流是今日的，这种情况报告仍有实质内容，
    应当降级而不是阻断——2026-08-11 午报就是这样。
    """
    return any(latest.get(key) for key in INTRADAY_KEYS)


def evaluate_liveness(mode, latest):
    """数据活性：这份午报里到底有没有今天的数字。

    刻意与 `evaluate_realtime_claims` 分开——那道门槛只在分析层写了"实时"
    二字时才触发，是措辞检查；这道只看数据本身，不管报告怎么措辞。
    一份 100% 回填的报告，即使小心避开"实时"字样，也必须被标出来。

    早报不适用：早报的基准本来就是最近一个已完成交易日的收盘价。
    """
    if mode != 'afternoon':
        return PASS, '早报以收盘价为基准，不适用活性判定'

    live, total = count_live_rows(latest)
    if total == 0:
        return BLOCK, '观察池为空'

    intraday = has_intraday_layer(latest)
    if live == 0 and not intraday:
        return BLOCK, '午报无任何当日数据：观察池 0 条实时报价，且无板块/资金流盘中层'
    if live == 0:
        return (DEGRADE,
                f'观察池 {total} 只全部为回填数据（0 条当日实时报价），'
                f'仅板块与资金流为当日盘中；个股价格与技术指标均非今日')

    ratio = live / total
    if ratio < LIVE_RATIO_DEGRADE:
        return (DEGRADE,
                f'当日实时报价仅 {live}/{total}（{ratio:.0%}），'
                f'低于 {LIVE_RATIO_DEGRADE:.0%}，多数个股为回填价')
    return PASS, f'当日实时报价 {live}/{total}（{ratio:.0%}）'


def evaluate_data_currency(mode, latest, today=None):
    """午报用的必须是**当日**行情。

    和闭环校验分开的理由：线上实测到一次午报提交了 08-10 遗留的 latest 文件
    （fetch_time 无时区、provenance 为空，说明 cloud_fetch 根本没重新生成）。
    这属于"数据是昨天的"，不是"复盘链断裂"——两者原因不同、修法不同，
    混在一条消息里会把人引向错误的方向。
    """
    if mode != 'afternoon':
        return PASS, ''
    today = today or timeutil.trading_date_bjt('afternoon')
    expected = latest.get('expected_data_date') or \
        (latest.get('data_freshness') or {}).get('expected_date')
    if not expected:
        return DEGRADE, 'latest 缺 expected_data_date，无法判断数据是否当日'
    if expected != today:
        return (BLOCK, f'午报数据非当日：latest 的行情日为 {expected}，'
                       f'当前交易日为 {today}（cloud_fetch 很可能未重新生成）')
    return PASS, f'午报数据为当日 {today}'


def evaluate_continuity(mode, latest, morning_analysis, today=None):
    """早午报闭环：今天有没有一份当日早报可供复盘。

    只比"报告日期"这一件事——午报数据是否当日由 evaluate_data_currency 负责。

    返回 (level, reason, prior_result)。prior_result 为 'pending' 时，调用方
    必须把 analysis.reflection.prior_result 覆盖成 pending，并禁止出现
    "早报预测正确/错误"一类结论。
    """
    if mode != 'afternoon':
        return PASS, '早报无需闭环校验', None

    today = today or timeutil.trading_date_bjt('afternoon')
    morning_date = (morning_analysis or {}).get('date')

    if not morning_date:
        return BLOCK, '当日早报 final 缺失，无法验证早报预测—午盘实际', 'pending'
    if morning_date != today:
        return (BLOCK,
                f'早报 final 是 {morning_date} 的，不是当日（{today}）'
                f'，本期无法结算早报预测', 'pending')
    return PASS, f'早午报闭环成立（{today}）', None


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


def _analysis_haystack(analysis):
    haystack = ' '.join(str((analysis or {}).get(k, '')) for k in
                        ('market_summary', 'sector_analysis', 'hk_us_summary',
                         'review', 'trading_advice'))
    haystack += ' ' + ' '.join(map(str, (analysis or {}).get('key_insights') or []))
    haystack += ' ' + ' '.join(str(r) for r in ((analysis or {}).get('risk_warnings') or []))
    return haystack


def stale_index_rows(latest):
    """外围市场里日期落后于同市场其余行的指数行。

    抓数端（global_markets.py）早就逐行算好了 row_stale 与 stale_rows，
    但一直只是打进日志——verify 从不读，渲染端也不读。也就是说唯一挡在
    陈旧指数和邮件之间的，是模型愿不愿意逐行去看 market_date。
    2026-08-12 实测：^HSI/^HSCE/^KS11/^TWII 四行落后整整一个交易日。
    """
    out = []
    markets = ((latest.get('global_markets') or {}).get('markets') or {})
    for region, block in markets.items():
        if not isinstance(block, dict):
            continue
        for row in (block.get('indices') or []):
            if not isinstance(row, dict) or not row.get('row_stale'):
                continue
            out.append({'region': region, 'code': row.get('code'),
                        'name': row.get('name') or row.get('code'),
                        'chg': row.get('chg'),
                        'row_date': row.get('market_date'),
                        'market_date': block.get('market_date')})
    return out


def _cites_without_dating(haystack, row, window=120):
    """报告是否在没有标注旧日期的情况下引用了这行陈旧指数的涨跌幅。

    在指数名出现的每个 ±window 字窗口里找它的涨跌幅数值；找到了，
    而窗口里既没有该行的真实日期（多种写法）也没有"最近有效时点"这类
    限定语，就判为把旧数据当成了今日数据。
    """
    name, chg, row_date = row.get('name'), row.get('chg'), row.get('row_date') or ''
    if not name or chg is None or not row_date:
        return False
    try:
        figure = f'{abs(float(chg)):.2f}'
    except (TypeError, ValueError):
        return False
    parts = row_date.split('-')
    date_forms = {row_date}
    if len(parts) == 3:
        mm, dd = parts[1], parts[2]
        date_forms |= {f'{mm}-{dd}', f'{int(mm)}/{int(dd)}', f'{mm}/{dd}',
                       f'{int(mm)}月{int(dd)}日', f'{int(mm)}-{int(dd)}'}
    qualifiers = ('最近有效', 'unavailable', '滞后', '非当日', '上一个交易日')
    for m in re.finditer(re.escape(name), haystack):
        w = haystack[max(0, m.start() - window):m.end() + window]
        if figure not in w:
            continue
        if any(d in w for d in date_forms) or any(q in w for q in qualifiers):
            continue
        return True
    return False


def evaluate_global_index_staleness(latest, analysis=None):
    """外围指数行滞后一个交易日时的两级判定。

    返回 (level, reason, detail)。detail['misattributed'] 非空时，verify 记
    **硬失败**（逼一次重生成）；否则 DEGRADE 只记软警告。不设 BLOCK：
    港股指数陈旧不足以让整份 A 股报告不发。
    """
    rows = stale_index_rows(latest)
    detail = {'stale_rows': rows, 'misattributed': []}
    if not rows:
        return PASS, '', detail
    haystack = _analysis_haystack(analysis) if analysis else ''
    bad = [r for r in rows if _cites_without_dating(haystack, r)]
    detail['misattributed'] = bad
    if bad:
        names = '、'.join(f"{r['name']} {float(r['chg']):+.2f}%（实为 {r['row_date']} 的数据）"
                          for r in bad)
        return DEGRADE, f'报告把落后一个交易日的指数当作当日数据引用：{names}', detail
    listed = '、'.join(f"{r['name']}({r['code']}) 数据日 {r['row_date']}"
                       f"、同市场其余行为 {r['market_date']}" for r in rows)
    return DEGRADE, f'外围指数行滞后一个交易日，不可用于描述当日行情：{listed}', detail


def combine(*levels):
    """多个门槛取最严。"""
    return _rank(PASS, *levels) if levels else PASS


def exit_code_for(level):
    """0=可发，2=硬失败但仍发（带降级横幅），3=停止正式发送。"""
    return {PASS: 0, DEGRADE: 0, BLOCK: 3}[level]
