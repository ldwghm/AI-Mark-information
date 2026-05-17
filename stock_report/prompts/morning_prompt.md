You are an institutional-grade A-share AI sector analyst. Generate a comprehensive daily report in HTML format.

## GH_TOKEN
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

## Step 1: Fetch pre-fetched market data

```bash
curl -sL \
  -H "Authorization: Bearer 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" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/ldwghm/AI-Mark-information/contents/stock_report/data/morning_latest.json" \
  -o /tmp/morning_latest.json
```

Check file size: `wc -c /tmp/morning_latest.json` — should be >50KB. If missing, abort and output error HTML.

## Step 2: Parse JSON and compute technical indicators

Read the JSON with a bash/python one-liner:
```bash
python3 - <<'EOF'
import json, math

with open('/tmp/morning_latest.json') as f:
    d = json.load(f)

def parse_klines(klines):
    """Parse kline strings: date,open,close,high,low,volume,amount,..."""
    rows = []
    for k in klines:
        parts = k.split(',')
        if len(parts) >= 6:
            rows.append({
                'date': parts[0],
                'open': float(parts[1]) if parts[1] else 0,
                'close': float(parts[2]) if parts[2] else 0,
                'high': float(parts[3]) if parts[3] else 0,
                'low': float(parts[4]) if parts[4] else 0,
                'volume': float(parts[5]) if parts[5] else 0,
                'amount': float(parts[6]) if len(parts) > 6 and parts[6] else 0,
            })
    return rows

def ma(prices, n):
    if len(prices) < n: return None
    return round(sum(prices[-n:]) / n, 2)

def ema(prices, n):
    if len(prices) < n: return None
    k = 2 / (n + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return round(e, 2)

def macd(prices):
    if len(prices) < 26: return None, None, None
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    dif = round(ema12 - ema26, 4)
    # simplified DEA
    dea = round(dif * 0.2, 4)
    macd_val = round((dif - dea) * 2, 4)
    return dif, dea, macd_val

def bollinger(prices, n=20):
    if len(prices) < n: return None, None, None
    mid = ma(prices, n)
    variance = sum((p - mid)**2 for p in prices[-n:]) / n
    std = math.sqrt(variance)
    return round(mid + 2*std, 2), round(mid, 2), round(mid - 2*std, 2)

results = {}
for key, idx in [('shanghai','上证指数'),('shenzhen','深证成指'),('chinext','创业板指'),('star50','科创50')]:
    klines = parse_klines(d['indices'][key]['klines'])
    if not klines: continue
    closes = [k['close'] for k in klines]
    vols = [k['volume'] for k in klines]
    latest = klines[-1]
    prev = klines[-2] if len(klines) >= 2 else klines[-1]
    vol5avg = sum(vols[-6:-1]) / 5 if len(vols) >= 6 else vols[-1]
    vol_ratio = round(latest['volume'] / vol5avg, 2) if vol5avg else 1
    chg_pct = round((latest['close'] - prev['close']) / prev['close'] * 100, 2) if prev['close'] else 0
    boll_up, boll_mid, boll_low = bollinger(closes)
    dif, dea, macd_val = macd(closes)
    results[key] = {
        'name': idx,
        'close': latest['close'],
        'open': latest['open'],
        'high': latest['high'],
        'low': latest['low'],
        'chg_pct': chg_pct,
        'amount': round(latest['amount']/1e8, 2),
        'vol_ratio': vol_ratio,
        'ma5': ma(closes, 5),
        'ma10': ma(closes, 10),
        'ma20': ma(closes, 20),
        'boll_up': boll_up, 'boll_mid': boll_mid, 'boll_low': boll_low,
        'macd_dif': dif, 'macd_dea': dea, 'macd_val': macd_val,
        'date': latest['date'],
    }

with open('/tmp/index_ta.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False)

print(json.dumps(results, ensure_ascii=False, indent=2))
EOF
```

Also extract watchlist TA:
```bash
python3 - <<'EOF'
import json, math

with open('/tmp/morning_latest.json') as f:
    d = json.load(f)

def parse_klines(klines):
    rows = []
    for k in klines:
        p = k.split(',')
        if len(p) >= 6:
            rows.append({'date':p[0],'open':float(p[1] or 0),'close':float(p[2] or 0),
                         'high':float(p[3] or 0),'low':float(p[4] or 0),'volume':float(p[5] or 0),
                         'amount':float(p[6] if len(p)>6 and p[6] else 0)})
    return rows

def ma(prices, n):
    return round(sum(prices[-n:])/n,2) if len(prices)>=n else None

results = []
for wl in d.get('watchlist_klines', []):
    klines = parse_klines(wl['klines'])
    if not klines: continue
    closes = [k['close'] for k in klines]
    vols = [k['volume'] for k in klines]
    latest = klines[-1]
    prev = klines[-2] if len(klines)>=2 else klines[-1]
    chg = round((latest['close']-prev['close'])/prev['close']*100,2) if prev['close'] else 0
    vol5avg = sum(vols[-6:-1])/5 if len(vols)>=6 else (vols[-1] or 1)
    vol_ratio = round(latest['volume']/vol5avg,2) if vol5avg else 1
    results.append({
        'name': wl['name'], 'close': latest['close'], 'chg_pct': chg,
        'ma5': ma(closes,5), 'ma10': ma(closes,10), 'ma20': ma(closes,20),
        'vol_ratio': vol_ratio, 'amount': round(latest['amount']/1e8,2),
        'high': latest['high'], 'low': latest['low'],
    })

with open('/tmp/watchlist_ta.json','w') as f:
    json.dump(results, f, ensure_ascii=False)
print(json.dumps(results, ensure_ascii=False))
EOF
```

## Step 3: Generate 8-module institutional-grade HTML report

Use the parsed data to write Python that generates the HTML and saves to `/tmp/morning_report.html`.

### Reference data (hardcoded, quarterly update):
- NVIDIA Q4 FY2026 数据中心营收: $62.3B（环比+21.7%，同比+93%）
- 四大云厂2026年CapEx合计: ~$725B（同比+77%）
- 800G光模块2026年预计出货: 4100万支
- 1.6T光模块2026年预计出货: 1100万支
- 中国智能算力规模: 1,037.3 EFLOPS（2025）

### HTML structure:

```python
import json, datetime

with open('/tmp/morning_latest.json') as f:
    raw = json.load(f)
with open('/tmp/index_ta.json') as f:
    idx = json.load(f)
with open('/tmp/watchlist_ta.json') as f:
    watchlist = json.load(f)

fetch_date = raw.get('fetch_date', datetime.date.today().isoformat())
report_date = fetch_date

def pct_color(v):
    try:
        fv = float(v)
        return '#dc2626' if fv > 0 else ('#16a34a' if fv < 0 else '#6b7280')
    except:
        return '#6b7280'

def fmt_pct(v):
    try:
        fv = float(v)
        return f"+{fv:.2f}%" if fv > 0 else f"{fv:.2f}%"
    except:
        return str(v)

def fmt_flow(v):
    """Format capital flow (unit: yuan) to 亿"""
    try:
        fv = float(v) / 1e8
        return f"+{fv:.2f}亿" if fv > 0 else f"{fv:.2f}亿"
    except:
        return "-"

# AI boards from raw data
ai_boards = raw.get('ai_boards', [])
board_stocks = raw.get('board_stocks', [])
capital_flow_top30 = raw.get('capital_flow_top30', [])
northbound = raw.get('northbound', [])
dragon_tiger = raw.get('dragon_tiger', [])
margin_trading = raw.get('margin_trading', [])
all_boards = raw.get('all_boards_by_change', [])
board_flows = raw.get('board_capital_flows', [])

# Sort AI boards
ai_boards_sorted_chg = sorted(ai_boards, key=lambda x: float(x.get('f3',0) or 0), reverse=True)
ai_boards_sorted_flow = sorted(ai_boards, key=lambda x: float(x.get('f62',0) or 0), reverse=True)

# Compute market breadth
total_boards = len(all_boards)
up_boards = sum(1 for b in all_boards if float(b.get('f3',0) or 0) > 0)
down_boards = sum(1 for b in all_boards if float(b.get('f3',0) or 0) < 0)

# Northbound summary
nb_net = 0
for nb in northbound[:2]:
    try:
        nb_net += float(nb.get('NET_BUY_AMT', 0) or 0)
    except:
        pass

# Index MA alignment analysis
def ma_alignment(d):
    if not d: return "数据不足"
    ma5, ma10, ma20 = d.get('ma5'), d.get('ma10'), d.get('ma20')
    close = d.get('close')
    if None in [ma5, ma10, ma20, close]: return "计算中"
    if close > ma5 > ma10 > ma20: return "多头排列 ▲"
    if close < ma5 < ma10 < ma20: return "空头排列 ▼"
    return "均线缠绕 ↔"

def boll_position(d):
    if not d: return "-"
    close = d.get('close')
    up = d.get('boll_up')
    mid = d.get('boll_mid')
    low = d.get('boll_low')
    if None in [close, up, mid, low]: return "-"
    if close > up: return "突破上轨"
    if close > mid: return "上轨内，强势"
    if close > low: return "中下轨间"
    return "跌破下轨"

def macd_signal(d):
    if not d: return "-"
    dif = d.get('macd_dif', 0) or 0
    val = d.get('macd_val', 0) or 0
    if dif > 0 and val > 0: return "金叉上行"
    if dif > 0 and val < 0: return "顶背离风险"
    if dif < 0 and val < 0: return "死叉下行"
    return "底背离观察"

# Build AI sub-sector summary
ai_sub = {}
for b in ai_boards:
    name = b.get('f14', '')
    chg = float(b.get('f3', 0) or 0)
    flow = float(b.get('f62', 0) or 0)
    ai_sub[name] = {'chg': chg, 'flow': flow, 'code': b.get('f12', '')}

# Top individual stocks from board_stocks
hot_stocks = []
for board in board_stocks:
    bn = board.get('board_name', '')
    for s in board.get('stocks', [])[:5]:
        chg = float(s.get('f3', 0) or 0)
        flow = float(s.get('f62', 0) or 0)
        amount = float(s.get('f6', 0) or 0) / 1e8
        vol_ratio = float(s.get('f8', 0) or 0) / 100  # f8 is换手率*100
        hot_stocks.append({
            'name': s.get('f14', ''), 'code': s.get('f12', ''),
            'chg': chg, 'flow': flow, 'amount': amount,
            'turnover': vol_ratio, 'board': bn,
            'close': float(s.get('f2', 0) or 0) / 100,
        })

hot_stocks_sorted = sorted(hot_stocks, key=lambda x: x['chg'], reverse=True)

# Shanghai index for summary
sh = idx.get('shanghai', {})
sh_chg = sh.get('chg_pct', 0)
sh_amount = sh.get('amount', 0)
sh_ma = ma_alignment(sh)

# Generate independent judgments based on data
def gen_macro_judgment():
    chg = sh_chg
    vol_ratio = sh.get('vol_ratio', 1)
    nb_bn = nb_net / 1e8
    if chg > 0.5 and vol_ratio > 1.1:
        strength = "放量上涨，多头主导"
    elif chg > 0 and vol_ratio < 0.9:
        strength = "缩量上涨，动能不足"
    elif chg < -0.5 and vol_ratio > 1.1:
        strength = "放量下跌，空头压力"
    elif chg < 0 and vol_ratio < 0.9:
        strength = "缩量调整，筑底信号"
    else:
        strength = "震荡整理，方向待定"
    nb_direction = "净流入" if nb_bn > 0 else "净流出"
    return f"市场呈{strength}。上证成交{sh_amount:.0f}亿元，量比{sh.get('vol_ratio',1):.2f}x。北向资金{nb_direction}{abs(nb_bn):.1f}亿元，外资态度{'积极' if nb_bn>0 else '审慎'}。均线{sh_ma}，市场β处于{'偏强' if chg>0 else '偏弱'}区间。NVIDIA数据中心营收$62.3B（同比+93%）提供产业链景气度支撑，AI科技风格中期逻辑未变。"

def gen_ai_sector_judgment():
    if not ai_boards_sorted_chg: return "AI板块数据获取中，请参考大盘走势。"
    top = ai_boards_sorted_chg[0]
    bottom = ai_boards_sorted_chg[-1] if len(ai_boards_sorted_chg) > 1 else top
    top_flow = ai_boards_sorted_flow[0] if ai_boards_sorted_flow else top
    avg_chg = sum(float(b.get('f3',0) or 0) for b in ai_boards) / len(ai_boards) if ai_boards else 0
    sh_chg_ref = sh_chg or 0
    excess = round(avg_chg - sh_chg_ref, 2)
    if excess > 0.5:
        rel = f"跑赢大盘{excess:.2f}pct，AI为主线题材"
    elif excess > 0:
        rel = f"小幅跑赢大盘{excess:.2f}pct，AI维持热度"
    elif excess > -0.5:
        rel = f"与大盘同步，AI非今日主线"
    else:
        rel = f"跑输大盘{abs(excess):.2f}pct，资金向外流"
    return f"AI板块平均涨幅{avg_chg:.2f}%，{rel}。领涨：{top.get('f14','?')}（{fmt_pct(top.get('f3',''))}，资金{fmt_flow(top.get('f62',''))}）；领跌：{bottom.get('f14','?')}（{fmt_pct(bottom.get('f3',''))}）。资金流入最大：{top_flow.get('f14','?')}（{fmt_flow(top_flow.get('f62',''))}）。产业链传导：美股算力端（NVIDIA）→ A股算力/服务器 → 光模块/光纤 → AI应用，当前关注{'上游算力'if top.get('f14','') in ['算力','半导体','AI芯片'] else '中游光模块/光纤' if '光' in top.get('f14','') else 'AI应用端'}。"

def gen_capital_judgment():
    top10_flow = sorted(capital_flow_top30, key=lambda x: float(x.get('f62',0) or 0), reverse=True)[:5]
    ai_names = ['旭创','新易盛','天孚','工业富联','曙光','寒武纪','海光','长飞','亨通','讯飞','算力','光模块','数据中心']
    ai_in_top = [s for s in top10_flow if any(kw in (s.get('f14','') or '') for kw in ai_names)]
    nb_bn = nb_net / 1e8
    dt_ai = [r for r in dragon_tiger if any(kw in (r.get('SECURITY_NAME','') or '') for kw in ai_names)]
    return f"主力资金净流入Top5个股中，AI相关占{len(ai_in_top)}席，机构配置AI方向{'明确' if ai_in_top else '尚不明确'}。北向资金{'净流入' if nb_bn>0 else '净流出'}{abs(nb_bn):.1f}亿元，外资{'增配' if nb_bn>0 else '减配'}A股。龙虎榜AI标的{len(dt_ai)}只，{'机构席位活跃，博弈激烈' if dt_ai else '游资主导，波动加剧'}。融资余额变化需关注是否有加速增长（杠杆过热预警）。"

def gen_stock_judgment():
    anomalies = [s for s in hot_stocks if s.get('vol_ratio', 0) > 2 or s.get('turnover', 0) > 0.15]
    absorb = [s for s in hot_stocks if s.get('chg', 0) < 0 and s.get('flow', 0) > 0]
    dump = [s for s in hot_stocks if s.get('chg', 0) > 1 and s.get('flow', 0) < 0]
    res = f"量价信号扫描：异动股（量比>2）{len(anomalies)}只，"
    if absorb:
        names = '、'.join(s['name'] for s in absorb[:3])
        res += f"吸筹信号（价跌资金流入）：{names}；"
    if dump:
        names = '、'.join(s['name'] for s in dump[:3])
        res += f"出货信号（价涨资金流出）：{names}，需警惕；"
    if not absorb and not dump:
        res += "量价背离不明显，"
    res += f"重点关注watchlist中量比>1.5且站上MA5的标的作为短线介入窗口。"
    return res

def gen_tech_judgment():
    sh = idx.get('shanghai', {})
    ma_align = ma_alignment(sh)
    boll = boll_position(sh)
    macd_s = macd_signal(sh)
    support = sh.get('ma20') or sh.get('ma10') or sh.get('close', 0)
    resist = sh.get('boll_up') or (sh.get('close', 0) * 1.02)
    return f"上证指数技术面：均线{ma_align}，布林带{boll}，MACD{macd_s}。关键支撑位{support}（MA20），压力位{resist:.1f}（布林上轨）。创业板/科创50科技属性强，若站稳MA5则短期延续强势；跌破MA20需降低仓位。"

def gen_valuation_judgment():
    return "AI板块整体PE（TTM）仍处历史较高分位（约70-80%分位）。光模块板块2026年盈利预期增速50-80%，PEG约1.0-1.5x，估值尚合理。AI芯片/寒武纪PE>200x，纯主题溢价，盈利兑现周期长。AI应用/科大讯飞PE约50x，盈利增速20-30%，估值偏贵。当前AI行情进入'盈利验证期'，关注季报超预期个股。建议回避纯概念、无盈利品种，聚焦业绩确定性高的光模块龙头。"

def gen_rotation_judgment():
    if len(ai_boards_sorted_flow) >= 2:
        top1 = ai_boards_sorted_flow[0].get('f14','')
        top2 = ai_boards_sorted_flow[1].get('f14','')
        return f"资金轮动：近日资金从{ai_boards_sorted_chg[-1].get('f14','') if ai_boards_sorted_chg else '?'}流出，向{top1}、{top2}集中。板块轮动路径：算力→光模块→光纤光缆→AI应用，当前动量集中在{top1}。若{top1}涨幅>5%且换手率>10%，可能进入过热区，关注向下一环节传导。"
    return "资金轮动方向：算力→光模块→AI应用，关注资金接力方向。"

macro_j = gen_macro_judgment()
ai_j = gen_ai_sector_judgment()
cap_j = gen_capital_judgment()
stock_j = gen_stock_judgment()
tech_j = gen_tech_judgment()
val_j = gen_valuation_judgment()
rot_j = gen_rotation_judgment()

# Strategy module
top_ai_boards = ai_boards_sorted_flow[:3] if ai_boards_sorted_flow else []
top_stocks_rec = sorted([s for s in hot_stocks if s.get('flow',0)>0 and s.get('chg',0)>0], 
                         key=lambda x: x['flow'], reverse=True)[:3]
risk_stock = sorted([s for s in hot_stocks if s.get('chg',0)>3], 
                    key=lambda x: x['chg'], reverse=True)[:2]

def gen_strategy():
    market_tone = "偏强震荡" if sh_chg > 0 else "偏弱震荡"
    if abs(sh_chg) > 1: market_tone = "强势上涨" if sh_chg > 0 else "明显调整"
    core_conflict = "AI板块高估值与盈利验证期之间的张力" if sh_chg > 0 else "宏观不确定性对科技板块的压制"
    
    short_opps = []
    for s in top_stocks_rec[:2]:
        short_opps.append(f"{s['name']}（{s['code']}）：主力净流入{fmt_flow(s['flow'])}，建议回调至MA5（约{s.get('close',0)*0.98:.2f}元附近）分批介入，目标+8-12%，止损MA10下方")
    
    mid_layouts = []
    for b in top_ai_boards[:2]:
        mid_layouts.append(f"{b.get('f14','?')}板块龙头：逢调配置，仓位5-8%")
    
    risks = []
    for s in risk_stock[:2]:
        risks.append(f"{s['name']}涨幅{s['chg']:.2f}%过大，出现放量滞涨立即减仓")
    
    vol_ratio = sh.get('vol_ratio', 1)
    position = "7成" if sh_chg > 0.5 and vol_ratio > 1 else "5成" if sh_chg > 0 else "3成"
    
    return market_tone, core_conflict, short_opps, mid_layouts, risks, position

market_tone, core_conflict, short_opps, mid_layouts, risks, position = gen_strategy()

# Build HTML
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股AI板块日报 {report_date}</title>
<style>
  body {{font-family:-apple-system,"PingFang SC",Arial,sans-serif;margin:0;padding:0;background:#f0f2f5;color:#1f2937}}
  .wrap {{max-width:800px;margin:0 auto;background:#fff}}
  .hdr {{background:linear-gradient(135deg,#1e3a5c,#2d5a8e);color:#fff;padding:28px 32px;text-align:center}}
  .hdr h1 {{margin:0;font-size:22px;font-weight:700;letter-spacing:2px}}
  .hdr p {{margin:8px 0 0;font-size:13px;opacity:.8}}
  .section {{padding:20px 24px;border-bottom:1px solid #e5e7eb}}
  .sec-title {{font-size:15px;font-weight:700;margin-bottom:14px;padding:6px 12px;border-radius:4px;color:#fff}}
  .m1 {{background:#3b82f6}} .m2 {{background:#8b5cf6}} .m3 {{background:#d97706}}
  .m4 {{background:#059669}} .m5 {{background:#dc2626}} .m6 {{background:#0891b2}}
  .m7 {{background:#6366f1}} .m8 {{background:#1e293b}}
  table {{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px}}
  th {{background:#f8fafc;padding:7px 8px;text-align:left;font-weight:600;border-bottom:2px solid #e2e8f0;color:#374151}}
  td {{padding:7px 8px;border-bottom:1px solid #f1f5f9}}
  tr:hover td {{background:#f8fafc}}
  .up {{color:#dc2626;font-weight:600}} .dn {{color:#16a34a;font-weight:600}} .flat {{color:#6b7280}}
  .judge {{background:#eff6ff;border-left:4px solid #3b82f6;padding:12px 16px;border-radius:0 6px 6px 0;margin:12px 0;font-size:13.5px;line-height:1.7;color:#1e3a5c}}
  .judge strong {{color:#1e3a5c}}
  .strat {{background:#1e293b;color:#f8fafc;padding:24px;margin:0}}
  .strat h3 {{color:#fbbf24;margin:0 0 4px;font-size:16px}}
  .strat .tone {{font-size:24px;font-weight:700;color:#fff;margin:8px 0 16px}}
  .strat .card {{background:#334155;border-radius:8px;padding:14px;margin:12px 0}}
  .strat .card h4 {{margin:0 0 8px;color:#94a3b8;font-size:12px;text-transform:uppercase;letter-spacing:1px}}
  .strat .card ul {{margin:0;padding:0 0 0 16px;color:#e2e8f0;font-size:13px;line-height:1.8}}
  .strat .risk {{background:#450a0a;border-left:4px solid #dc2626;padding:10px 14px;border-radius:0 6px 6px 0;margin:10px 0;font-size:13px;color:#fca5a5}}
  .pos {{background:#14532d;color:#86efac;padding:10px 14px;border-radius:6px;font-weight:700;font-size:14px;text-align:center;margin:10px 0}}
  .footer {{background:#f8fafc;padding:16px 24px;text-align:center;font-size:11px;color:#9ca3af}}
  .tag {{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600;margin-right:4px}}
  .tag-up {{background:#fee2e2;color:#dc2626}} .tag-dn {{background:#dcfce7;color:#16a34a}}
  .tag-hot {{background:#fef3c7;color:#d97706}}
</style>
</head>
<body>
<div class="wrap">

<div class="hdr">
  <h1>A股AI板块机构级日报</h1>
  <p>{report_date} · 开盘前参考 · 数据截至前收盘</p>
  <p style="margin-top:6px;font-size:12px;opacity:.7">分析框架：自上而下三层决策树 | 多维资金交叉验证</p>
</div>

<!-- 模块1：宏观环境 -->
<div class="section">
  <div class="sec-title m1">模块1：宏观环境与市场β</div>
  <table>
    <tr><th>指数</th><th>收盘</th><th>涨跌幅</th><th>成交额(亿)</th><th>量比</th><th>均线排列</th><th>布林位置</th><th>MACD</th></tr>
"""

for key, name in [('shanghai','上证指数'),('shenzhen','深证成指'),('chinext','创业板指'),('star50','科创50')]:
    d2 = idx.get(key, {})
    if not d2: continue
    chg = d2.get('chg_pct', 0)
    cc = 'up' if chg > 0 else ('dn' if chg < 0 else 'flat')
    html += f"""    <tr>
      <td><b>{name}</b></td>
      <td>{d2.get('close','-')}</td>
      <td class="{cc}">{fmt_pct(chg)}</td>
      <td>{d2.get('amount','-')}</td>
      <td>{d2.get('vol_ratio','-')}</td>
      <td>{ma_alignment(d2)}</td>
      <td>{boll_position(d2)}</td>
      <td>{macd_signal(d2)}</td>
    </tr>\n"""

html += f"""  </table>
  <div style="font-size:12px;color:#6b7280;margin-bottom:8px">
    全球信号：NVIDIA数据中心营收$62.3B（Q4 FY2026，同比+93%） | 四大云厂2026年CapEx ~$725B（+77%）| 北向资金今日净{'流入' if nb_net>0 else '流出'}{abs(nb_net/1e8):.1f}亿元
  </div>
  <div class="judge"><strong>【宏观判断】</strong> {macro_j}</div>
</div>

<!-- 模块2：AI板块景气度 -->
<div class="section">
  <div class="sec-title m2">模块2：AI板块景气度评估</div>
  <table>
    <tr><th>子板块</th><th>涨跌幅</th><th>主力净流入</th><th>vs大盘</th></tr>
"""

for b in ai_boards_sorted_chg[:15]:
    name = b.get('f14', '-')
    chg = float(b.get('f3', 0) or 0)
    flow = float(b.get('f62', 0) or 0)
    excess = round(chg - (sh_chg or 0), 2)
    cc = 'up' if chg > 0 else ('dn' if chg < 0 else 'flat')
    ecc = 'up' if excess > 0 else ('dn' if excess < 0 else 'flat')
    html += f"""    <tr>
      <td>{name}</td>
      <td class="{cc}">{fmt_pct(chg)}</td>
      <td class="{'up' if flow>0 else 'dn'}">{fmt_flow(flow)}</td>
      <td class="{ecc}">{'+' if excess>0 else ''}{excess:.2f}%</td>
    </tr>\n"""

html += f"""  </table>
  <div class="judge"><strong>【AI板块判断】</strong> {ai_j}</div>
</div>

<!-- 模块3：资金面 -->
<div class="section">
  <div class="sec-title m3">模块3：资金面六维透视</div>
  <table>
    <tr><th colspan="4">主力资金净流入 Top10（全市场）</th></tr>
    <tr><th>个股</th><th>代码</th><th>涨跌幅</th><th>主力净流入</th></tr>
"""

for s in capital_flow_top30[:10]:
    name = s.get('f14', '-')
    code = s.get('f12', '-')
    chg = float(s.get('f3', 0) or 0)
    flow = float(s.get('f62', 0) or 0)
    cc = 'up' if chg > 0 else ('dn' if chg < 0 else 'flat')
    html += f"""    <tr>
      <td>{name}</td><td style="color:#6b7280">{code}</td>
      <td class="{cc}">{fmt_pct(chg)}</td>
      <td class="{'up' if flow>0 else 'dn'}">{fmt_flow(flow)}</td>
    </tr>\n"""

# Northbound
html += """  </table>
  <table>
    <tr><th colspan="4">北向资金（沪深港通）</th></tr>
    <tr><th>类型</th><th>净买入额</th><th>买入额</th><th>卖出额</th></tr>
"""
for nb in northbound[:4]:
    nb_name = nb.get('MUTUAL_TYPE_NAME', '-')
    net = float(nb.get('NET_BUY_AMT', 0) or 0) / 1e8
    buy = float(nb.get('BUY_AMT', 0) or 0) / 1e8
    sell = float(nb.get('SELL_AMT', 0) or 0) / 1e8
    html += f"    <tr><td>{nb_name}</td><td class=\"{'up' if net>0 else 'dn'}\">{net:+.2f}亿</td><td>{buy:.2f}亿</td><td>{sell:.2f}亿</td></tr>\n"

# Margin top5
html += """  </table>
  <table>
    <tr><th colspan="3">融资余额 Top5（AI相关）</th></tr>
    <tr><th>个股</th><th>融资余额(亿)</th><th>净买入(亿)</th></tr>
"""
ai_kws = ['旭创','新易盛','天孚','富联','曙光','寒武','海光','长飞','亨通','讯飞','算力','光模块','数据中心','AI']
ai_margin = [m for m in margin_trading if any(kw in (m.get('SECURITY_NAME','') or '') for kw in ai_kws)]
for m in ai_margin[:5]:
    rzye = float(m.get('RZYE', 0) or 0) / 1e8
    rzmre = float(m.get('RZMRE', 0) or 0) / 1e8
    rzche = float(m.get('RZCHE', 0) or 0) / 1e8
    net_buy = rzmre - rzche
    html += f"    <tr><td>{m.get('SECURITY_NAME','-')}</td><td>{rzye:.2f}</td><td class=\"{'up' if net_buy>0 else 'dn'}\">{net_buy:+.2f}</td></tr>\n"

html += f"""  </table>
  <div class="judge"><strong>【资金面判断】</strong> {cap_j}</div>
</div>

<!-- 模块4：个股聚焦 -->
<div class="section">
  <div class="sec-title m4">模块4：个股深度聚焦</div>
  <table>
    <tr><th>个股</th><th>所属板块</th><th>涨跌幅</th><th>主力流入</th><th>换手率</th><th>成交额(亿)</th></tr>
"""

for s in hot_stocks_sorted[:15]:
    cc = 'up' if s['chg'] > 0 else ('dn' if s['chg'] < 0 else 'flat')
    fcc = 'up' if s['flow'] > 0 else 'dn'
    extra = ''
    if s.get('vol_ratio', 0) > 2: extra = '<span class="tag tag-hot">量比异动</span>'
    if s['chg'] > 0 and s['flow'] < 0: extra += '<span class="tag tag-dn">出货信号</span>'
    if s['chg'] < 0 and s['flow'] > 0: extra += '<span class="tag tag-up">吸筹信号</span>'
    html += f"""    <tr>
      <td><b>{s['name']}</b> {extra}</td>
      <td style="color:#6b7280;font-size:12px">{s['board']}</td>
      <td class="{cc}">{fmt_pct(s['chg'])}</td>
      <td class="{fcc}">{fmt_flow(s['flow'])}</td>
      <td>{s.get('turnover',0):.1f}%</td>
      <td>{s.get('amount',0):.2f}</td>
    </tr>\n"""

html += f"""  </table>
  <table>
    <tr><th colspan="5">Watchlist龙头股技术面</th></tr>
    <tr><th>个股</th><th>收盘</th><th>涨跌幅</th><th>量比</th><th>均线排列</th></tr>
"""
for w in watchlist:
    chg = w.get('chg_pct', 0)
    cc = 'up' if chg > 0 else ('dn' if chg < 0 else 'flat')
    closes = w.get('close', 0)
    ma5 = w.get('ma5')
    ma10 = w.get('ma10')
    ma20 = w.get('ma20')
    if None not in [ma5, ma10, ma20, closes]:
        if closes > ma5 > ma10 > ma20: align = "多头▲"
        elif closes < ma5 < ma10 < ma20: align = "空头▼"
        else: align = "缠绕↔"
    else:
        align = "-"
    html += f"    <tr><td><b>{w['name']}</b></td><td>{w.get('close','-')}</td><td class=\"{cc}\">{fmt_pct(chg)}</td><td>{w.get('vol_ratio','-')}</td><td>{align}</td></tr>\n"

html += f"""  </table>
  <div class="judge"><strong>【个股判断】</strong> {stock_j}</div>
</div>

<!-- 模块5：技术面 -->
<div class="section">
  <div class="sec-title m5">模块5：技术面全景</div>
  <table>
    <tr><th>指数</th><th>MA5</th><th>MA10</th><th>MA20</th><th>布林上轨</th><th>布林中轨</th><th>布林下轨</th><th>收盘位置</th></tr>
"""

for key, name in [('shanghai','上证'),('shenzhen','深证'),('chinext','创业板'),('star50','科创50')]:
    d2 = idx.get(key, {})
    if not d2: continue
    html += f"""    <tr>
      <td><b>{name}</b></td>
      <td>{d2.get('ma5','-')}</td><td>{d2.get('ma10','-')}</td><td>{d2.get('ma20','-')}</td>
      <td>{d2.get('boll_up','-')}</td><td>{d2.get('boll_mid','-')}</td><td>{d2.get('boll_low','-')}</td>
      <td>{boll_position(d2)}</td>
    </tr>\n"""

sh_d = idx.get('shanghai', {})
html += f"""  </table>
  <div class="judge"><strong>【技术面判断】</strong> {tech_j}
  上证关键价位：支撑{sh_d.get('ma20','-')}（MA20）/ {sh_d.get('boll_low','-')}（布林下轨），压力{sh_d.get('boll_up','-')}（布林上轨）/ {sh_d.get('ma5','-')}短期阻力。</div>
</div>

<!-- 模块6：估值 -->
<div class="section">
  <div class="sec-title m6">模块6：估值与盈利验证</div>
  <table>
    <tr><th>子板块</th><th>估值水位</th><th>2026年盈利预期</th><th>PEG评估</th><th>建议</th></tr>
    <tr><td>光模块（中际旭创/新易盛）</td><td>合理（历史50-60%分位）</td><td>+50-80%</td><td>~1.2x</td><td><span class="tag tag-up">超配</span></td></tr>
    <tr><td>AI芯片（寒武纪）</td><td>偏高（>90%分位）</td><td>扭亏+</td><td>>10x</td><td><span class="tag tag-dn">低配</span></td></tr>
    <tr><td>算力/服务器（工业富联）</td><td>合理（历史40-55%分位）</td><td>+20-30%</td><td>~0.8x</td><td><span class="tag tag-up">标配</span></td></tr>
    <tr><td>光纤光缆（长飞/亨通）</td><td>偏低（历史30%分位）</td><td>+15-25%</td><td>~0.7x</td><td><span class="tag tag-up">超配</span></td></tr>
    <tr><td>AI应用（科大讯飞）</td><td>偏高（历史75%分位）</td><td>+20-30%</td><td>~2.0x</td><td><span class="tag">标配</span></td></tr>
  </table>
  <div class="judge"><strong>【估值判断】</strong> {val_j}</div>
</div>

<!-- 模块7：轮动 -->
<div class="section">
  <div class="sec-title m7">模块7：板块轮动与趋势</div>
  <table>
    <tr><th>子板块（按资金流排序）</th><th>今日资金流</th><th>涨跌幅</th><th>状态</th></tr>
"""

for b in ai_boards_sorted_flow[:10]:
    name = b.get('f14', '-')
    flow = float(b.get('f62', 0) or 0)
    chg = float(b.get('f3', 0) or 0)
    status = "资金涌入" if flow > 5e8 else ("资金流入" if flow > 0 else ("资金流出" if flow < -5e8 else "资金撤退"))
    html += f"    <tr><td>{name}</td><td class=\"{'up' if flow>0 else 'dn'}\">{fmt_flow(flow)}</td><td class=\"{'up' if chg>0 else 'dn'}\">{fmt_pct(chg)}</td><td>{status}</td></tr>\n"

html += f"""  </table>
  <div class="judge"><strong>【轮动判断】</strong> {rot_j}</div>
</div>

<!-- 模块8：策略 -->
<div class="strat">
  <div class="sec-title m8" style="background:transparent;padding:0;margin-bottom:16px;font-size:18px;color:#fbbf24">🎯 模块8：今日策略</div>
  <div class="tone">市场定性：{market_tone}</div>
  <div style="color:#94a3b8;margin-bottom:16px;font-size:13px">核心矛盾：{core_conflict}</div>

  <div class="card">
    <h4>短线机会（1-3日）</h4>
    <ul>
"""
for opp in short_opps:
    html += f"      <li>{opp}</li>\n"
if not short_opps:
    html += "      <li>今日资金信号不明确，建议观望等待确认信号</li>\n"
html += f"""    </ul>
  </div>

  <div class="card">
    <h4>中线布局（1-3个月）</h4>
    <ul>
"""
for ml in mid_layouts:
    html += f"      <li>{ml}</li>\n"
html += f"""      <li>光纤光缆：估值安全边际高，受益光模块放量，逢调吸筹</li>
      <li>算力服务器：工业富联业绩稳健，AI服务器占比持续提升</li>
    </ul>
  </div>

  <div class="risk">
    ⚠ 风险警示：{"  ".join(risks) if risks else "高位获利盘较重，注意止盈纪律"}<br>
    若上证跌破MA20（{sh_d.get('ma20','-')}），科技仓位降至3成以下
  </div>

  <div class="pos">仓位建议：{position}仓 | 攻守比 6:4 | 止损触发点：个股-8%</div>
</div>

<div class="footer">
  数据来源：东方财富API · SEC EDGAR | 分析框架参照顶级券商研报方法论 | Claude 独立分析 | 仅供参考，不构成投资建议<br>
  生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CST
</div>

</div>
</body>
</html>"""

with open('/tmp/morning_report.html', 'w', encoding='utf-8') as f:
    f.write(html)
print(f"HTML written: {len(html)} chars")
EOF
```

## Step 4: Commit HTML to GitHub repo

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
  const filePath = '/stock_report/morning_latest.html';
  const content = fs.readFileSync('/tmp/morning_report.html');
  const b64 = content.toString('base64');
  
  // Get current SHA if exists
  const getRes = await ghRequest('GET', '/repos/' + repo + '/contents' + filePath);
  const sha = getRes.body && getRes.body.sha ? getRes.body.sha : undefined;
  
  const putBody = {
    message: 'report: AI morning report ' + new Date().toISOString().slice(0,10),
    content: b64,
    ...(sha ? {sha} : {})
  };
  
  const putRes = await ghRequest('PUT', '/repos/' + repo + '/contents' + filePath, putBody);
  console.log('Commit status:', putRes.status);
  console.log('SHA:', putRes.body && putRes.body.content ? putRes.body.content.sha : 'N/A');
}

main().catch(console.error);
"
```

## Step 5: Trigger email send workflow

```bash
curl -s -X POST \
  -H "Authorization: Bearer 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" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/ldwghm/AI-Mark-information/actions/workflows/send-report.yml/dispatches" \
  -d '{"ref":"main"}' && echo "Workflow triggered"
```

## Important notes
- If morning_latest.json fetch fails (file not found or too small), output a brief error HTML and commit it — do not fail silently.
- All monetary values from Eastmoney f62 field are in yuan (元), divide by 1e8 for 亿.
- Kline format: date,open,close,high,low,volume,amount (push2his eastmoney format).
- The report must have all 8 modules with 【独立判断】sections. Do not skip any module even if data is partial.
- Use actual computed numbers in all judgments — no placeholder text like "XX" or "待定".
