#!/usr/bin/env python3
"""分析质量验证关卡（确定性检查器）。

在 LLM 生成 <mode>_analysis.json 之后、commit/push 之前运行。
Loop Engineering 里"做的和验的分开"：写分析的是 LLM，验的是这个确定性脚本——
"分析里的数字是否真的来自抓取数据"恰好可以机器判定，比再叫模型打分更可靠、更省 token。

标定原则（重要）：本系统数据多源、降级常态（盘中快照 / 部分个股缺数据 / 港美股不可用），
因此只把**严重矛盾**判为硬失败，避免天天误报：
  - 硬失败(exit 2)：① 完全无任何行情数据；② highlight 报的价格较可靠源(新浪个股池)偏离 >25%
    或涨跌幅符号翻转且绝对差 >5 个百分点（典型编造特征）。
  - 软警告(exit 0, degraded=True)：数据不新鲜、key_insight 缺数字、港美股空缺未标注、
    highlight 数字与个股池有轻微出入或仅能在板块汇总里找到。软警告允许发出，但邮件带降级横幅。

用法:
    python3 verify.py --mode morning
    python3 verify.py --mode morning --latest path/to/x_latest.json --analysis path/to/x_analysis.json   # 本地测试
退出码: 0=通过(可能 degraded)，2=硬失败(调用方：重生成一次；再失败则降级发出+Gmail告警)
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:                                  # 作为包导入（GitHub Actions: python -m / import）
    from . import quality
except ImportError:                   # 直接执行 verify.py（本地调试、云端 curl 到 /tmp）
    import quality

# 阈值集中在 quality.py，便于回归测试；这里只做别名
HARD_PRICE_PCT = quality.HARD_STOCK_PCT        # 个股偏差 > 1% → 硬失败（原为 25%）
HARD_INDEX_PCT = quality.HARD_INDEX_PCT        # 指数双源偏差 > 0.3% → 硬失败
HARD_CHG_FLIP_ABS = quality.HARD_CHG_CONFLICT_ABS  # 方向冲突且差 > 1pct → 硬失败（原为软警告）
SOFT_PRICE_PCT = quality.SOFT_PRICE_PCT
SOFT_CHG_ABS = quality.SOFT_CHG_ABS
BANNED_VAGUE = ['建议关注', '保持谨慎', '注意风险', '择机', '逢低', '逢高']
INDEX_CODES = frozenset({'000001', '399001', '399006', '000688'})


def verdict_path_for(analysis_path):
    """Return a verdict path that cannot overwrite the analysis candidate."""
    path = Path(analysis_path)
    if path.stem.endswith('_analysis'):
        return path.with_name(path.stem[:-9] + '_verdict.json')
    return path.with_name(path.stem + '_verdict.json')


def has_digit(s):
    return bool(re.search(r'\d', str(s)))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def merge_hk_us(latest, analysis):
    """原 Step 4.5：确定性地把 latest 港美股补进 analysis（渲染端读 analysis.hk_stocks）。"""
    changed = False
    if latest.get('hk_stocks') and not analysis.get('hk_stocks'):
        analysis['hk_stocks'] = latest['hk_stocks']; changed = True
    if latest.get('us_stocks') and not analysis.get('us_stocks'):
        analysis['us_stocks'] = latest['us_stocks']; changed = True
    hk = analysis.get('hk_stocks', []); us = analysis.get('us_stocks', [])
    summary = analysis.get('hk_us_summary', '')
    if (hk or us) and (not summary or any(w in summary for w in ['暂无', '无法获取', '网络', '限制', '暂未'])):
        parts = [f"{s['name']}({s['code']}){s['price']},涨跌{s.get('chg', 0):+.2f}%" for s in (hk + us)]
        analysis['hk_us_summary'] = '港美股AI龙头最新：' + '；'.join(parts[:8]) + '。'
        changed = True
    return changed


def _fill(idx, code, price, chg):
    """把非空数值填进 idx[code]（已有非空值不覆盖，仅补空）。"""
    if not code:
        return
    cur = idx.setdefault(code, {'price': None, 'chg_pct': None})
    if cur['price'] is None and price is not None:
        cur['price'] = price
    if cur['chg_pct'] is None and chg is not None:
        cur['chg_pct'] = chg


def build_indices(latest):
    """返回 (primary, ef_index)。
    primary:  code -> {price, chg_pct} 来自新浪个股池（可靠，形状已知）；realtime(current) 优先，再补 close。用于硬核对。
    ef_index: code -> {price, chg_pct} 来自 efinance 板块成分股/资金流榜(f2/f3)；量纲不完全可控，仅作软核对/存在性。"""
    primary = {}
    for row in latest.get('watchlist_rt', []) or []:   # realtime 优先
        _fill(primary, str(row.get('code', '')), _f(row.get('current')), _f(row.get('change_pct')))
    for row in latest.get('watchlist_technicals', []) or []:  # 补空
        _fill(primary, str(row.get('code', '')), _f(row.get('close')), _f(row.get('chg_pct')))

    ef_index = {}
    for grp in (latest.get('board_stocks', []) or []) + (latest.get('board_stocks_rt', []) or []):
        for s in grp.get('stocks', []) or []:
            _fill(ef_index, str(s.get('f12', '')), _f(s.get('f2')), _f(s.get('f3')))
    for s in (latest.get('capital_flow_top30', []) or []) + (latest.get('capital_flow_top30_rt', []) or []):
        _fill(ef_index, str(s.get('f12', '')), _f(s.get('f2')), _f(s.get('f3')))
    return primary, ef_index


def build_provenance_index(latest):
    """code -> {as_of, is_fallback, source}，来自观察池两个数组。"""
    index = {}
    for row in (latest.get('watchlist_rt', []) or []) + \
               (latest.get('watchlist_technicals', []) or []):
        code = str(row.get('code', ''))
        if code and code not in index and row.get('source'):
            index[code] = {'as_of': row.get('as_of'),
                           'is_fallback': bool(row.get('is_fallback')),
                           'source': row.get('source')}
    return index


def build_intraday_index(latest):
    """code -> 当日盘中价，仅取 *_rt 实时榜（efinance 今日数据）。

    用来发现"highlight 写的是昨收，但这只股票今天明明有盘中价"这种情况。
    """
    index = {}
    for grp in latest.get('board_stocks_rt', []) or []:
        for s in grp.get('stocks', []) or []:
            code = str(s.get('f12', ''))
            if code and code not in index:
                index[code] = (_f(s.get('f2')), _f(s.get('f3')))
    for s in latest.get('capital_flow_top30_rt', []) or []:
        code = str(s.get('f12', ''))
        if code and code not in index:
            index[code] = (_f(s.get('f2')), _f(s.get('f3')))
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['morning', 'afternoon'])
    ap.add_argument('--latest')
    ap.add_argument('--analysis')
    ap.add_argument('--verdict')
    ap.add_argument('--morning-analysis', dest='morning_analysis',
                    default='stock_report/data/morning_analysis.json',
                    help='午报闭环校验用的当日早报 final')
    ap.add_argument('--allow-open-loop', dest='allow_open_loop', action='store_true',
                    help='影子验证期使用：闭环断裂时降级而不阻断发送')
    ap.add_argument('--today', default=None,
                    help='覆盖"当前交易日"（YYYY-MM-DD）。回放归档 bundle 或跑测试时用，'
                         '生产环境不要传——传了就等于把日期校验的基准也一起伪造了')
    args = ap.parse_args()
    mode = args.mode
    lpath = args.latest or f'/tmp/{mode}_latest.json'
    apath = args.analysis or f'/tmp/{mode}_analysis.json'

    latest = json.load(open(lpath, encoding='utf-8-sig'))
    analysis = json.load(open(apath, encoding='utf-8-sig'))

    morning_analysis = {}
    if mode == 'afternoon' and args.morning_analysis:
        mpath = Path(args.morning_analysis)
        if mpath.is_file():
            try:
                morning_analysis = json.loads(mpath.read_text(encoding='utf-8-sig'))
            except (ValueError, OSError) as exc:
                print(f'morning analysis unreadable: {exc}')

    merge_hk_us(latest, analysis)  # Step 4.5 折叠进来

    # 丢弃 0/空价的港美股占位（agent 偶尔会编"腾讯 0"），宁可诚实留空
    for fld in ('hk_stocks', 'us_stocks'):
        orig = analysis.get(fld) or []
        kept = [s for s in orig if _f(s.get('price')) not in (None, 0)]
        if len(kept) != len(orig):
            analysis[fld] = kept
    if not analysis.get('hk_stocks') and not analysis.get('us_stocks'):
        summ = str(analysis.get('hk_us_summary', ''))
        if (not summ) or re.search(r'0\.00|\(0\)|涨跌\s*\+?0(?!\d)', summ):
            analysis['hk_us_summary'] = '港股/美股实时行情接口在云端不可用，本期不含港美股报价，请以券商行情为准。'

    hard = []     # 硬失败
    soft = []     # 软警告（降级但允许发）
    primary, ef_index = build_indices(latest)
    has_any = any(v['price'] is not None for v in primary.values()) or \
              any(v['price'] is not None for v in ef_index.values())

    # 1) 完全无数据
    if not has_any:
        hard.append('latest.json 无任何可用行情数值（个股池/板块/资金流均无价格）')

    # 2) 新鲜度
    fresh = latest.get('data_freshness', {})
    expected = latest.get('expected_data_date') or fresh.get('expected_date')
    qmode = fresh.get('quote_date_mode')
    stale = fresh.get('stale_quote_count', 0)
    # 行情非实时（云端连不上新浪/雅虎、价格来自 efinance 回填）→ 必须降级提示
    dq = latest.get('data_quality', {})
    conf = dq.get('index_data_confidence')
    if conf and conf != 'high':
        soft.append(f"行情非实时（来源 {dq.get('quote_source', '?')}，置信度 {conf}）：{dq.get('caveat', '')}"[:90])
    if qmode and expected and qmode < expected:
        soft.append(f'行情主日期 {qmode} 早于期望 {expected}（数据延迟）')
    if isinstance(stale, int) and primary and stale > len(primary) * 0.5:
        soft.append(f'过期报价占比偏高（{stale} 条）')
    if soft and 'risk_warnings' in analysis:
        rw = ' '.join(map(str, analysis.get('risk_warnings', [])))
        if not re.search(r'延迟|滞后|快照|盘中|\d{1,2}日|未更新|非实时|非收盘', rw):
            soft.append('数据有延迟/快照但 risk_warnings 未明确标注')

    # 3) 数字核对（核心）
    weak = 0
    prov_index = build_provenance_index(latest)
    intraday_index = build_intraday_index(latest)
    stale_highlights = []
    for h in analysis.get('stock_highlights', []) or []:
        code = str(h.get('code', ''))
        nm = h.get('name', '?')
        hp, hcg = _f(h.get('price')), _f(h.get('chg_pct'))

        # 给 price 字段本身打上时点标识——邮件表格渲染的就是这个数字，
        # 把口径写在 comment 散文里不够：扫表格的读者看不到。
        prov = prov_index.get(code)
        if prov:
            h['price_as_of'] = prov['as_of']
            h['price_is_fallback'] = prov['is_fallback']
            h['price_source'] = prov['source']
        # 这只股票今天明明有盘中价，highlight 却写了回填价 -> 表格会显示反向行情
        today_px = intraday_index.get(code, (None, None))[0]
        if prov and prov['is_fallback'] and today_px and hp and \
                abs(today_px - hp) / hp * 100 > SOFT_PRICE_PCT:
            h['intraday_price'] = today_px
            stale_highlights.append(f'{nm}({code}) 表格价 {hp}（{prov["source"]}回填）'
                                    f'但今日盘中为 {today_px}')

        ref = primary.get(code)
        if ref and ref['price'] is not None:   # 可靠源：硬核对
            sp, scg = ref['price'], ref['chg_pct']
            if hp:
                dev = abs(hp - sp) / sp * 100
                if dev > HARD_PRICE_PCT:
                    hard.append(f'{nm}({code}) price 报 {hp} 实际 {sp}（偏离{dev:.0f}%）')
                elif dev > SOFT_PRICE_PCT:
                    soft.append(f'{nm}({code}) price 报 {hp} 实际 {sp}（偏离{dev:.0f}%）')
            if scg is not None and hcg is not None:
                if (scg > 0) != (hcg > 0) and abs(hcg - scg) > HARD_CHG_FLIP_ABS:
                    hard.append(f'{nm}({code}) 涨跌方向相反 报{hcg} 实际{scg}（差{abs(hcg - scg):.2f}pct）')
                elif abs(hcg - scg) > SOFT_CHG_ABS:
                    soft.append(f'{nm}({code}) chg_pct 报 {hcg} 实际 {scg}')
        elif ef_index.get(code) and ef_index[code]['price'] is not None:  # 仅 efinance：软核对（量纲不完全可控）
            sp = ef_index[code]['price']
            if hp and abs(hp - sp) / sp * 100 > 30:
                soft.append(f'{nm}({code}) price 报 {hp} 与板块汇总 {sp} 差距大')
            weak += 1
        else:
            soft.append(f'{nm}({code}) 不在任何抓取数据中（无法核对）')
    if weak:
        soft.append(f'{weak} 只 highlight 数字仅来自板块汇总，未在个股池二次核对')

    # 4) key_insights 必须含数字
    no_digit = [k for k in (analysis.get('key_insights') or []) if not has_digit(k)]
    if no_digit:
        soft.append(f'{len(no_digit)} 条 key_insight 不含任何数字')
    vague = [k for k in (analysis.get('key_insights') or [])
             if (not has_digit(k)) and any(b in str(k) for b in BANNED_VAGUE)]
    if vague:
        soft.append(f'{len(vague)} 条 key_insight 是无数字空话')

    # 5) 港美股
    hk = analysis.get('hk_stocks') or []
    us = analysis.get('us_stocks') or []
    summ = str(analysis.get('hk_us_summary', ''))
    if not hk and not us and not re.search(r'新闻|来源|接口|不可用|限制|时间|缺失', summ):
        soft.append('港美股为空且 summary 未标注降级来源')

    # 6) 双源交叉验证冲突（cloud_fetch 产出）：指数 0.3% / 个股 1% 分档
    blockers = []
    for conflict in (latest.get('data_quality', {}).get('source_conflicts') or []):
        code = str(conflict.get('code', ''))
        diff = conflict.get('diff_pct')
        if not isinstance(diff, (int, float)):
            continue
        limit = HARD_INDEX_PCT if code[-6:] in INDEX_CODES else HARD_PRICE_PCT
        label = '指数' if code[-6:] in INDEX_CODES else '个股'
        msg = (f'{label} {code} 双源冲突：{conflict.get("primary_source")} '
               f'{conflict.get("primary_price")} vs {conflict.get("secondary_source")} '
               f'{conflict.get("secondary_price")}（差{diff:.2f}%）')
        (hard if diff > limit else soft).append(msg)

    # 6b) 交叉验证是否真的做过——0 冲突可能意味着"没得比"而非"两源一致"
    cc = (latest.get('data_quality', {}).get('crosscheck') or {})
    if cc.get('status') == 'unchecked' or cc.get('checked_pairs') == 0:
        soft.append('本期未做双源交叉验证（无第二数据源），价格未经互相印证')

    # 7) 关注池覆盖率：<90% 降级，<70% 停止正式发送
    cov_level, cov_reason = quality.evaluate_coverage(latest)
    if cov_level == quality.BLOCK:
        blockers.append(cov_reason)
    elif cov_level == quality.DEGRADE:
        soft.append(cov_reason)

    # 7b) 数据活性：覆盖率回答"有没有数字"，活性回答"是不是今天的数字"
    live_level, live_reason = quality.evaluate_liveness(mode, latest)
    if live_level == quality.BLOCK:
        blockers.append(live_reason)
    elif live_level == quality.DEGRADE:
        soft.append(live_reason)

    # 7c) highlight 的 price 是回填价，而该股今日明明有盘中价。
    # 目前渲染端只输出 comment 文字、不输出 price，所以这不是收件人可见的误导；
    # 但 verify 的偏差核对、归档 bundle 与预测台账存的都是这个数字，写错就是错。
    # 故记软警告并把正确的今日价写进 intraday_price 字段，不硬失败。
    soft.extend(stale_highlights)

    # 7d) 外围指数行滞后一个交易日。抓数端一直算着 row_stale 却没人读，
    # 挡在陈旧指数和邮件之间的只有模型的自觉。引用了旧数字记硬失败，
    # 只是存在陈旧行则记软警告。
    gidx_level, gidx_reason, gidx_detail = quality.evaluate_global_index_staleness(
        latest, analysis)
    if gidx_detail['misattributed']:
        hard.append(gidx_reason)
    elif gidx_level != quality.PASS:
        soft.append(gidx_reason)

    # 8a) 午报数据必须是当日的（与闭环分开：原因不同、修法不同）
    cur_level, cur_reason = quality.evaluate_data_currency(mode, latest, today=args.today)
    if cur_level == quality.BLOCK:
        blockers.append(cur_reason)
    elif cur_level == quality.DEGRADE:
        soft.append(cur_reason)

    # 8b) 早午报闭环：今天有没有一份当日早报可供复盘
    cont_level, cont_reason, prior_result = quality.evaluate_continuity(
        mode, latest, morning_analysis, today=args.today)
    if prior_result == 'pending':
        reflection = analysis.get('reflection')
        if not isinstance(reflection, dict):
            reflection = {}
        reflection['prior_result'] = 'pending'
        reflection.setdefault('error_type', 'unverifiable')
        reflection['lesson'] = f'闭环断裂，本期不结算上一期预测：{cont_reason}'
        analysis['reflection'] = reflection
        analysis['review'] = f'[待结算] {cont_reason}。' + str(analysis.get('review', ''))
    if cont_level == quality.BLOCK:
        (soft if args.allow_open_loop else blockers).append(cont_reason)
    elif cont_level == quality.DEGRADE:
        soft.append(cont_reason)

    # 9) 有过期报价时禁止使用"实时"一类确定性措辞
    rt_level, rt_reason = quality.evaluate_realtime_claims(latest, analysis, mode=mode)
    if rt_level != quality.PASS:
        soft.append(rt_reason)

    blocked = bool(blockers)
    degraded = bool(soft) or blocked
    hard_fail = bool(hard)
    ok = not hard_fail and not blocked

    verdict = {'ok': ok, 'degraded': degraded, 'hard_fail': hard_fail, 'blocked': blocked,
               'hard_reasons': hard, 'soft_reasons': soft, 'block_reasons': blockers,
               'mode': mode, 'expected_data_date': expected, 'quote_date_mode': qmode,
               'continuity': {'level': cont_level, 'reason': cont_reason,
                              'morning_date': (morning_analysis or {}).get('date')},
               'data_currency': {'level': cur_level, 'reason': cur_reason},
               'coverage': {'level': cov_level, 'reason': cov_reason},
               'liveness': {'level': live_level, 'reason': live_reason,
                            'live_rows': quality.count_live_rows(latest)[0],
                            'total_rows': quality.count_live_rows(latest)[1]},
               'stale_highlights': stale_highlights,
               'global_index_staleness': {
                   'level': gidx_level, 'reason': gidx_reason,
                   'stale_rows': [f"{r['code']}@{r['row_date']}"
                                  for r in gidx_detail['stale_rows']],
                   'misattributed': [r['code'] for r in gidx_detail['misattributed']]},
               'primary_priced': len([1 for v in primary.values() if v['price'] is not None]),
               'ef_priced': len([1 for v in ef_index.values() if v['price'] is not None])}

    analysis['degraded'] = degraded
    analysis['verify'] = {'ok': ok, 'degraded': degraded, 'hard_fail': hard_fail,
                          'blocked': blocked, 'reasons': hard + blockers + soft}
    json.dump(analysis, open(apath, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    verdict_path = Path(args.verdict) if args.verdict else verdict_path_for(apath)
    json.dump(verdict, open(verdict_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    if blocked:
        print('VERIFY: BLOCKED -> 停止正式发送（数据不足以支撑一份负责任的报告）')
        for reason in blockers:
            print('  -', reason)
        sys.exit(3)
    if hard_fail:
        print('VERIFY: HARD FAIL ->（调用方：重生成一次；再失败则降级发出 + Gmail 告警）')
        sys.exit(2)
    print('VERIFY: PASS (DEGRADED)' if degraded else 'VERIFY: PASS')
    sys.exit(0)


if __name__ == '__main__':
    main()
