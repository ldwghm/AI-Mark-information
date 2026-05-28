"""
stock_report_pm.py — Afternoon report: read pre-fetched JSON + CCR analysis → render HTML → send via Resend.

New flow (P2):
  1. GitHub Actions fetch_market_data_pm.py → afternoon_latest.json (market data + technicals)
  2. CCR trigger → afternoon_analysis.json (AI insights, predictions)
  3. This script reads both → report_renderer → HTML → Resend API

Fallback: if JSON not available, fetches real-time data directly (legacy mode).
"""
import requests, os, json, time
from datetime import datetime
from report_renderer import render_afternoon_report

RESEND_API_KEY = os.environ['RESEND_API_KEY']
GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
RECIPIENT      = '1654155512@qq.com'
REPO           = 'ldwghm/AI-Mark-information'

# ── GitHub helpers ─────────────────────────────────────────────────────────

def gh_read_json(path):
    if not GITHUB_TOKEN: return None
    try:
        r = requests.get(
            f'https://api.github.com/repos/{REPO}/contents/{path}',
            headers={'Authorization': f'Bearer {GITHUB_TOKEN}',
                     'Accept': 'application/vnd.github.v3.raw'},
            timeout=15)
        if r.status_code == 200:
            return json.loads(r.text)
        print(f'[gh] {path}: HTTP {r.status_code}')
    except Exception as e:
        print(f'[gh] Error: {e}')
    return None

# ── Legacy real-time fetch (fallback if JSON unavailable) ──────────────────

INDICES = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
INDEX_NAMES = {
    'sh000001': '上证指数', 'sz399001': '深证成指',
    'sz399006': '创业板指', 'sh000688': '科创50',
}

WATCHLIST = [
    ('sz300308', '中际旭创'), ('sz300394', '天孚通信'),
    ('sz300502', '新易盛'),   ('sz002281', '光迅科技'),
    ('sh600522', '中天科技'), ('sh600487', '亨通光电'),
    ('sh600498', '烽火通信'), ('sh603019', '中科曙光'),
    ('sh601138', '工业富联'), ('sz000977', '浪潮信息'),
    ('sh688041', '海光信息'), ('sh688256', '寒武纪'),
    ('sz300474', '景嘉微'),   ('sh603986', '兆易创新'),
    ('sz002049', '紫光国微'), ('sh688008', '澜起科技'),
    ('sz002371', '北方华创'), ('sh688981', '中芯国际'),
    ('sz002236', '大华技术'), ('sz300750', '宁德时代'),
    ('sz002460', '赣锋锂业'), ('sz002074', '国轩高科'),
    ('sh600989', '宝丰能源'), ('sz002916', '深南电路'),
]

def _parse_sina_line(line):
    if '="' not in line or line.strip().endswith('="";'):
        return None
    code = line.split('hq_str_')[1].split('=')[0]
    d = line.split('="')[1].rstrip('";').split(',')
    if len(d) < 10: return None
    try:
        prev, cur = float(d[2]), float(d[3])
        return {
            'code': code, 'name': d[0],
            'current': cur, 'prev': prev,
            'open': float(d[1]),
            'high': float(d[4]), 'low': float(d[5]),
            'volume': float(d[8]) if d[8] else 0,
            'amount': float(d[9]) if d[9] else 0,
            'change_pct': (cur - prev) / prev * 100 if prev else 0,
        }
    except:
        return None

def fetch_realtime_fallback():
    """Fetch real-time data directly from Sina as fallback."""
    all_codes = INDICES + [s[0] for s in WATCHLIST]
    try:
        r = requests.get(
            f'https://hq.sinajs.cn/list={",".join(all_codes)}',
            headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'},
            timeout=12)
        r.encoding = 'gbk'
    except Exception as e:
        print(f'[fallback] Sina fetch error: {e}')
        return None

    hq = {}
    for line in r.text.strip().split('\n'):
        p = _parse_sina_line(line)
        if p:
            hq[p['code']] = p

    # Build market_data structure matching afternoon_latest.json
    rt_indices = {}
    for code in INDICES:
        if code in hq:
            d = hq[code]
            rt_indices[code] = {
                'price': d['current'], 'chg': d['change_pct'],
                'current': d['current'], 'change_pct': d['change_pct'],
                'open': d['open'], 'high': d['high'], 'low': d['low'],
                'amount': d['amount'],
            }

    watchlist_rt = []
    for code, name in WATCHLIST:
        if code in hq:
            d = hq[code]
            watchlist_rt.append({
                'name': d['name'], 'current': d['current'],
                'change_pct': d['change_pct'],
                'high': d['high'], 'low': d['low'],
                'volume': d['volume'], 'yesterday_close': d['prev'],
                'open': d['open'],
            })

    return {
        'fetch_time': datetime.now().isoformat(),
        'fetch_date': datetime.now().strftime('%Y-%m-%d'),
        'report_type': 'afternoon',
        'realtime_indices': rt_indices,
        'watchlist_rt': watchlist_rt,
        'ai_boards_rt': [],
        'board_stocks_rt': [],
        'capital_flow_top30_rt': [],
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    today = datetime.now().strftime('%Y-%m-%d')

    # Try new flow: read pre-fetched JSON + CCR analysis
    market_data = gh_read_json('stock_report/data/afternoon_latest.json')
    analysis = gh_read_json('stock_report/data/afternoon_analysis.json')

    if market_data:
        print(f'[main] Afternoon market data loaded: {len(market_data)} keys')
        if analysis:
            print(f'[main] Analysis loaded: {len(analysis)} keys')
        else:
            print('[main] No analysis JSON, rendering data-only report')
    else:
        # Fallback: fetch real-time data directly
        print('[main] No pre-fetched JSON, using real-time fallback')
        market_data = fetch_realtime_fallback()
        if not market_data:
            print('[main] Fallback also failed, aborting')
            exit(1)

    html = render_afternoon_report(market_data, analysis, today)
    print(f'[main] Rendered HTML: {len(html)} chars')

    # Send via Resend
    resp = requests.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {RESEND_API_KEY}',
                 'Content-Type': 'application/json'},
        json={
            'from': 'A股午报 <onboarding@resend.dev>',
            'to': [RECIPIENT],
            'subject': f'📊 A股AI板块午报 · {today} 14:00',
            'html': html,
        },
        timeout=15)
    result = resp.json()
    if 'id' in result:
        print(f'[main] Email sent! ID: {result["id"]}')
    else:
        print(f'[main] Email failed: {result}')
        exit(1)


if __name__ == '__main__':
    main()
