import requests, os, base64, json
from datetime import datetime

RESEND_API_KEY = os.environ['RESEND_API_KEY']
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
RECIPIENT = '1654155512@qq.com'
REPO = 'ldwghm/AI-Mark-information'

INDICES = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
INDEX_NAMES = {
    'sh000001': '上证指数', 'sz399001': '深证成指',
    'sz399006': '创业板指', 'sh000688': '科创50',
}

STOCKS = [
    ('sz300308', '中际旭创', '光模块', '光模块龙头/CPO'),
    ('sz300394', '天孚通信', '光模块', '光器件'),
    ('sz300502', '新易盛',   '光模块', '高速光模块'),
    ('sz002281', '光迅科技', '光模块', 'CPO方向'),
    ('sh600522', '中天科技', '光通信', '光缆/5G基建'),
    ('sh600487', '亨通光电', '光通信', '光纤光缆龙头'),
    ('sh600498', '烽火通信', '光通信', '光通信系统'),
    ('sh603019', '中科曙光', '算力',   'AI服务器/超算'),
    ('sh601138', '工业富联', '算力',   'AI服务器'),
    ('sz000977', '浪潮信息', '算力',   '服务器龙头'),
    ('sh688041', '海光信息', 'AI芯片', '国产CPU/GPU'),
    ('sh688256', '寒武纪',   'AI芯片', 'AI推理芯片'),
    ('sz300474', '景嘉微',   'AI芯片', '国产GPU'),
    ('sh603986', '兆易创新', '半导体', 'NOR Flash/MCU'),
    ('sz002049', '紫光国微', '半导体', '芯片设计'),
    ('sh688008', '澜起科技', '半导体', '内存接口芯片'),
    ('sz002371', '北方华创', '半导体', '半导体设备龙头'),
    ('sh688981', '中芯国际', '半导体', '晶圆代工'),
    ('sz002236', '大华技术', 'AI应用', 'AI视觉/安防'),
    ('sz300750', '宁德时代', '新能源', '动力电池龙头'),
    ('sz002460', '赣锋锂业', '新能源', '锂资源/电池'),
    ('sz002074', '国轩高科', '新能源', '动力电池'),
    ('sh600989', '宝丰能源', '新能源', '煤化工+新能源'),
    ('sz002916', '深南电路', '算力基建', 'AI服务器PCB'),
]

SECTOR_ORDER = ['光模块', '光通信', '算力', 'AI芯片', '半导体', 'AI应用', '新能源', '算力基建']

# ── GitHub volume history ──────────────────────────────────────────────────

def gh_read_history():
    if not GITHUB_TOKEN:
        return {}, None
    try:
        r = requests.get(
            f'https://api.github.com/repos/{REPO}/contents/volume_history.json',
            headers={'Authorization': f'Bearer {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github+json'},
            timeout=10)
        if r.status_code == 200:
            d = r.json()
            return json.loads(base64.b64decode(d['content']).decode('utf-8')), d['sha']
    except Exception as e:
        print(f'[history] read failed: {e}')
    return {}, None

def gh_write_history(history, sha, today):
    if not GITHUB_TOKEN:
        return
    try:
        b64 = base64.b64encode(
            json.dumps(history, ensure_ascii=False, indent=2).encode('utf-8')
        ).decode()
        payload = {'message': f'chore: vol history {today}', 'content': b64}
        if sha:
            payload['sha'] = sha
        r = requests.put(
            f'https://api.github.com/repos/{REPO}/contents/volume_history.json',
            headers={'Authorization': f'Bearer {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json'},
            json=payload, timeout=15)
        print(f'[history] write: {r.status_code}')
    except Exception as e:
        print(f'[history] write failed: {e}')

# ── Sina API ───────────────────────────────────────────────────────────────

def fetch(codes):
    r = requests.get(
        f'https://hq.sinajs.cn/list={",".join(codes)}',
        headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'},
        timeout=10)
    r.encoding = 'gbk'
    return r.text

def parse(line):
    if '="' not in line or line.strip().endswith('="";'):
        return None
    code = line.split('hq_str_')[1].split('=')[0]
    d = line.split('="')[1].rstrip('";').split(',')
    if len(d) < 10:
        return None
    try:
        prev, cur = float(d[2]), float(d[3])
        amt = float(d[9]) if d[9] else 0
        vol = float(d[8]) if d[8] else 0
        return {
            'code': code, 'name': d[0],
            'open': float(d[1]), 'prev': prev, 'cur': cur,
            'high': float(d[4]), 'low': float(d[5]),
            'vol': vol, 'amt': amt,
            'pct': (cur - prev) / prev * 100 if prev else 0,
        }
    except:
        return None

# ── Formatters ─────────────────────────────────────────────────────────────

def clr(p): return '#16a34a' if p >= 0 else '#dc2626'
def fp(p):  return f'{p:+.2f}%'

def fmt_amt(a):
    if a >= 1e8: return f'{a/1e8:.1f}亿'
    if a >= 1e4: return f'{a/1e4:.0f}万'
    return f'{a:.0f}'

def vol_badge(cur_amt, prev_amt):
    """Return inline HTML badge showing volume change vs yesterday."""
    if not prev_amt or prev_amt == 0:
        return '<span style="color:#9ca3af;font-size:11px">首日</span>'
    pct = (cur_amt - prev_amt) / prev_amt * 100
    if pct > 20:
        label, color = f'放量+{pct:.0f}%', '#16a34a'
    elif pct < -20:
        label, color = f'缩量{pct:.0f}%', '#dc2626'
    else:
        label, color = f'平量{pct:+.0f}%', '#9ca3af'
    arrow = '▲' if pct > 0 else '▼'
    return f"<span style='color:{color};font-size:11px'>{arrow}{label}</span>"

def limit_flag(pct):
    if pct >= 9.9:  return ' 🚀涨停'
    if pct <= -9.9: return ' 💀跌停'
    if pct >= 7.0:  return ' ⚡强势'
    return ''

# ── Trading analysis ───────────────────────────────────────────────────────

def trading_analysis(idx_data, all_parsed, vol_history):
    """Return (style_html, windows_html, score) based on market data."""
    mi = idx_data[0] if idx_data and idx_data[0] else None
    idx_pct = mi['pct'] if mi else 0

    # Volume change for main index vs yesterday
    idx_vol_chg = None
    if mi:
        prev_amt = vol_history.get(mi['code'], {}).get('amt', 0)
        if prev_amt > 0:
            idx_vol_chg = (mi['amt'] - prev_amt) / prev_amt * 100

    # Limit-ups/downs in watchlist
    limit_up_cnt  = sum(1 for d in all_parsed if d['pct'] >= 9.9)
    limit_dn_cnt  = sum(1 for d in all_parsed if d['pct'] <= -9.9)

    # Sector breadth
    stock_map = {s[0]: s for s in STOCKS}
    sector_avgs = {}
    for d in all_parsed:
        info = stock_map.get(d['code'])
        if info:
            sec = info[2]
            sector_avgs.setdefault(sec, []).append(d['pct'])
    positive_sec = sum(1 for v in sector_avgs.values() if sum(v)/len(v) > 0)
    total_sec    = len(sector_avgs) or 1
    breadth_pct  = positive_sec / total_sec * 100

    best_sector = max(sector_avgs, key=lambda s: sum(sector_avgs[s])/len(sector_avgs[s])) \
                  if sector_avgs else None

    # ── Score factors ──
    score = 0
    factors = []  # (icon, text)

    if idx_pct > 1.5:
        score += 3; factors.append(('✅', f'大盘强势涨{idx_pct:.2f}%，做多情绪高涨'))
    elif idx_pct > 0.5:
        score += 2; factors.append(('✅', f'大盘温和上涨{idx_pct:.2f}%，偏多格局'))
    elif idx_pct > 0:
        score += 1; factors.append(('⚠️', f'大盘小幅翻红{idx_pct:.2f}%，方向待明确'))
    elif idx_pct > -0.5:
        score -= 1; factors.append(('⚠️', f'大盘小幅下跌{idx_pct:.2f}%，谨慎观望'))
    elif idx_pct > -1.5:
        score -= 2; factors.append(('❌', f'大盘弱势下跌{idx_pct:.2f}%，控制仓位'))
    else:
        score -= 3; factors.append(('❌', f'大盘大跌{idx_pct:.2f}%，建议空仓或轻仓'))

    if idx_vol_chg is not None:
        if idx_vol_chg > 30:
            score += 2
            factors.append(('✅', f'上证成交额大幅放量{idx_vol_chg:.0f}%，资金积极入场，做多意愿强'))
        elif idx_vol_chg > 10:
            score += 1
            factors.append(('✅', f'上证成交额温和放量{idx_vol_chg:.0f}%，市场活跃度提升'))
        elif idx_vol_chg < -30:
            score -= 2
            factors.append(('❌', f'上证成交额大幅缩量{abs(idx_vol_chg):.0f}%，市场观望情绪浓重，谨慎操作'))
        elif idx_vol_chg < -10:
            score -= 1
            factors.append(('❌', f'上证成交额缩量{abs(idx_vol_chg):.0f}%，短期谨慎为主'))
        else:
            factors.append(('⚠️', f'上证成交额变化不大（{idx_vol_chg:+.0f}%），量能平稳，参考性有限'))
    else:
        factors.append(('⚠️', '历史量能数据不足（首次运行），无法对比放量/缩量'))

    if limit_up_cnt >= 3:
        score += 2
        factors.append(('✅', f'关注池内{limit_up_cnt}只涨停，赚钱效应强，可追强'))
    elif limit_up_cnt >= 1:
        score += 1
        factors.append(('✅', f'关注池内{limit_up_cnt}只涨停，局部赚钱效应存在'))

    if limit_dn_cnt >= 3:
        score -= 2
        factors.append(('❌', f'关注池内{limit_dn_cnt}只跌停，杀跌情绪蔓延，规避风险'))
    elif limit_dn_cnt >= 1:
        score -= 1
        factors.append(('❌', f'关注池内{limit_dn_cnt}只跌停，注意板块拖累'))

    if breadth_pct > 70:
        score += 1
        factors.append(('✅', f'{positive_sec}/{total_sec}板块上涨，市场普涨格局，机会分散'))
    elif breadth_pct < 30:
        score -= 1
        factors.append(('❌', f'仅{positive_sec}/{total_sec}板块上涨，市场分化严重，谨慎追高'))

    # ── Style mapping ──
    if score >= 6:
        style, scolor, pos_range = '激进', '#16a34a', '60-80%'
        style_desc = ('市场强势，可积极参与强势股和涨停板，优先跟随最强板块龙头。'
                      '止损线设在成本-3%，盈利超5%可移动止盈。')
    elif score >= 3:
        style, scolor, pos_range = '偏多', '#65a30d', '40-60%'
        style_desc = ('市场偏强，适度参与，重点选择量能配合的强势股。'
                      '保持一定现金应对回调，止损-5%严格执行。')
    elif score >= 1:
        style, scolor, pos_range = '中性偏多', '#d97706', '30-50%'
        style_desc = ('市场方向偏多但信号不强，轻仓参与确定性机会，等待明确量能信号再加仓。'
                      '止损-5%，不追高冲板。')
    elif score >= -1:
        style, scolor, pos_range = '中性', '#6b7280', '20-40%'
        style_desc = ('市场方向不明，以观望为主，持有已有盈利仓位，控制新开仓。'
                      '若大盘企稳放量则再考虑参与。')
    elif score >= -3:
        style, scolor, pos_range = '偏空', '#ea580c', '≤30%'
        style_desc = ('市场偏弱，减仓为主，只持高确定性强势股。'
                      '严格止损，优先保护本金，等待弱势企稳信号。')
    else:
        style, scolor, pos_range = '保守', '#dc2626', '0-20%'
        style_desc = ('市场弱势明显，建议空仓或极轻仓观望，'
                      '等待成交额企稳+大盘止跌信号再布局。')

    factors_html = ''.join(
        f"<li style='margin:5px 0;font-size:14px'>{icon} {text}</li>"
        for icon, text in factors
    )
    best_hint = (f"<p style='margin:6px 0 0;font-size:13px;color:#374151'>"
                 f"最强板块：<b style='color:#1d4ed8'>{best_sector}</b>，优先关注该板块内个股机会。</p>"
                 if best_sector else '')

    style_html = f"""
<div style='border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:8px 0;background:#f9fafb'>
  <p style='margin:0 0 10px 0;font-size:15px'>
    今日交易风格：
    <span style='color:{scolor};font-weight:bold;font-size:22px'>&nbsp;{style}&nbsp;</span>
    <span style='color:#6b7280;font-size:13px;margin-left:10px'>建议仓位：{pos_range}</span>
  </p>
  <ul style='margin:0;padding-left:20px;line-height:1.9'>{factors_html}</ul>
  <p style='margin:10px 0 0;font-size:14px;color:#111'><b>操作方向：</b>{style_desc}</p>
  {best_hint}
</div>"""

    # ── Time windows ──
    is_bull = score >= 3
    is_bear = score <= -3

    def tw(t, sub, obs, action):
        return (f"<tr>"
                f"<td style='font-size:13px;white-space:nowrap'><b>{t}</b><br>"
                f"<span style='color:#9ca3af;font-size:11px'>{sub}</span></td>"
                f"<td style='font-size:13px;color:#4b5563'>{obs}</td>"
                f"<td style='font-size:13px'>{action}</td></tr>")

    w1 = ('可轻仓试探，量能充沛的强势股可建底仓' if is_bull
          else '观望为主，不盲目抄底；弱势跳空低开则直接放弃当日操作' if is_bear
          else '静观量能方向，缩量高开谨慎，放量低开可关注超跌')
    w2 = ('量能持续放大可加仓至目标仓位，涨停封板≥2只则积极追强' if is_bull
          else '若仍弱势无反弹，继续观望，不抢反弹' if is_bear
          else '量能决定方向：放量→跟强；缩量→继续等待')
    w3 = ('守住早盘涨幅则持仓，跌破开盘价且无量支撑则减半仓止损' if is_bull
          else '若持续弱势则清仓，不赌反弹' if is_bear
          else '指数能否守高决定下午走势，此窗口判断午后策略')
    w4 = ('午后放量上攻可加仓；缩量横盘则轻仓不追，等待下一个信号' if is_bull
          else '小反弹无量不追，观察是否有资金护盘意愿' if is_bear
          else '关注主力资金方向，有量的板块顺势跟随')
    w5_base = f'{best_sector}板块若维持强势可持仓过夜' if (is_bull and best_sector) else \
              '缩量阴线坚决止损，不过夜' if is_bear else \
              f'{"最强板块"+best_sector+"维持则持仓；" if best_sector else ""}缩量转阴则减仓，降低过夜风险'

    windows_html = f"""
<table border='1' cellpadding='9' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'>
  <th style='width:22%;font-size:13px'>时间窗口</th>
  <th style='width:33%;font-size:13px'>观察重点</th>
  <th style='font-size:13px'>操作建议</th>
</tr>
{tw('9:25-9:30','集合竞价',
    '高低开幅度 / 竞价成交量',
    '高开>2%不追，等回踩；低开<1%可观察量能择机；竞价成交量>前日均值为放量信号')}
{tw('9:30-10:00','开盘第一波',
    '主力资金流入方向 / 是否冲高回落',
    w1)}
{tw('10:00-10:30','主力方向窗口',
    '涨停板封板情况 / 板块持续性 / 量能是否衰减',
    w2)}
{tw('11:00-11:30','午盘前',
    '指数能否守住涨幅 / 强势股是否回撤',
    w3)}
{tw('14:00-14:30','午后行情',
    '是否有增量资金进场 / 龙头个股走势',
    w4)}
{tw('14:30-15:00','尾盘决策窗口',
    f'尾盘量能变化 / {"最强板块"+best_sector if best_sector else "主力护盘意愿"} / 过夜风险',
    w5_base + '；周五尾盘缩量需额外谨慎，不留无把握仓位过周末')}
</table>"""

    return style_html, windows_html, score

# ── HTML builder ───────────────────────────────────────────────────────────

def build_html(today, idx_data, stk_data, vol_history):
    stock_map = {s[0]: s for s in STOCKS}
    all_parsed = [d for d in stk_data if d]

    # ── Index table ──
    idx_rows = ''
    for d in idx_data:
        if not d: continue
        prev_amt = vol_history.get(d['code'], {}).get('amt', 0)
        badge = vol_badge(d['amt'], prev_amt)
        idx_rows += (
            f"<tr>"
            f"<td><b>{INDEX_NAMES.get(d['code'], d['name'])}</b></td>"
            f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
            f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
            f"<td style='color:#6b7280'>{d['open']:.2f}</td>"
            f"<td>{fmt_amt(d['amt'])}&nbsp;{badge}</td>"
            f"</tr>"
        )

    # ── Sector summary ──
    sectors = {}
    for d in all_parsed:
        info = stock_map.get(d['code'])
        if not info: continue
        sec = info[2]
        sectors.setdefault(sec, []).append({**d, 'theme': info[3]})

    sector_summary = []
    for sec in SECTOR_ORDER:
        if sec not in sectors: continue
        items = sectors[sec]
        avg_pct = sum(x['pct'] for x in items) / len(items)
        best  = max(items, key=lambda x: x['pct'])
        worst = min(items, key=lambda x: x['pct'])
        # sector total volume change
        sec_amt_cur  = sum(x['amt'] for x in items)
        sec_amt_prev = sum(vol_history.get(x['code'], {}).get('amt', 0) for x in items)
        sec_vol_badge = vol_badge(sec_amt_cur, sec_amt_prev)
        sector_summary.append((sec, avg_pct, len(items), best, worst, sec_vol_badge))

    sector_summary.sort(key=lambda x: x[1], reverse=True)

    sector_rows = ''.join(
        f"<tr>"
        f"<td><b>{sec}</b></td>"
        f"<td style='color:{clr(avg)};font-weight:bold'>{fp(avg)}</td>"
        f"<td style='color:#6b7280'>{cnt}只</td>"
        f"<td>{badge}</td>"
        f"<td style='color:{clr(best[\"pct\"])}'>{best[\"name\"]} {fp(best[\"pct\"])}</td>"
        f"<td style='color:{clr(worst[\"pct\"])}'>{worst[\"name\"]} {fp(worst[\"pct\"])}</td>"
        f"</tr>"
        for sec, avg, cnt, best, worst, badge in sector_summary
    )

    # ── Limit-up/down alerts ──
    limit_up = [d for d in all_parsed if d['pct'] >= 9.9]
    limit_dn = [d for d in all_parsed if d['pct'] <= -9.9]
    alert_html = ''
    if limit_up:
        names = '、'.join(f"<b>{d['name']}</b>({d['code'][2:]})" for d in limit_up)
        alert_html += f"<p>🚀 <b>涨停</b>：{names}</p>"
    if limit_dn:
        names = '、'.join(f"<b>{d['name']}</b>({d['code'][2:]})" for d in limit_dn)
        alert_html += f"<p>💀 <b>跌停</b>：{names}</p>"
    if not alert_html:
        alert_html = '<p style="color:#9ca3af">今日无涨跌停个股</p>'

    # ── Full stock table sorted by pct ──
    all_sorted = sorted(all_parsed, key=lambda x: x['pct'], reverse=True)
    stk_rows = ''
    for d in all_sorted:
        info = stock_map.get(d['code']) or ('', '', '', '')
        prev_amt = vol_history.get(d['code'], {}).get('amt', 0)
        badge = vol_badge(d['amt'], prev_amt)
        stk_rows += (
            f"<tr>"
            f"<td>{d['name']}{limit_flag(d['pct'])}</td>"
            f"<td style='color:#6b7280;font-family:monospace'>{d['code'][2:]}</td>"
            f"<td style='color:#6b7280;font-size:12px'>{info[2]}</td>"
            f"<td style='color:#6b7280;font-size:12px'>{info[3]}</td>"
            f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
            f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
            f"<td style='color:#6b7280'>{fmt_amt(d['amt'])}</td>"
            f"<td>{badge}</td>"
            f"</tr>"
        )

    # ── Focus list: ≤100元, 00/60 prefix ──
    focus = [d for d in all_sorted
             if d['cur'] <= 100 and (d['code'][2:].startswith('00') or d['code'][2:].startswith('60'))]
    if focus:
        focus_html = (
            "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
            "<tr style='background:#f3f4f6'><th>股票</th><th>代码</th><th>板块</th>"
            "<th>现价(元)</th><th>涨跌幅</th><th>成交额</th><th>量变</th></tr>"
            + ''.join(
                f"<tr><td><b>{d['name']}</b></td>"
                f"<td style='font-family:monospace'>{d['code'][2:]}</td>"
                f"<td style='color:#6b7280'>{(stock_map.get(d['code']) or ('','','',''))[2]}</td>"
                f"<td>{d['cur']:.2f}</td>"
                f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}{limit_flag(d['pct'])}</td>"
                f"<td style='color:#6b7280'>{fmt_amt(d['amt'])}</td>"
                f"<td>{vol_badge(d['amt'], vol_history.get(d['code'], {}).get('amt', 0))}</td></tr>"
                for d in focus)
            + "</table>")
    else:
        focus_html = '<p style="color:#9ca3af">今日无符合条件标的（≤100元，00/60开头）</p>'

    # ── Trading analysis ──
    style_html, windows_html, score = trading_analysis(idx_data, all_parsed, vol_history)

    return f"""<html><body style='font-family:Arial,sans-serif;max-width:780px;margin:0 auto;color:#111'>
<h2 style='color:#1d4ed8;border-bottom:2px solid #1d4ed8;padding-bottom:8px'>
  📈 A股AI板块早报 &middot; {today}
  <span style='font-size:14px;font-weight:normal;margin-left:12px;color:#6b7280'>数据为昨日收盘，早8:00推送</span>
</h2>

<h3>📊 大盘指数</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>指数</th><th>收盘价</th><th>涨跌幅</th><th>今开</th><th>成交额(量变)</th></tr>
{idx_rows}</table>

<h3>🗂️ 板块概览（按平均涨跌幅排序）</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>板块</th><th>平均涨跌</th><th>股票数</th><th>板块量变</th><th>最强</th><th>最弱</th></tr>
{sector_rows}</table>

<h3>⚡ 涨跌停提示</h3>
{alert_html}

<h3>🤖 全部个股（按涨跌幅排序，共{len(all_sorted)}只）</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>股票</th><th>代码</th><th>板块</th><th>方向</th>
<th>收盘价</th><th>涨跌幅</th><th>成交额</th><th>量变</th></tr>
{stk_rows}</table>

<h3>🎯 今日重点关注（≤100元，00/60开头）</h3>
{focus_html}

<h3>🧠 今日风格判断 & 操盘建议</h3>
{style_html}

<h3>⏰ 分时间窗操作指南</h3>
{windows_html}

<hr style='margin-top:28px'>
<p style='color:#9ca3af;font-size:12px'>
  ⚠️ 仅供参考，不构成投资建议。股市有风险，入市需谨慎。<br>
  数据来源：新浪财经 | 自动推送：北京时间 08:00 | 数据为昨日（上一交易日）收盘数据
</p>
</body></html>"""

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    today = datetime.now().strftime('%Y-%m-%d')

    # 1. Load volume history from repo
    vol_history, history_sha = gh_read_history()
    print(f'[history] loaded {len(vol_history)} entries, sha={history_sha}')

    # 2. Fetch market data
    all_codes = INDICES + [s[0] for s in STOCKS]
    raw = fetch(all_codes)
    parsed = {}
    for line in raw.strip().split('\n'):
        if 'hq_str_' in line:
            p = parse(line)
            if p:
                parsed[p['code']] = p

    idx_data = [parsed.get(c) for c in INDICES]
    stk_data = [parsed.get(s[0]) for s in STOCKS]

    # 3. Build HTML
    html = build_html(today, idx_data, [d for d in stk_data if d], vol_history)

    # 4. Send email
    resp = requests.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
        json={
            'from': 'A股早报 <onboarding@resend.dev>',
            'to': [RECIPIENT],
            'subject': f'📈 A股AI板块早报 · {today}',
            'html': html,
        },
        timeout=15)
    result = resp.json()
    if 'id' in result:
        print(f'Email sent! ID: {result["id"]}')
    else:
        print(f'Email failed: {result}')
        exit(1)

    # 5. Update volume history (write after email sent, so failure here doesn't block email)
    new_history = {**vol_history}
    for code, d in parsed.items():
        new_history[code] = {'amt': d['amt'], 'date': today}
    gh_write_history(new_history, history_sha, today)

if __name__ == '__main__':
    main()
