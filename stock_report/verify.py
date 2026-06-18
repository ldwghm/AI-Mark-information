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

HARD_PRICE_PCT = 25.0   # 价格较可靠源偏离超过此比例 → 硬失败（编造）
HARD_CHG_FLIP_ABS = 5.0  # 涨跌幅符号翻转且绝对差超过此值 → 硬失败
SOFT_PRICE_PCT = 3.0
SOFT_CHG_ABS = 1.5
BANNED_VAGUE = ['建议关注', '保持谨慎', '注意风险', '择机', '逢低', '逢高']


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['morning', 'afternoon'])
    ap.add_argument('--latest')
    ap.add_argument('--analysis')
    args = ap.parse_args()
    mode = args.mode
    lpath = args.latest or f'/tmp/{mode}_latest.json'
    apath = args.analysis or f'/tmp/{mode}_analysis.json'

    latest = json.load(open(lpath, encoding='utf-8-sig'))
    analysis = json.load(open(apath, encoding='utf-8-sig'))

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
    for h in analysis.get('stock_highlights', []) or []:
        code = str(h.get('code', ''))
        nm = h.get('name', '?')
        hp, hcg = _f(h.get('price')), _f(h.get('chg_pct'))
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
                    soft.append(f'{nm}({code}) 涨跌方向相反 报{hcg} 实际{scg}（疑似快照不一致或笔误）')
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

    degraded = bool(soft)
    hard_fail = bool(hard)
    ok = not hard_fail

    verdict = {'ok': ok, 'degraded': degraded, 'hard_fail': hard_fail,
               'hard_reasons': hard, 'soft_reasons': soft,
               'mode': mode, 'expected_data_date': expected, 'quote_date_mode': qmode,
               'primary_priced': len([1 for v in primary.values() if v['price'] is not None]),
               'ef_priced': len([1 for v in ef_index.values() if v['price'] is not None])}

    analysis['degraded'] = degraded
    analysis['verify'] = {'ok': ok, 'degraded': degraded, 'hard_fail': hard_fail, 'reasons': hard + soft}
    json.dump(analysis, open(apath, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(verdict, open(apath.replace('_analysis.json', '_verdict.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    if hard_fail:
        print('VERIFY: HARD FAIL ->（调用方：重生成一次；再失败则降级发出 + Gmail 告警）')
        sys.exit(2)
    print('VERIFY: PASS (DEGRADED)' if degraded else 'VERIFY: PASS')
    sys.exit(0)


if __name__ == '__main__':
    main()
