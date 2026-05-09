import requests, os
from datetime import datetime

RESEND_API_KEY = os.environ['RESEND_API_KEY']
RECIPIENT = '1654155512@qq.com'

INDICES = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
INDEX_NAMES = {
    'sh000001': '上证指数',
    'sz399001': '深证成指',
    'sz399006': '创业板指',
    'sh000688': '科创50',
}

# (code, display_name, sector, theme)
STOCKS = [
    # 光模块/CPO
    ('sz300308', '中际旭创', '光模块', '光模块龙头/CPO'),
    ('sz300394', '天孚通信', '光模块', '光器件'),
    ('sz300502', '新易盛', '光模块', '高速光模块'),
    ('sz002281', '光迅科技', '光模块', 'CPO方向'),
    # 光通信/光纤
    ('sh600522', '中天科技', '光通信', '光缆/5G基建'),
    ('sh600487', '亨通光电', '光通信', '光纤光缆龙头'),
    ('sh600498', '烽火通信', '光通信', '光通信系统'),
    # 算力/服务器
    ('sh603019', '中科曙光', '算力', 'AI服务器/超算'),
    ('sh601138', '工业富联', '算力', 'AI服务器'),
    ('sz000977', '浪潮信息', '算力', '服务器龙头'),
    # AI芯片
    ('sh688041', '海光信息', 'AI芯片', '国产CPU/GPU'),
    ('sh688256', '寒武纪', 'AI芯片', 'AI推理芯片'),
    ('sz300474', '景嘉微', 'AI芯片', '国产GPU'),
    # 半导体
    ('sh603986', '兆易创新', '半导体', 'NOR Flash/MCU'),
    ('sz002049', '紫光国微', '半导体', '芯片设计'),
    ('sh688008', '澜起科技', '半导体', '内存接口芯片'),
    ('sz002371', '北方华创', '半导体', '半导体设备龙头'),
    ('sh688981', '中芯国际', '半导体', '晶圆代工'),
    # AI应用
    ('sz002236', '大华技术', 'AI应用', 'AI视觉/安防'),
    # 新能源/锂电
    ('sz300750', '宁德时代', '新能源', '动力电池龙头'),
    ('sz002460', '赣锋锂业', '新能源', '锂资源/电池'),
    ('sz002074', '国轩高科', '新能源', '动力电池'),
    ('sh600989', '宝丰能源', '新能源', '煤化工+新能源'),
    # 算力基建
    ('sz002916', '深南电路', '算力基建', 'AI服务器PCB'),
]

SECTOR_ORDER = ['光模块', '光通信', '算力', 'AI芯片', '半导体', 'AI应用', '新能源', '算力基建']

def fetch(codes):
    r = requests.get(
        f'https://hq.sinajs.cn/list={",".join(codes)}',
        headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'},
        timeout=10
    )
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
        return {
            'code': code,
            'name': d[0],
            'open': float(d[1]),
            'prev': prev,
            'cur': cur,
            'high': float(d[4]),
            'low': float(d[5]),
            'amt': amt,
            'pct': (cur - prev) / prev * 100 if prev else 0,
        }
    except:
        return None

def clr(p): return '#16a34a' if p >= 0 else '#dc2626'
def fp(p): return f'{p:+.2f}%'

def fmt_amt(a):
    if a >= 1e8: return f'{a/1e8:.1f}亿'
    if a >= 1e4: return f'{a/1e4:.0f}万'
    return f'{a:.0f}'

def limit_flag(pct):
    if pct >= 9.9: return ' 🚀涨停'
    if pct <= -9.9: return ' 💀跌停'
    if pct >= 7.0: return ' ⚡强势'
    return ''

def build_html(today, idx_data, stk_data):
    # Index table
    idx_rows = ''.join(
        f"<tr><td><b>{INDEX_NAMES.get(d['code'], d['name'])}</b></td>"
        f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
        f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
        f"<td style='color:#6b7280'>{d['open']:.2f}</td></tr>"
        for d in idx_data if d)

    # Build sector groups
    stock_map = {s[0]: s for s in STOCKS}
    all_parsed = [d for d in stk_data if d]
    sectors = {}
    for d in all_parsed:
        info = stock_map.get(d['code'])
        if not info:
            continue
        sec = info[2]
        if sec not in sectors:
            sectors[sec] = []
        sectors[sec].append({**d, 'theme': info[3]})

    # Sector summary rows (sorted by avg pct desc)
    sector_summary = []
    for sec in SECTOR_ORDER:
        if sec not in sectors:
            continue
        items = sectors[sec]
        avg_pct = sum(x['pct'] for x in items) / len(items)
        best = max(items, key=lambda x: x['pct'])
        worst = min(items, key=lambda x: x['pct'])
        sector_summary.append((sec, avg_pct, len(items), best, worst))
    sector_summary.sort(key=lambda x: x[1], reverse=True)

    sector_rows = ''.join(
        f"<tr>"
        f"<td><b>{sec}</b></td>"
        f"<td style='color:{clr(avg)};font-weight:bold'>{fp(avg)}</td>"
        f"<td style='color:#6b7280'>{cnt}只</td>"
        f"<td style='color:{clr(best['pct'])}'>{best['name']} {fp(best['pct'])}</td>"
        f"<td style='color:{clr(worst['pct'])}'>{worst['name']} {fp(worst['pct'])}</td>"
        f"</tr>"
        for sec, avg, cnt, best, worst in sector_summary)

    # Limit-up/down alerts
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

    # Full stock table sorted by pct desc
    all_sorted = sorted(all_parsed, key=lambda x: x['pct'], reverse=True)
    stk_rows = ''.join(
        f"<tr>"
        f"<td>{d['name']}{limit_flag(d['pct'])}</td>"
        f"<td style='color:#6b7280;font-family:monospace'>{d['code'][2:]}</td>"
        f"<td style='color:#6b7280;font-size:12px'>{(stock_map.get(d['code']) or ('','','',''))[2]}</td>"
        f"<td style='color:#6b7280;font-size:12px'>{(stock_map.get(d['code']) or ('','','',''))[3]}</td>"
        f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
        f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
        f"<td style='color:#6b7280'>{fmt_amt(d['amt'])}</td>"
        f"</tr>"
        for d in all_sorted)

    # Focus: ≤100元, 00/60 prefix
    focus = [d for d in all_sorted
             if d['cur'] <= 100 and (d['code'][2:].startswith('00') or d['code'][2:].startswith('60'))]
    if focus:
        focus_html = (
            "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
            "<tr style='background:#f3f4f6'><th>股票</th><th>代码</th><th>板块</th><th>现价(元)</th><th>涨跌幅</th><th>成交额</th></tr>"
            + ''.join(
                f"<tr><td><b>{d['name']}</b></td>"
                f"<td style='font-family:monospace'>{d['code'][2:]}</td>"
                f"<td style='color:#6b7280'>{(stock_map.get(d['code']) or ('','','',''))[2]}</td>"
                f"<td>{d['cur']:.2f}</td>"
                f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}{limit_flag(d['pct'])}</td>"
                f"<td style='color:#6b7280'>{fmt_amt(d['amt'])}</td></tr>"
                for d in focus)
            + "</table>")
    else:
        focus_html = '<p style="color:#9ca3af">今日无符合条件标的</p>'

    # Market tips
    mi = idx_data[0] if idx_data and idx_data[0] else None
    if mi and mi['pct'] > 0.5:
        m_tip = f'大盘高开{fp(mi["pct"])}，量能维持可跟进光通信等强势板块，注意追高风险'
        a_tip = '尾盘成交额维持则强势股可持仓；缩量则适当减仓'
    elif mi and mi['pct'] < -0.5:
        m_tip = f'大盘低开{fp(mi["pct"])}，建议先观望，等企稳信号再操作'
        a_tip = '持续弱势建议减仓，降低过夜风险'
    else:
        m_tip = '大盘平开，关注AI板块量能分化，有量的方向优先跟'
        a_tip = '关注尾盘主力方向，光通信/算力若维持涨幅可持仓'

    return f"""<html><body style='font-family:Arial,sans-serif;max-width:760px;margin:0 auto;color:#111'>
<h2 style='color:#1d4ed8;border-bottom:2px solid #1d4ed8;padding-bottom:8px'>📈 A股AI板块早报 &middot; {today}</h2>

<h3>📊 大盘指数</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>指数</th><th>现价</th><th>涨跌幅</th><th>今开</th></tr>
{idx_rows}</table>

<h3>🗂️ 板块概览（按平均涨跌幅排序）</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>板块</th><th>平均涨跌</th><th>股票数</th><th>最强</th><th>最弱</th></tr>
{sector_rows}</table>

<h3>⚡ 涨跌停提示</h3>
{alert_html}

<h3>🤖 全部个股（按涨跌幅排序，共{len(all_sorted)}只）</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>股票</th><th>代码</th><th>板块</th><th>方向</th><th>现价(元)</th><th>涨跌幅</th><th>成交额</th></tr>
{stk_rows}</table>

<h3>⏰ 操盘参考</h3>
<p><b>10:00-10:30 观察窗：</b>{m_tip}</p>
<p><b>14:30-15:00 决策窗：</b>{a_tip}</p>

<h3>🎯 今日重点关注（≤100元，00/60开头）</h3>
{focus_html}

<hr style='margin-top:24px'>
<p style='color:#9ca3af;font-size:12px'>⚠️ 仅供参考，不构成投资建议。股市有风险，入市需谨慎。<br>
数据来源：新浪财经 | 自动生成：北京时间 08:00</p>
</body></html>"""

def main():
    today = datetime.now().strftime('%Y-%m-%d')
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
    html = build_html(today, idx_data, stk_data)
    resp = requests.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
        json={'from': 'A\u80a1\u65e9\u62a5 <onboarding@resend.dev>', 'to': [RECIPIENT],
              'subject': f'\U0001f4c8 A\u80a1AI\u677f\u5757\u65e9\u62a5 \u00b7 {today}', 'html': html},
        timeout=15
    )
    result = resp.json()
    if 'id' in result:
        print(f'Email sent! ID: {result["id"]}')
    else:
        print(f'Failed: {result}')
        exit(1)

if __name__ == '__main__':
    main()
