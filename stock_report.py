import requests, os
from datetime import datetime

RESEND_API_KEY = os.environ['RESEND_API_KEY']
RECIPIENT = '1654155512@qq.com'

INDICES = ['sh000001', 'sz399001', 'sz399006']
INDEX_NAMES = {'sh000001': '\u4e0a\u8bc1\u6307\u6570', 'sz399001': '\u6df1\u8bc1\u6210\u6307', 'sz399006': '\u521b\u4e1a\u677f\u6307'}

STOCKS = [
    ('sh600522', '\u4e2d\u5929\u79d1\u6280', '\u5149\u901a\u4fe1/5G'),
    ('sh600487', '\u4ea8\u901a\u5149\u7535', '\u5149\u7ea4\u5149\u7f06'),
    ('sh600498', '\u70fd\u706b\u901a\u4fe1', '\u5149\u901a\u4fe1\u8bbe\u5907'),
    ('sh603019', '\u4e2d\u79d1\u66d9\u5149', '\u7b97\u529b/\u670d\u52a1\u5668'),
    ('sh603986', '\u5146\u6613\u521b\u65b0', '\u5b58\u50a8\u82af\u7247'),
    ('sz002281', '\u5149\u8fc5\u79d1\u6280', '\u5149\u6a21\u5757/CPO'),
    ('sz002049', '\u7d2b\u5149\u56fd\u5fae', '\u82af\u7247\u8bbe\u8ba1'),
    ('sz002236', '\u5927\u534e\u6280\u672f', 'AI\u89c6\u89c9\u7b97\u529b'),
    ('sz002460', '\u8d63\u950b\u9502\u4e1a', '\u9502\u7535\u6c60'),
    ('sz002074', '\u56fd\u8f69\u9ad8\u79d1', '\u52a8\u529b\u7535\u6c60'),
    ('sh600989', '\u5b9d\u4e30\u80fd\u6e90', '\u65b0\u80fd\u6e90\u5316\u5de5'),
    ('sz002916', '\u6df1\u5357\u7535\u8def', 'PCB/\u7b97\u529b\u57fa\u5efa'),
]

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
    if len(d) < 6:
        return None
    try:
        prev, cur = float(d[2]), float(d[3])
        return {'code': code, 'name': d[0], 'open': float(d[1]),
                'prev': prev, 'cur': cur,
                'pct': (cur - prev) / prev * 100 if prev else 0}
    except:
        return None

def clr(p): return '#16a34a' if p >= 0 else '#dc2626'
def fp(p): return f'{p:+.2f}%'

def build_html(today, idx_data, stk_data):
    idx_rows = ''.join(
        f"<tr><td><b>{INDEX_NAMES.get(d['code'], d['name'])}</b></td>"
        f"<td>{d['cur']:.2f}</td>"
        f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
        f"<td>{d['open']:.2f}</td></tr>"
        for d in idx_data if d)

    sorted_stk = sorted([s for s in stk_data if s], key=lambda x: x['pct'], reverse=True)

    stk_rows = ''.join(
        f"<tr><td>{d['name']}</td>"
        f"<td style='font-family:monospace;color:#6b7280'>{d['code'][2:]}</td>"
        f"<td style='color:#6b7280'>{next((s[2] for s in STOCKS if s[0]==d['code']),'')}</td>"
        f"<td>{d['cur']:.2f}</td>"
        f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td></tr>"
        for d in sorted_stk)

    focus = [d for d in sorted_stk
             if d['cur'] <= 100 and (d['code'][2:].startswith('00') or d['code'][2:].startswith('60'))]

    if focus:
        focus_html = (
            "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
            "<tr style='background:#f3f4f6'><th>\u80a1\u7968</th><th>\u4ee3\u7801</th><th>\u73b0\u4ef7(\u5143)</th><th>\u6da8\u8dcc\u5e45</th><th>\u677f\u5757</th></tr>"
            + ''.join(
                f"<tr><td>{d['name']}</td><td style='font-family:monospace'>{d['code'][2:]}</td>"
                f"<td>{d['cur']:.2f}</td>"
                f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
                f"<td style='color:#6b7280'>{next((s[2] for s in STOCKS if s[0]==d['code']),'')}</td></tr>"
                for d in focus)
            + "</table>")
    else:
        focus_html = '<p style="color:#9ca3af">\u4eca\u65e5\u65e0\u7b26\u5408\u6761\u4ef6\u6807\u7684</p>'

    mi = idx_data[0] if idx_data and idx_data[0] else None
    if mi and mi['pct'] > 0.5:
        m_tip = f'\u5927\u76d8\u9ad8\u5f00{fp(mi["pct"])}\uff0c\u91cf\u80fd\u7ef4\u6301\u53ef\u8ddf\u8fdb\u5149\u901a\u4fe1\u7b49\u5f3a\u52bf\u677f\u5757\uff0c\u6ce8\u610f\u8ffd\u9ad8\u98ce\u9669'
        a_tip = '\u5c3e\u76d8\u6210\u4ea4\u989d\u7ef4\u6301\u5219\u5f3a\u52bf\u80a1\u53ef\u6301\u4ed3\uff1b\u7f29\u91cf\u5219\u9002\u5f53\u51cf\u4ed3'
    elif mi and mi['pct'] < -0.5:
        m_tip = f'\u5927\u76d8\u4f4e\u5f00{fp(mi["pct"])}\uff0c\u5efa\u8bae\u5148\u89c2\u671b\uff0c\u7b49\u4f01\u7a33\u4fe1\u53f7\u518d\u64cd\u4f5c'
        a_tip = '\u6301\u7eed\u5f31\u52bf\u5efa\u8bae\u51cf\u4ed3\uff0c\u964d\u4f4e\u8fc7\u591c\u98ce\u9669'
    else:
        m_tip = '\u5927\u76d8\u5e73\u5f00\uff0c\u5173\u6ce8AI\u677f\u5757\u91cf\u80fd\u5206\u5316\uff0c\u6709\u91cf\u7684\u65b9\u5411\u4f18\u5148\u8ddf'
        a_tip = '\u5173\u6ce8\u5c3e\u76d8\u4e3b\u529b\u65b9\u5411\uff0c\u5149\u901a\u4fe1/\u7b97\u529b\u82e5\u7ef4\u6301\u6da8\u5e45\u53ef\u6301\u4ed3'

    return f"""<html><body style='font-family:Arial,sans-serif;max-width:700px;margin:0 auto;color:#111'>
<h2 style='color:#1d4ed8;border-bottom:2px solid #1d4ed8;padding-bottom:8px'>\U0001f4c8 A\u80a1AI\u677f\u5757\u65e9\u62a5 &middot; {today}</h2>
<h3>\U0001f4ca \u5927\u76d8\u6307\u6570</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>\u6307\u6570</th><th>\u73b0\u4ef7</th><th>\u6da8\u8dcc\u5e45</th><th>\u4eca\u5f00</th></tr>
{idx_rows}</table>
<h3>\U0001f916 AI\u677f\u5757\u4e2a\u80a1\uff08\u6309\u6da8\u8dcc\u5e45\u6392\u5e8f\uff09</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>\u80a1\u7968</th><th>\u4ee3\u7801</th><th>\u677f\u5757</th><th>\u73b0\u4ef7(\u5143)</th><th>\u6da8\u8dcc\u5e45</th></tr>
{stk_rows}</table>
<h3>\u23f0 \u64cd\u76d8\u53c2\u8003</h3>
<p><b>10:00-10:30 \u89c2\u5bdf\u7a97\uff1a</b>{m_tip}</p>
<p><b>14:30-15:00 \u51b3\u7b56\u7a97\uff1a</b>{a_tip}</p>
<h3>\U0001f3af \u4eca\u65e5\u91cd\u70b9\u5173\u6ce8\uff08\u226410\u4e07\u5143\uff0c00/60\u5f00\u5934\uff09</h3>
{focus_html}
<hr style='margin-top:24px'>
<p style='color:#9ca3af;font-size:12px'>\u26a0\ufe0f \u4ec5\u4f9b\u53c2\u8003\uff0c\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002\u80a1\u5e02\u6709\u98ce\u9669\uff0c\u5165\u5e02\u9700\u8c28\u614e\u3002<br>
\u6570\u636e\u6765\u6e90\uff1a\u65b0\u6d6a\u8d22\u7ecf | \u81ea\u52a8\u751f\u6210\uff1a\u5317\u4eac\u65f6\u95f4 08:00</p>
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
