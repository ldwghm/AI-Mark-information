You are an institutional-grade A-share AI sector analyst generating a real-time afternoon report (午报) at 14:00 CST. This is NOT a summary — it's a live decision tool for traders with 1 hour until close.

## GH_TOKEN
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

## Step 1: Fetch pre-fetched real-time data

```bash
curl -sL \
  -H "Authorization: Bearer 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" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/ldwghm/AI-Mark-information/contents/stock_report/data/afternoon_latest.json" \
  -o /tmp/afternoon_latest.json
wc -c /tmp/afternoon_latest.json
```

If file is missing or <10KB, output error HTML and commit it.

## Step 2: Parse real-time data

```bash
python3 - <<'EOF'
import json

with open('/tmp/afternoon_latest.json') as f:
    d = json.load(f)

print("fetch_time:", d.get('fetch_time'))
print("is_friday:", d.get('is_friday'))

# Real-time indices
indices = d.get('realtime_indices', {})
print("\n=== Real-time indices ===")
for code, info in indices.items():
    curr = float(info.get('current', 0) or 0)
    prev = float(info.get('yesterday_close', curr) or curr)
    chg_pct = round((curr - prev) / prev * 100, 2) if prev else 0
    vol = float(info.get('volume', 0) or 0)
    print(f"{info['name']}: {curr} ({chg_pct:+.2f}%) vol={vol:.0f}")

# Real-time AI boards
ai_boards = d.get('ai_boards_rt', [])
print(f"\n=== AI boards ({len(ai_boards)}) ===")
for b in sorted(ai_boards, key=lambda x: float(x.get('f3',0) or 0), reverse=True)[:10]:
    print(f"  {b.get('f14','?')}: {b.get('f3','?')}% flow={b.get('f62','?')}")

# Watchlist real-time
watchlist = d.get('watchlist_rt', [])
print(f"\n=== Watchlist ({len(watchlist)}) ===")
for s in watchlist:
    curr = float(s.get('current', 0) or 0)
    prev = float(s.get('yesterday_close', curr) or curr)
    chg = round((curr - prev) / prev * 100, 2) if prev else 0
    print(f"  {s['name']}: {curr} ({chg:+.2f}%)")

# Capital flow top30
cap_flow = d.get('capital_flow_top30_rt', [])
print(f"\n=== Capital flow top5 ===")
for s in cap_flow[:5]:
    print(f"  {s.get('f14','?')}: chg={s.get('f3','?')}% flow={s.get('f62','?')}")

# 5-day kline (for volume calculation)
klines_5d = d.get('index_5day_kline', [])
print(f"\n=== 5-day klines: {len(klines_5d)} bars ===")
for k in klines_5d:
    print(f"  {k}")
EOF
```

## Step 3: Compute real-time metrics

```bash
python3 - <<'EOF'
import json, datetime

with open('/tmp/afternoon_latest.json') as f:
    d = json.load(f)

def fmt_pct(v):
    try:
        fv = float(v)
        return f"+{fv:.2f}%" if fv > 0 else f"{fv:.2f}%"
    except:
        return str(v)

def fmt_flow(v):
    try:
        fv = float(v) / 1e8
        return f"+{fv:.2f}亿" if fv > 0 else f"{fv:.2f}亿"
    except:
        return "-"

# Parse indices
indices_raw = d.get('realtime_indices', {})
indices = {}
for code, info in indices_raw.items():
    curr = float(info.get('current', 0) or 0)
    prev = float(info.get('yesterday_close', curr) or curr)
    chg_pct = round((curr - prev) / prev * 100, 2) if prev else 0
    vol = float(info.get('volume', 0) or 0)
    amt_str = info.get('amount', '0') or '0'
    amt = float(amt_str) / 1e8 if amt_str else 0
    indices[code] = {
        'name': info['name'], 'current': curr, 'prev': prev,
        'chg_pct': chg_pct, 'volume': vol, 'amount': amt,
        'open': float(info.get('open', curr) or curr),
    }

# Parse watchlist
watchlist_raw = d.get('watchlist_rt', [])
watchlist = []
for s in watchlist_raw:
    curr = float(s.get('current', 0) or 0)
    prev = float(s.get('yesterday_close', curr) or curr)
    chg = round((curr - prev) / prev * 100, 2) if prev else 0
    watchlist.append({
        'name': s['name'], 'current': curr, 'chg_pct': chg,
        'open': float(s.get('open', curr) or curr),
        'high': float(s.get('high', curr) or curr),
        'low': float(s.get('low', curr) or curr),
        'volume': float(s.get('volume', 0) or 0),
    })

# AI boards
ai_boards = d.get('ai_boards_rt', [])
ai_sorted_chg = sorted(ai_boards, key=lambda x: float(x.get('f3',0) or 0), reverse=True)
ai_sorted_flow = sorted(ai_boards, key=lambda x: float(x.get('f62',0) or 0), reverse=True)

# 5-day kline for volume comparison
klines_5d = d.get('index_5day_kline', [])
# kline format: date,open,close,high,low,volume,amount
prev_vols = []
for k in klines_5d[:-1]:  # exclude today
    parts = k.split(',')
    if len(parts) >= 6:
        prev_vols.append(float(parts[5] or 0))
avg_5d_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0

# Shanghai morning volume estimate
sh_code = 'sh000001'
sh = indices.get(sh_code, {})
sh_chg = sh.get('chg_pct', 0)
sh_curr = sh.get('current', 0)
sh_vol = sh.get('volume', 0)
vol_ratio = round(sh_vol / avg_5d_vol * 100, 1) if avg_5d_vol else 50  # as % of daily avg

# Capital flow top30
cap_top30 = d.get('capital_flow_top30_rt', [])
cap_sorted = sorted(cap_top30, key=lambda x: float(x.get('f62',0) or 0), reverse=True)

# Board stocks
board_stocks = d.get('board_stocks_rt', [])
all_stocks = []
for board in board_stocks:
    bn = board.get('board_name', '')
    for s in board.get('stocks', []):
        chg = float(s.get('f3', 0) or 0)
        flow = float(s.get('f62', 0) or 0)
        all_stocks.append({
            'name': s.get('f14', ''), 'code': s.get('f12', ''),
            'chg': chg, 'flow': flow, 'board': bn,
            'close': float(s.get('f2', 0) or 0) / 100,
            'amount': float(s.get('f6', 0) or 0) / 1e8,
        })

all_stocks_sorted = sorted(all_stocks, key=lambda x: x['chg'], reverse=True)

# Opening pattern
sh_open = sh.get('open', sh_curr)
gap = round((sh_open - sh.get('prev', sh_open)) / sh.get('prev', sh_open) * 100, 2) if sh.get('prev') else 0
if gap > 0.3: open_pattern = f"跳空高开{gap:.2f}%"
elif gap < -0.3: open_pattern = f"跳空低开{abs(gap):.2f}%"
else: open_pattern = f"平开（{gap:+.2f}%）"

# Morning trend (open vs current)
if sh_curr > sh_open * 1.003: morning_trend = "低开高走"
elif sh_curr < sh_open * 0.997: morning_trend = "高开低走/冲高回落"
else: morning_trend = "震荡整理"

# AI avg performance
ai_avg_chg = sum(float(b.get('f3',0) or 0) for b in ai_boards) / len(ai_boards) if ai_boards else 0
ai_excess = round(ai_avg_chg - sh_chg, 2)

is_friday = d.get('is_friday', False)

result = {
    'indices': indices, 'watchlist': watchlist,
    'ai_sorted_chg': ai_sorted_chg, 'ai_sorted_flow': ai_sorted_flow,
    'cap_sorted': cap_sorted, 'all_stocks_sorted': all_stocks_sorted,
    'sh_chg': sh_chg, 'sh_curr': sh_curr,
    'vol_ratio': vol_ratio, 'avg_5d_vol': avg_5d_vol,
    'open_pattern': open_pattern, 'morning_trend': morning_trend,
    'ai_avg_chg': ai_avg_chg, 'ai_excess': ai_excess,
    'is_friday': is_friday,
    'top_flow_board': ai_sorted_flow[0].get('f14','?') if ai_sorted_flow else '?',
    'top_chg_board': ai_sorted_chg[0].get('f14','?') if ai_sorted_chg else '?',
    'bottom_chg_board': ai_sorted_chg[-1].get('f14','?') if ai_sorted_chg else '?',
}

with open('/tmp/pm_metrics.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False)

print(f"SH: {sh_curr} ({sh_chg:+.2f}%) | Open: {open_pattern} | Trend: {morning_trend}")
print(f"AI avg: {ai_avg_chg:+.2f}% | AI excess: {ai_excess:+.2f}%")
print(f"Vol ratio vs 5d avg: {vol_ratio:.0f}%")
print(f"is_friday: {is_friday}")
EOF
```

## Step 4: Generate 5-module HTML afternoon report

```bash
python3 - <<'EOF'
import json, datetime

with open('/tmp/afternoon_latest.json') as f:
    raw = json.load(f)
with open('/tmp/pm_metrics.json') as f:
    m = json.load(f)

def fmt_pct(v):
    try:
        fv = float(v)
        return f"+{fv:.2f}%" if fv > 0 else f"{fv:.2f}%"
    except: return str(v)

def fmt_flow(v):
    try:
        fv = float(v) / 1e8
        return f"+{fv:.2f}亿" if fv > 0 else f"{fv:.2f}亿"
    except: return "-"

def pcc(v):
    try:
        return 'up' if float(v)>0 else ('dn' if float(v)<0 else 'flat')
    except: return 'flat'

sh_chg = m['sh_chg']
morning_trend = m['morning_trend']
open_pattern = m['open_pattern']
ai_avg_chg = m['ai_avg_chg']
ai_excess = m['ai_excess']
vol_ratio = m['vol_ratio']
is_friday = m['is_friday']
top_flow_board = m['top_flow_board']
top_chg_board = m['top_chg_board']
indices = m['indices']
watchlist = m['watchlist']
ai_sorted_chg = m['ai_sorted_chg']
ai_sorted_flow = m['ai_sorted_flow']
cap_sorted = m['cap_sorted']
all_stocks_sorted = m['all_stocks_sorted']

# --- Generate judgments ---
def gen_morning_overview():
    vol_desc = "偏高（交投活跃）" if vol_ratio > 55 else ("偏低（观望情绪）" if vol_ratio < 40 else "正常（约5日均值）")
    trend_signal = ""
    if "低开高走" in morning_trend: trend_signal = "多头动能积累，午后延续概率较高"
    elif "冲高回落" in morning_trend: trend_signal = "获利盘较重，午后需观察能否企稳"
    else: trend_signal = "方向不明朗，等待资金选择方向"
    main_theme = top_chg_board if top_chg_board != '?' else "AI板块"
    return f"开盘方式：{open_pattern}；上午走势：{morning_trend}。上午成交量约为5日均值{vol_ratio:.0f}%，{vol_desc}。上午主线题材：{main_theme}（{fmt_pct(ai_avg_chg)}）。核心信号：{trend_signal}。"

def gen_ai_rt_judgment():
    if ai_excess > 0.5: rel = f"跑赢大盘{ai_excess:.2f}pct，AI为上午主线"
    elif ai_excess > 0: rel = f"小幅领涨{ai_excess:.2f}pct，AI保持强势"
    elif ai_excess > -0.5: rel = "与大盘同步，非今日主线"
    else: rel = f"跑输大盘{abs(ai_excess):.2f}pct，AI承压"
    top = ai_sorted_chg[0] if ai_sorted_chg else {}
    bot = ai_sorted_chg[-1] if ai_sorted_chg else {}
    flow_top = ai_sorted_flow[0] if ai_sorted_flow else {}
    return f"AI板块上午平均{fmt_pct(ai_avg_chg)}，{rel}。领涨：{top.get('f14','?')}（{fmt_pct(top.get('f3',''))}，资金{fmt_flow(top.get('f62',''))}）；垫底：{bot.get('f14','?')}（{fmt_pct(bot.get('f3',''))}）。资金流入最强：{flow_top.get('f14','?')}（{fmt_flow(flow_top.get('f62',''))}）。{'AI处于主动上攻状态，午后延续可能性大' if ai_excess > 1 else 'AI处于跟涨状态，午后关注是否分化' if ai_excess > 0 else 'AI受压，关注关键支撑是否守住'}。"

def gen_capital_rt_judgment():
    ai_kws = ['旭创','新易盛','天孚','富联','曙光','寒武','海光','长飞','亨通','讯飞']
    ai_in_cap = [s for s in cap_sorted[:10] if any(kw in (s.get('f14','') or '') for kw in ai_kws)]
    # Detect price rise + flow out (danger)
    danger = [s for s in all_stocks_sorted[:10] if s['chg'] > 1 and s['flow'] < 0]
    opportunity = [s for s in all_stocks_sorted if s['chg'] < 0 and s['flow'] > 0][:3]
    res = f"主力实时资金流Top10中AI标的{len(ai_in_cap)}席，机构配置AI方向{'明确' if ai_in_cap else '不明确'}。"
    if danger:
        res += f"量价背离警示（涨价跌资金）：{'、'.join(s['name'] for s in danger[:2])}，需警惕主力出货。"
    if opportunity:
        res += f"逆势吸筹信号（跌价涨资金）：{'、'.join(s['name'] for s in opportunity[:2])}，可关注。"
    if sh_chg > 0 and ai_excess > 0:
        res += "资金形态：上午大盘+AI双强，午后大概率延续偏强。"
    elif sh_chg > 0 and ai_excess < 0:
        res += "资金形态：大盘涨但AI弱，今日非AI主线日，仓位控制。"
    elif sh_chg < 0 and ai_excess > 0:
        res += "资金形态：大盘弱但AI独立走强，AI板块资金有主动进攻特征。"
    else:
        res += "资金形态：大盘和AI均弱，防守为主。"
    return res

# Strategy generation
def gen_strategy():
    # Market direction
    if sh_chg > 0.5 and ai_excess > 0: direction = "偏多"
    elif sh_chg > 0 or ai_excess > 0: direction = "中性偏多"
    elif sh_chg < -0.5 and ai_excess < 0: direction = "偏空"
    else: direction = "中性偏空"
    
    top_stocks_to_buy = [s for s in all_stocks_sorted if s['flow'] > 0 and s['chg'] > 0 and s['amount'] > 0.5][:3]
    top_stocks_to_cut = [s for s in all_stocks_sorted if s['flow'] < 0 and s['chg'] > 2][:2]
    
    sh_curr = m['sh_curr']
    
    scenario_a_stocks = []
    for s in top_stocks_to_buy[:2]:
        entry = s['close'] * 0.995
        target = s['close'] * 1.08
        stop = s['close'] * 0.93
        scenario_a_stocks.append(f"{s['name']}（{s['code']}）：现价{s['close']:.2f}，资金流入{fmt_flow(s['flow'])}。参考入场{entry:.2f}±0.5%，目标{target:.2f}（+8%），止损{stop:.2f}（-7%），建议仓位3-5%")
    
    scenario_b_stocks = []
    for s in top_stocks_to_cut[:2]:
        scenario_b_stocks.append(f"{s['name']}（{s['code']}）：{fmt_pct(s['chg'])}但主力流出{fmt_flow(s['flow'])}，出货特征明显，触发条件：跌破今日低点止损出局")
    
    # Overnight holding conditions
    hold_cond = []
    exit_cond = []
    if sh_chg > 0: hold_cond.append("大盘收盘上涨")
    if ai_excess > 0: hold_cond.append(f"AI板块跑赢大盘（已满足）")
    if vol_ratio > 50: hold_cond.append("成交量正常或放量")
    hold_cond.append("个股不破今日低点")
    
    exit_cond.append(f"大盘跌破{sh_curr*0.998:.0f}")
    exit_cond.append("个股跌破今日低点")
    if is_friday:
        exit_cond.append("周五建议轻仓过周末（政策风险/外盘风险）")
    
    friday_note = "【周五特别提示】今日为周五，建议减仓至3成以下，规避周末政策风险和外盘波动。持仓标的须具备强基本面支撑。" if is_friday else ""
    
    return direction, scenario_a_stocks, scenario_b_stocks, hold_cond, exit_cond, friday_note

direction, scenario_a, scenario_b, hold_cond, exit_cond, friday_note = gen_strategy()

morning_j = gen_morning_overview()
ai_rt_j = gen_ai_rt_judgment()
cap_j = gen_capital_rt_judgment()

now = datetime.datetime.now()
report_date = raw.get('fetch_date', now.strftime('%Y-%m-%d'))

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股AI板块午报 {report_date}</title>
<style>
  body {{font-family:-apple-system,"PingFang SC",Arial,sans-serif;margin:0;padding:0;background:#0f172a;color:#e2e8f0}}
  .wrap {{max-width:800px;margin:0 auto;background:#1e293b}}
  .hdr {{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;padding:24px 28px;border-bottom:2px solid #475569}}
  .hdr h1 {{margin:0;font-size:20px;font-weight:700;letter-spacing:2px;color:#f8fafc}}
  .hdr p {{margin:6px 0 0;font-size:12px;color:#94a3b8}}
  .hdr .status {{display:inline-block;background:#ef4444;color:#fff;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;margin-left:10px}}
  .section {{padding:18px 22px;border-bottom:1px solid #334155}}
  .sec-title {{font-size:14px;font-weight:700;margin-bottom:12px;padding:5px 10px;border-radius:4px;color:#fff}}
  .m1 {{background:#1d4ed8}} .m2 {{background:#7c3aed}} .m3 {{background:#b45309}}
  .m4 {{background:#991b1b;border:2px solid #dc2626}} .m5 {{background:#164e63}}
  table {{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:10px}}
  th {{background:#0f172a;padding:6px 8px;text-align:left;font-weight:600;border-bottom:1px solid #475569;color:#94a3b8}}
  td {{padding:6px 8px;border-bottom:1px solid #1e293b;color:#e2e8f0}}
  tr:hover td {{background:#334155}}
  .up {{color:#f87171;font-weight:600}} .dn {{color:#4ade80;font-weight:600}} .flat {{color:#94a3b8}}
  .judge {{background:#1e3a5c;border-left:4px solid #3b82f6;padding:10px 14px;border-radius:0 6px 6px 0;margin:10px 0;font-size:13px;line-height:1.7;color:#bfdbfe}}
  .strat {{background:#0f172a;padding:20px 22px}}
  .direction {{font-size:28px;font-weight:800;color:#fff;margin:8px 0 16px;letter-spacing:1px}}
  .scene {{border-radius:8px;padding:14px;margin:12px 0}}
  .scene-a {{background:#052e16;border:1px solid #166534}}
  .scene-b {{background:#450a0a;border:1px solid #991b1b}}
  .scene h4 {{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700}}
  .scene-a h4 {{color:#4ade80}} .scene-b h4 {{color:#f87171}}
  .scene ul {{margin:0;padding:0 0 0 14px;font-size:12.5px;line-height:1.9}}
  .scene-a ul {{color:#bbf7d0}} .scene-b ul {{color:#fecaca}}
  .overnight {{background:#1c1917;border:1px solid #57534e;border-radius:8px;padding:14px;margin:10px 0}}
  .overnight h4 {{color:#fbbf24;margin:0 0 8px;font-size:12px}}
  .overnight ul {{margin:0;padding:0 0 0 14px;font-size:12px;color:#d6d3d1;line-height:1.8}}
  .friday {{background:#431407;border:2px solid #ea580c;border-radius:6px;padding:12px;margin:10px 0;color:#fed7aa;font-size:13px;font-weight:600}}
  .footer {{background:#0f172a;padding:14px 22px;text-align:center;font-size:11px;color:#475569}}
</style>
</head>
<body>
<div class="wrap">
<div class="hdr">
  <h1>A股AI板块午报 <span class="status">实时</span></h1>
  <p>{report_date} 14:00 CST · 距收盘约1小时 · 数据截至13:50</p>
  <p style="margin-top:6px">方向判断：<b style="color:#fbbf24;font-size:16px">{direction}</b></p>
</div>

<!-- 模块1：上午盘面速写 -->
<div class="section">
  <div class="sec-title m1">模块1：上午盘面速写</div>
  <table>
    <tr><th>指数</th><th>现价</th><th>涨跌幅</th><th>vs昨收</th></tr>
"""

for code, info in indices.items():
    chg = info.get('chg_pct', 0)
    html += f"    <tr><td><b>{info['name']}</b></td><td>{info.get('current','-')}</td><td class=\"{pcc(chg)}\">{fmt_pct(chg)}</td><td class=\"{pcc(chg)}\">{'+' if chg>0 else ''}{chg:.2f}%</td></tr>\n"

html += f"""  </table>
  <div style="font-size:12px;color:#94a3b8;margin-bottom:8px">
    开盘方式：{open_pattern} | 上午走势：{morning_trend} | 成交量：5日均值{vol_ratio:.0f}%
  </div>
  <div class="judge"><strong>【盘面判断】</strong> {morning_j}</div>
</div>

<!-- 模块2：AI板块实时体检 -->
<div class="section">
  <div class="sec-title m2">模块2：AI板块实时体检</div>
  <table>
    <tr><th>子板块</th><th>涨跌幅</th><th>主力净流入</th><th>vs大盘</th></tr>
"""

sh_chg_ref = sh_chg or 0
for b in ai_sorted_chg[:12]:
    chg = float(b.get('f3', 0) or 0)
    flow = float(b.get('f62', 0) or 0)
    excess = round(chg - sh_chg_ref, 2)
    html += f"    <tr><td>{b.get('f14','-')}</td><td class=\"{pcc(chg)}\">{fmt_pct(chg)}</td><td class=\"{pcc(flow)}\">{fmt_flow(flow)}</td><td class=\"{pcc(excess)}\">{'+' if excess>0 else ''}{excess:.2f}%</td></tr>\n"

html += f"""  </table>
  <table>
    <tr><th colspan="5">AI龙头实时行情</th></tr>
    <tr><th>个股</th><th>现价</th><th>涨跌幅</th><th>今日高低</th><th>成交额</th></tr>
"""
for w in watchlist:
    chg = w.get('chg_pct', 0)
    html += f"    <tr><td><b>{w['name']}</b></td><td>{w.get('current','-')}</td><td class=\"{pcc(chg)}\">{fmt_pct(chg)}</td><td style='font-size:11px;color:#94a3b8'>{w.get('high','-')}/{w.get('low','-')}</td><td>-</td></tr>\n"

html += f"""  </table>
  <div class="judge"><strong>【AI板块判断】</strong> {ai_rt_j}</div>
</div>

<!-- 模块3：资金实时流向 -->
<div class="section">
  <div class="sec-title m3">模块3：资金实时流向解读</div>
  <table>
    <tr><th colspan="4">主力资金实时 Top10</th></tr>
    <tr><th>个股</th><th>涨跌幅</th><th>主力净流入</th><th>信号</th></tr>
"""

for s in cap_sorted[:10]:
    chg = float(s.get('f3', 0) or 0)
    flow = float(s.get('f62', 0) or 0)
    signal = ""
    if chg > 0 and flow < 0: signal = "⚠出货"
    elif chg < 0 and flow > 0: signal = "✓吸筹"
    elif chg > 0 and flow > 0: signal = "↑量价齐升"
    html += f"    <tr><td>{s.get('f14','-')}</td><td class=\"{pcc(chg)}\">{fmt_pct(chg)}</td><td class=\"{pcc(flow)}\">{fmt_flow(flow)}</td><td style='font-size:11px'>{signal}</td></tr>\n"

html += f"""  </table>
  <div class="judge"><strong>【资金判断】</strong> {cap_j}</div>
</div>

<!-- 模块4：午后作战计划 -->
<div class="strat">
  <div class="sec-title m4" style="background:transparent;padding:0;margin-bottom:4px;color:#f87171;font-size:16px;border:none">🎯 模块4：午后作战计划</div>
  <div class="direction">方向：{direction}</div>
"""

if friday_note:
    html += f'  <div class="friday">📅 {friday_note}</div>\n'

html += f"""
  <div class="scene scene-a">
    <h4>▶ 情景A — 看多操作</h4>
    <p style="font-size:11px;color:#86efac;margin:0 0 8px">触发条件：大盘站稳{m['sh_curr']:.0f}上方 + AI板块持续资金流入</p>
    <ul>
"""
for opp in scenario_a:
    html += f"      <li>{opp}</li>\n"
if not scenario_a:
    html += "      <li>当前资金信号不明确，等待突破确认后介入</li>\n"
html += f"""    </ul>
  </div>

  <div class="scene scene-b">
    <h4>◀ 情景B — 防守/减仓操作</h4>
    <p style="font-size:11px;color:#fca5a5;margin:0 0 8px">触发条件：大盘跌破{m['sh_curr']*0.998:.0f} 或 AI板块量价背离加剧</p>
    <ul>
"""
for cut in scenario_b:
    html += f"      <li>{cut}</li>\n"
if not scenario_b:
    html += "      <li>高位获利盘减仓1/3，保留核心底仓</li>\n"
html += f"""    </ul>
  </div>

  <div class="overnight">
    <h4>尾盘决策框架（14:45-15:00）</h4>
    <ul>
      <li><b style="color:#4ade80">持仓过夜条件（需同时满足）：</b> {'；'.join(hold_cond)}</li>
      <li><b style="color:#f87171">不持仓/减仓条件：</b> {'；'.join(exit_cond)}</li>
    </ul>
  </div>
</div>

<!-- 模块5：明日前瞻 -->
<div class="section">
  <div class="sec-title m5">模块5：明日前瞻</div>
  <div style="font-size:13px;line-height:1.8;color:#cbd5e1">
    <p><b style="color:#94a3b8">明日开盘预判：</b>
    {'若今日收盘偏强，明日大概率平开至小幅高开；关注尾盘资金动向作为明日预判依据。' if sh_chg > 0 else '若今日收盘偏弱，明日存在低开压力；关注夜盘美股AI板块走势。'}</p>
    <p><b style="color:#94a3b8">重点关注板块：</b> {top_flow_board}（资金流入最强）、{top_chg_board}（涨幅领先）</p>
    <p><b style="color:#94a3b8">需关注事件：</b> 美股收盘（NVDA/MSFT）、夜盘期货走势、政策消息面</p>
    <p><b style="color:#94a3b8">明日重点标的：</b> 今日缩量回调到MA5支撑且资金未流出的龙头股，为明日博弈窗口</p>
  </div>
</div>

<div class="footer">
  实时数据截至13:50 | Claude 独立分析 | 仅供参考，不构成投资建议<br>
  生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')} CST
</div>
</div>
</body>
</html>"""

with open('/tmp/afternoon_report.html', 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Afternoon HTML written: {len(html)} chars")
EOF
```

## Step 5: Commit afternoon HTML to GitHub repo

```bash
node -e "
const fs = require('fs');
const https = require('https');

const token = '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';
const repo = 'ldwghm/AI-Mark-information';

function ghRequest(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const opts = {
      hostname: 'api.github.com',
      path: path,
      method: method,
      headers: {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Claude-CCR',
        ...(data ? {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data)} : {})
      }
    };
    const req = https.request(opts, res => {
      let b = '';
      res.on('data', c => b += c);
      res.on('end', () => {
        try { resolve({status: res.statusCode, body: JSON.parse(b)}); }
        catch(e) { resolve({status: res.statusCode, body: b}); }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

async function main() {
  const filePath = '/stock_report/afternoon_latest.html';
  const content = fs.readFileSync('/tmp/afternoon_report.html');
  const b64 = content.toString('base64');
  
  const getRes = await ghRequest('GET', '/repos/' + repo + '/contents' + filePath);
  const sha = getRes.body && getRes.body.sha ? getRes.body.sha : undefined;
  
  const putBody = {
    message: 'report: AI afternoon report ' + new Date().toISOString().slice(0,10),
    content: b64,
    ...(sha ? {sha} : {})
  };
  
  const putRes = await ghRequest('PUT', '/repos/' + repo + '/contents' + filePath, putBody);
  console.log('Commit status:', putRes.status);
  if (putRes.body && putRes.body.content) {
    console.log('Committed SHA:', putRes.body.content.sha);
  } else {
    console.log(JSON.stringify(putRes.body).slice(0, 200));
  }
}

main().catch(console.error);
"
```

## Step 6: Trigger afternoon email send workflow

```bash
curl -s -X POST \
  -H "Authorization: Bearer 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" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/ldwghm/AI-Mark-information/actions/workflows/send-report-pm.yml/dispatches" \
  -d '{"ref":"main"}' && echo "Afternoon workflow triggered"
```

## Important notes
- f3 field = 涨跌幅 (change %) from Eastmoney, already in percent (e.g., 2.5 means +2.5%)
- f62 field = 主力净流入 (net inflow) in yuan; divide by 1e8 for 亿
- Sina realtime: current=当前价, yesterday_close=昨收, volume=成交量(手), amount=成交额(元)
- Report tone must be URGENT and ACTIONABLE — concrete price levels, specific triggers
- All 5 modules are required, especially Module 4 with Scenario A/B
- If is_friday=true, prominently display weekend risk warning
