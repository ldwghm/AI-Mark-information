"""
report_renderer.py — Shared HTML rendering for morning & afternoon stock reports.

Takes structured JSON data (from fetch scripts) + CCR analysis JSON → produces
complete HTML email body. Charts via quickchart.io image URLs.
"""
import json
import re
from urllib.parse import quote

# ── Helpers ────────────────────────────────────────────────────────────────

def _num(v, default=0):
    """Safely convert to float. Handles None, '-', empty strings, etc."""
    if v is None or v == '' or v == '-':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def _clr(p):
    """Color for percentage: red=up (A-share convention), green=down."""
    p = _num(p)
    return '#dc2626' if p >= 0 else '#16a34a'

def _fp(p):
    p = _num(p)
    return f'{p:+.2f}%'

def _price_cell(v):
    """缺失的价格必须显示为「—」。

    不能走 _num()——它把 None 折成 0，会印出 0.00，读者无法与真实的
    0 元区分；更不能拿收盘价顶替，那会造出一根不存在的十字星。
    """
    if v is None or v == '' or v == '-':
        return '—'
    try:
        return f'{float(v):.2f}'
    except (ValueError, TypeError):
        return '—'

def _stale_index_names(market_data):
    """外围指数里日期落后于同市场其余行的那些（抓数端已逐行标 row_stale）。"""
    names = []
    markets = (((market_data or {}).get('global_markets') or {}).get('markets') or {})
    for block in markets.values():
        if not isinstance(block, dict):
            continue
        for row in (block.get('indices') or []):
            if isinstance(row, dict) and row.get('row_stale'):
                names.append(row.get('name') or row.get('code'))
    return names

def _has_intraday_range(rows):
    """整池是否至少有一行拿到了真实的日内高低。

    第二个条件是防伪：整池每一行都 high==low==现价，说明上游拿收盘价
    顶替了 OHLC（历史归档里就是这样），不是 51 只股票真的全天零振幅。
    单只涨停股确实可能零振幅，但那时整池也只会丢两列，代价可以接受。
    """
    rows = rows or []
    if not any((r.get('high') is not None) or (r.get('low') is not None)
               for r in rows):
        return False
    return any(_num(r.get('high')) != _num(r.get('low'))
               or _num(r.get('high')) != _num(r.get('current'))
               for r in rows)

def _fmt_amt(a):
    if a is None or a == '-': return '-'
    try:
        a = float(a)
    except (ValueError, TypeError):
        return '-'
    if abs(a) >= 1e8: return f'{a/1e8:.1f}亿'
    if abs(a) >= 1e4: return f'{a/1e4:.0f}万'
    return f'{a:.0f}'

def _fmt_flow(v):
    if v is None or v == '-': return '-'
    try:
        v = float(v)
    except (ValueError, TypeError):
        return '-'
    sign = '+' if v >= 0 else ''
    if abs(v) >= 1e8: return f'{sign}{v/1e8:.2f}亿'
    if abs(v) >= 1e4: return f'{sign}{v/1e4:.0f}万'
    return f'{sign}{v:.0f}'

def _score_stars(score):
    if score is None: return ''
    score = int(score)
    if score >= 80: return '★★★'
    if score >= 60: return '★★'
    return '★'

def _safe(v, default='-'):
    if v is None: return default
    return v

# ── Chart URL builder (quickchart.io) ──────────────────────────────────────

def _chart_url(config, width=600, height=300, bg='white'):
    """Build a quickchart.io URL from a chart config dict."""
    c = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
    return f"https://quickchart.io/chart?c={quote(c)}&w={width}&h={height}&bkg={bg}"

def _bar_chart_url(labels, values, title='', color_fn=None, width=600, height=280):
    """Build a horizontal bar chart URL. color_fn maps value → color."""
    if not labels or not values:
        return None
    colors = []
    for v in values:
        if color_fn:
            colors.append(color_fn(v))
        else:
            colors.append('#dc2626' if v >= 0 else '#16a34a')
    config = {
        'type': 'horizontalBar',
        'data': {
            'labels': labels[:15],
            'datasets': [{
                'data': [round(v, 2) for v in values[:15]],
                'backgroundColor': colors[:15],
            }]
        },
        'options': {
            'legend': {'display': False},
            'title': {'display': bool(title), 'text': title, 'fontSize': 14},
            'scales': {
                'xAxes': [{'ticks': {'callback': '(v)=>v+"%"'}}],
            },
            'plugins': {
                'datalabels': {
                    'anchor': 'end', 'align': 'end',
                    'formatter': '(v)=>v.toFixed(2)+"%"',
                    'font': {'size': 11}
                }
            }
        }
    }
    return _chart_url(config, width=width, height=max(180, len(labels) * 22))

# ── CSS (shared) ──────────────────────────────────────────────────────────

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f0f4f8; color: #1a202c; }
.container { max-width: 800px; margin: 0 auto; padding: 12px; }
.header { background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 50%, #1d4ed8 100%); color: white; padding: 20px 24px; border-radius: 12px 12px 0 0; }
.header h1 { font-size: 22px; font-weight: 700; }
.header .subtitle { font-size: 13px; opacity: 0.85; margin-top: 4px; }
.header .date-bar { font-size: 12px; opacity: 0.75; margin-top: 8px; display: flex; justify-content: space-between; }
.section { background: white; margin-top: 10px; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.section-header { padding: 12px 16px; font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.section-body { padding: 12px 16px; }
.sec-index { border-left: 4px solid #2563eb; }
.sec-index .section-header { background: linear-gradient(90deg, #eff6ff, #f8faff); color: #2563eb; }
.sec-capital { border-left: 4px solid #0891b2; }
.sec-capital .section-header { background: linear-gradient(90deg, #ecfeff, #f0feff); color: #0891b2; }
.sec-board { border-left: 4px solid #7c3aed; }
.sec-board .section-header { background: linear-gradient(90deg, #faf5ff, #fdfaff); color: #7c3aed; }
.sec-watchlist { border-left: 4px solid #d97706; }
.sec-watchlist .section-header { background: linear-gradient(90deg, #fffbeb, #fffdf5); color: #d97706; }
.sec-chart { border-left: 4px solid #059669; }
.sec-chart .section-header { background: linear-gradient(90deg, #f0fdf4, #f8fff9); color: #059669; }
.sec-analysis { border-left: 4px solid #dc2626; }
.sec-analysis .section-header { background: linear-gradient(90deg, #fff1f2, #fff8f8); color: #dc2626; }
.sec-score { border-left: 4px solid #ea580c; }
.sec-score .section-header { background: linear-gradient(90deg, #fff7ed, #fffbf5); color: #ea580c; }
.sec-predict { border-left: 4px solid #7c3aed; }
.sec-predict .section-header { background: linear-gradient(90deg, #faf5ff, #fdfaff); color: #7c3aed; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { background: #f8faff; padding: 8px 10px; text-align: left; font-weight: 600; color: #374151; border-bottom: 2px solid #e5e7eb; }
td { padding: 7px 10px; border-bottom: 1px solid #f3f4f6; }
tr:last-child td { border-bottom: none; }
.pos { color: #dc2626; font-weight: 600; }
.neg { color: #16a34a; font-weight: 600; }
.idx-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 8px; }
.idx-card { background: #f8faff; border-radius: 8px; padding: 12px; text-align: center; border: 1px solid #e5e7eb; }
.idx-card .idx-name { font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.idx-card .idx-val { font-size: 20px; font-weight: 700; }
.idx-card .idx-chg { font-size: 13px; margin-top: 3px; }
.board-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.board-item { background: #f9fafb; border-radius: 6px; padding: 10px; }
.board-item .board-name { font-size: 12px; font-weight: 600; color: #374151; }
.board-item .board-chg { font-size: 15px; font-weight: 700; margin: 3px 0; }
.board-item .board-meta { font-size: 11px; color: #9ca3af; }
.insight-box { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px; margin: 8px 0; }
.insight-box li { margin: 5px 0; font-size: 13px; line-height: 1.6; }
.risk-item { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 8px 12px; margin: 6px 0; font-size: 12px; color: #9a3412; }
.advice-box { background: linear-gradient(135deg, #1e3a8a, #1d4ed8); color: white; padding: 16px; border-radius: 10px; margin: 8px 0; }
.advice-box .style-label { font-size: 22px; font-weight: 800; }
.advice-box .pos-range { font-size: 14px; opacity: 0.9; margin-top: 4px; }
.advice-box .rationale { font-size: 13px; opacity: 0.85; margin-top: 8px; line-height: 1.6; }
.footer { background: #f1f5f9; border-top: 1px solid #e2e8f0; padding: 12px 16px; font-size: 11px; color: #94a3b8; text-align: center; margin-top: 10px; border-radius: 0 0 8px 8px; }
.chart-img { max-width: 100%; border-radius: 6px; margin: 8px 0; }
.predict-box { border: 2px solid; border-radius: 10px; padding: 18px; margin: 8px 0; background: #fafafa; }
.predict-label { font-size: 22px; font-weight: bold; }
.sec-sectors { border-left: 4px solid #0891b2; }
.sec-sectors .section-header { background: linear-gradient(90deg, #ecfeff, #f0feff); color: #0891b2; }
.sector-title-row td { background: #f0f9ff; font-weight: 700; color: #0891b2; padding: 5px 10px; font-size: 12px; }

/* 研报分节。结论段用最重的蓝，论据段沿用既有配色，附录压到灰。 */
.sec-verdict { border-left: 4px solid #1e3a8a; }
.sec-verdict .section-header { background: linear-gradient(90deg, #eef2ff, #f8faff); color: #1e3a8a; }
.sec-scenario { border-left: 4px solid #b45309; }
.sec-scenario .section-header { background: linear-gradient(90deg, #fffbeb, #fffdf5); color: #b45309; }
.sec-review { border-left: 4px solid #ca8a04; }
.sec-review .section-header { background: linear-gradient(90deg, #fefce8, #fffef5); color: #854d0e; }
.sec-anomaly { border-left: 4px solid #0d9488; }
.sec-anomaly .section-header { background: linear-gradient(90deg, #f0fdfa, #f7fffe); color: #0d9488; }
.sec-thesis { border-left: 4px solid #4f46e5; }
.sec-thesis .section-header { background: linear-gradient(90deg, #eef2ff, #f8faff); color: #4f46e5; }
.sec-risk { border-left: 4px solid #ea580c; }
.sec-risk .section-header { background: linear-gradient(90deg, #fff7ed, #fffbf5); color: #ea580c; }
.sec-evidence { border-left: 4px solid #94a3b8; }
.sec-evidence .section-header { background: linear-gradient(90deg, #f8fafc, #fcfdfe); color: #64748b; }

/* ── 可读性层 ─────────────────────────────────────────────────
   分析正文常年一万六千字以上，平铺会让"当天最重要的结论"和"第 9 条
   数据口径声明"拥有同样的视觉权重。以下三组样式只做一件事：把已经
   写在文本里的结构（【小标题】、①②③、数据口径 vs 市场风险）翻译成
   看得见的层级。 */
.tldr { background: #fff; border: 2px solid #1e3a8a; border-radius: 10px; padding: 16px 18px; margin-top: 10px; }
.tldr .tldr-tag { display: inline-block; font-size: 11px; font-weight: 700; color: #1e3a8a; background: #eff6ff; padding: 2px 8px; border-radius: 4px; letter-spacing: .5px; }
.tldr .tldr-line { font-size: 16px; font-weight: 700; line-height: 1.6; margin-top: 8px; color: #111827; }
.tldr .tldr-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.tldr .tldr-cell { background: #f8faff; border-radius: 6px; padding: 8px 10px; }
.tldr .tldr-k { font-size: 11px; color: #6b7280; }
.tldr .tldr-v { font-size: 14px; font-weight: 700; color: #1f2937; margin-top: 2px; }
.badges { margin-top: 10px; }
.badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 999px; margin: 2px 4px 2px 0; }
.badge-ok { background: #dcfce7; color: #15803d; }
.badge-warn { background: #fef3c7; color: #b45309; }
.badge-bad { background: #fee2e2; color: #b91c1c; }
.badge-mute { background: #f1f5f9; color: #64748b; }

.subhead { font-size: 13px; font-weight: 700; color: #1e3a8a; margin: 12px 0 4px; padding-left: 8px; border-left: 3px solid #93c5fd; }
.para { font-size: 13px; line-height: 1.85; margin: 4px 0; color: #374151; }
.insight-num { display: inline-block; min-width: 18px; height: 18px; line-height: 18px; text-align: center; background: #1e3a8a; color: #fff; font-size: 11px; font-weight: 700; border-radius: 50%; margin-right: 6px; }

.hl-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; margin: 8px 0; background: #fff; }
.hl-head { font-size: 14px; font-weight: 700; color: #111827; }
.hl-code { font-size: 12px; color: #9ca3af; font-weight: 400; margin-left: 4px; }
.hl-asof { font-size: 11px; color: #b45309; background: #fffbeb; border: 1px solid #fde68a; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }
.hl-body { font-size: 12.5px; line-height: 1.75; color: #4b5563; margin-top: 6px; }

.caveat-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.caveat-title { font-size: 12px; font-weight: 700; color: #64748b; }
.caveat-item { font-size: 11.5px; line-height: 1.7; color: #64748b; margin-top: 6px; padding-left: 10px; border-left: 2px solid #cbd5e1; }
.caveat-item b { color: #475569; }
"""

# ── 文本结构化 ────────────────────────────────────────────────────────────
# 分析层已经把结构写进了文本：【小标题】分段、①②③列点。以前这些都当纯文字
# 渲染，读者要自己在一堵墙里找层级。下面把它们提成真的 HTML 结构。

_LEAD_MARK = re.compile(r'^【([^】]{1,40})】')
# 数据/方法类口径 vs 真正的市场风险。分类依据就是分析层自己写的【】标题——
# 它已经准确地把两类分开了，不需要再猜。
_CAVEAT_WORDS = ('数据', '口径', '缺失', '快照', '基准', '核验', '闭环', '重复计算',
                 '状态', '证据不足', '不可得', 'unavailable', '时点', '替换', '分层',
                 # 「X 为 A 而非 B」「无今日…」这类纯粹描述取数口径的说法
                 '观察池', '无今日', '而非', '未采集', '非当日', '未能',
                 # 早报侧的说法（早报不写【】小标题，更依赖这些词）
                 '非实时', '来源冲突', '归档', '有效时点')
# 「缺口」「回补」都不能进这张表：归档缺口是数据问题，但跳空缺口、缺口回补
# 是真正的市场风险。「个股行情为收盘回补，非实时」靠'非实时'已能命中。


_MD_BOLD = re.compile(r'\*\*(.+?)\*\*', re.S)


def _md_inline(text):
    """分析层习惯在 JSON 字符串里写 markdown 强调，邮件里会原样露出 `**`。

    实测："①**今日盘中层（北京时间14:23:20抓取）**——AI板块行情…"
    这些星号是模型在标注重点，本来就该是加粗，翻译过来即可。
    """
    return _MD_BOLD.sub(r'<b>\1</b>', str(text or ''))


def _rich_text(text, para_cls='para'):
    """把 `【小标题】` 提成小标题，按换行分段。纯展示，不改动任何文字。"""
    if not text:
        return ''
    out = []
    for chunk in str(text).split('\n'):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _LEAD_MARK.match(chunk)
        if m:
            out.append(f'<div class="subhead">{m.group(1)}</div>')
            chunk = chunk[m.end():].strip()
            if not chunk:
                continue
        out.append(f'<p class="{para_cls}">{_md_inline(chunk)}</p>')
    return ''.join(out)


def _split_lead(text):
    """拆出开头的 `【标题】`，返回 (标题 or None, 余文)。"""
    text = str(text or '').strip()
    m = _LEAD_MARK.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():].strip()


def _is_caveat(title, body):
    """这条 risk_warning 是数据口径说明，还是真正的市场风险？"""
    probe = title or body[:30]
    return any(w in probe for w in _CAVEAT_WORDS)


# ── Section builders ──────────────────────────────────────────────────────

def _section(cls, icon, title, body_html):
    return f"""
<div class="section {cls}">
  <div class="section-header">{icon} {title}</div>
  <div class="section-body">{body_html}</div>
</div>"""

def _render_index_cards(indices_data, index_names=None):
    """Render index cards from indices dict (shanghai/shenzhen/chinext/star50)."""
    if not index_names:
        index_names = {
            'shanghai': '上证指数', 'shenzhen': '深证成指',
            'chinext': '创业板指', 'star50': '科创50',
            'sh000001': '上证指数', 'sz399001': '深证成指',
            'sz399006': '创业板指', 'sh000688': '科创50',
        }
    cards = ''
    for key, data in indices_data.items():
        name = index_names.get(key, key)
        if isinstance(data, dict):
            price = _num(data.get('price') or data.get('current') or data.get('close'))
            chg_raw = data.get('chg', data.get('change_pct', data.get('pct')))
            if chg_raw is None:
                prev = _num(data.get('yesterday_close'))
                chg = (price - prev) / prev * 100 if prev else 0
            else:
                chg = _num(chg_raw)
        else:
            continue
        color = _clr(chg)
        arrow = '↑' if chg >= 0 else '↓'
        cards += f"""
      <div class="idx-card">
        <div class="idx-name">{name}</div>
        <div class="idx-val" style="color:{color}">{price:.2f}</div>
        <div class="idx-chg" style="color:{color}">{arrow}{_fp(chg)}</div>
      </div>"""
    return f'<div class="idx-grid">{cards}</div>'

def _render_index_table(indices_data, index_names=None):
    """Full index table with open/high/low/volume."""
    if not index_names:
        index_names = {
            'shanghai': '上证指数', 'shenzhen': '深证成指',
            'chinext': '创业板指', 'star50': '科创50',
        }
    rows = ''
    for key, data in indices_data.items():
        name = index_names.get(key, key)
        price = _num(data.get('price') or data.get('close'))
        chg = _num(data.get('chg') or data.get('change_pct'))
        amt = data.get('amount') or data.get('amt')
        color = _clr(chg)
        rows += f"""<tr>
        <td><b>{name}</b></td>
        <td style="font-weight:bold">{price:.2f}</td>
        <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
        <td>{_fmt_amt(amt)}</td>
      </tr>"""
    return f"""<table>
    <tr><th>指数</th><th>最新价</th><th>涨跌幅</th><th>成交额</th></tr>
    {rows}</table>"""

def _render_ai_boards(boards, board_stocks=None):
    """Render AI sector boards as grid cards."""
    if not boards:
        return '<p style="color:#9ca3af">AI板块数据不可用</p>'
    items = ''
    stock_map = {}
    if board_stocks:
        for bs in board_stocks:
            stock_map[bs.get('bk_code', '')] = bs.get('stocks', [])

    for b in boards[:8]:
        name = b.get('f14', '-')
        chg = _num(b.get('f3'))
        amt = b.get('f6')
        flow = b.get('f62', None)
        bk_code = b.get('f12', '')
        color = _clr(chg)

        leaders = ''
        stocks = stock_map.get(bk_code, [])
        if stocks:
            top3 = stocks[:3]
            parts = []
            for s in top3:
                sn = s.get('f14', '?')
                sc = _num(s.get('f3'))
                parts.append(f'{sn}({_fp(sc)})')
            leaders = f'<div class="board-meta">龙头: {" | ".join(parts)}</div>'

        flow_html = ''
        if flow is not None:
            flow_html = f'<div class="board-meta">主力净流入: {_fmt_flow(flow)}</div>'

        items += f"""
      <div class="board-item">
        <div class="board-name">{name}</div>
        <div class="board-chg" style="color:{color}">{_fp(chg)}</div>
        <div class="board-meta">成交额: {_fmt_amt(amt)}</div>
        {flow_html}
        {leaders}
      </div>"""
    return f'<div class="board-grid">{items}</div>'

def _render_capital_flow(flows):
    """Render top capital flow stocks table."""
    if not flows:
        return '<p style="color:#9ca3af">资金流向数据不可用</p>'
    rows = ''
    for i, s in enumerate(flows[:10]):
        name = s.get('f14', '-')
        code = s.get('f12', '-')
        chg = _num(s.get('f3'))
        flow = _num(s.get('f62'))
        amt = s.get('f6')
        color = _clr(chg)
        fc = '#dc2626' if flow >= 0 else '#16a34a'
        rows += f"""<tr>
        <td>{i+1}</td>
        <td><b>{name}</b></td>
        <td style="color:#6b7280">{code}</td>
        <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
        <td style="color:{fc};font-weight:bold">{_fmt_flow(flow)}</td>
        <td>{_fmt_amt(amt)}</td>
      </tr>"""
    return f"""<table>
    <tr><th>#</th><th>股票</th><th>代码</th><th>涨跌幅</th><th>主力净流入</th><th>成交额</th></tr>
    {rows}</table>"""

# Fields that carry an actual quote/indicator value. An entry holding only
# name/code/sector is a placeholder produced by a failed backfill — rendering it
# yields a row of 0.00 / +0.00% / '-', which reads as real data. Treat as absent.
_TECH_VALUE_FIELDS = ('close', 'price', 'chg_pct', 'score',
                      'ma_trend', 'macd_status', 'rsi_12', 'volume_ratio')

def _has_tech_data(s):
    return isinstance(s, dict) and any(s.get(f) is not None for f in _TECH_VALUE_FIELDS)

def _filter_tech(technicals):
    """Drop placeholder entries so empty sections can be hidden instead of zero-filled."""
    return [s for s in (technicals or []) if _has_tech_data(s)]

_INDEX_VALUE_FIELDS = ('price', 'current', 'close', 'chg', 'change_pct', 'pct')

def _has_index_data(indices_data):
    """_render_index_cards always returns a wrapper div, and entries may carry only
    name/secid/klines (which the cards cannot read), so test for a quote value."""
    if not isinstance(indices_data, dict):
        return False
    return any(isinstance(v, dict) and any(v.get(f) is not None for f in _INDEX_VALUE_FIELDS)
               for v in indices_data.values())

def _quote_date_label(market_data):
    """Return the quote date when it differs from the expected trading day, else None."""
    fresh = market_data.get('data_freshness') or {}
    quote_date = fresh.get('quote_date_mode')
    expected = market_data.get('expected_data_date')
    return quote_date if (quote_date and expected and quote_date != expected) else None

def _render_watchlist_technicals(technicals, group_by_sector=False, price_date=None):
    """Render watchlist stocks with technical indicators and scores."""
    technicals = _filter_tech(technicals)
    if not technicals:
        return ''
    rows = ''
    if group_by_sector and any(s.get('sector') for s in technicals):
        # Group by sector, preserving sort-by-chg within each group
        from collections import OrderedDict
        groups = OrderedDict()
        for s in sorted(technicals, key=lambda x: _num(x.get('chg_pct')), reverse=True):
            sec = s.get('sector', '其他')
            groups.setdefault(sec, []).append(s)
        ordered = []
        for sec, items in groups.items():
            ordered.append(('__sector__', sec))
            ordered.extend(items)
        iter_list = ordered
    else:
        # Sort by score descending (original behaviour)
        iter_list = sorted(technicals, key=lambda x: _num(x.get('score')), reverse=True)
    price_hdr = f'现价<br/><span style="font-weight:normal;font-size:11px;color:#b45309">{price_date}</span>' if price_date else '现价'
    header = f'<tr><th>股票</th><th>代码</th><th>{price_hdr}</th><th>涨跌幅</th><th>评分</th><th>MA趋势</th><th>MACD</th><th>RSI</th><th>量比</th></tr>'
    for s in iter_list:
        if isinstance(s, tuple) and s[0] == '__sector__':
            rows += f'<tr class="sector-title-row"><td colspan="9">📂 {s[1]}</td></tr>'
            continue
        name = s.get('name', '-')
        code = s.get('code', '-')
        chg = _num(s.get('chg_pct'))
        price = _num(s.get('close') if s.get('close') is not None else s.get('price'))
        score = s.get('score')
        stars = _score_stars(score)
        ma_trend = _safe(s.get('ma_trend'))
        macd_st = _safe(s.get('macd_status'))
        rsi = s.get('rsi_12')
        vr = s.get('volume_ratio')
        vl = _safe(s.get('volume_label'))
        color = _clr(chg)

        score_html = f'<span style="color:#ea580c;font-weight:bold">{score}</span> {stars}' if score is not None else '-'
        rsi_html = f'{rsi:.0f}' if rsi else '-'
        vr_html = f'{vr:.1f}x' if vr else '-'

        rows += f"""<tr>
        <td><b>{name}</b></td>
        <td style="color:#6b7280;font-family:monospace">{code}</td>
        <td style="font-weight:bold">{price:.2f}</td>
        <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
        <td>{score_html}</td>
        <td>{ma_trend}</td>
        <td>{macd_st}</td>
        <td>{rsi_html}</td>
        <td>{vr_html} {vl}</td>
      </tr>"""
    return f"""<table>
    {header}
    {rows}</table>"""

def _render_score_ranking(technicals):
    """Render score ranking chart + table for top scored stocks."""
    if not technicals:
        return ''
    scored = [s for s in technicals if s.get('score') is not None]
    scored.sort(key=lambda x: x['score'], reverse=True)
    if not scored:
        return ''
    top = scored[:10]
    labels = [s.get('name', '?') for s in top]
    values = [s['score'] for s in top]

    def score_color(v):
        if v >= 80: return '#dc2626'
        if v >= 60: return '#ea580c'
        return '#9ca3af'

    config = {
        'type': 'horizontalBar',
        'data': {
            'labels': labels,
            'datasets': [{
                'data': values,
                'backgroundColor': [score_color(v) for v in values],
            }]
        },
        'options': {
            'legend': {'display': False},
            'title': {'display': True, 'text': 'AI龙头综合评分 TOP10', 'fontSize': 14},
            'scales': {
                'xAxes': [{'ticks': {'min': 0, 'max': 100}}],
            },
            'plugins': {
                'datalabels': {
                    'anchor': 'end', 'align': 'end',
                    'font': {'size': 11, 'weight': 'bold'}
                }
            }
        }
    }
    url = _chart_url(config, width=600, height=max(200, len(top) * 28))
    return f'<img src="{url}" class="chart-img" alt="综合评分排行" />'

def _render_change_chart(technicals):
    """Bar chart of stock price changes."""
    if not technicals:
        return ''
    sorted_t = sorted(technicals, key=lambda x: _num(x.get('chg_pct')), reverse=True)
    labels = [s.get('name', '?') for s in sorted_t[:15]]
    values = [round(s.get('chg_pct', 0) or 0, 2) for s in sorted_t[:15]]
    if not labels:
        return ''
    config = {
        'type': 'horizontalBar',
        'data': {
            'labels': labels,
            'datasets': [{
                'data': values,
                'backgroundColor': ['#dc2626' if v >= 0 else '#16a34a' for v in values],
            }]
        },
        'options': {
            'legend': {'display': False},
            'title': {'display': True, 'text': '个股涨跌幅一览', 'fontSize': 14},
            'plugins': {
                'datalabels': {
                    'anchor': 'end', 'align': 'end',
                    'formatter': '(v)=>v.toFixed(2)+"%"',
                    'font': {'size': 11}
                }
            }
        }
    }
    url = _chart_url(config, width=600, height=max(200, len(labels) * 24))
    return f'<img src="{url}" class="chart-img" alt="个股涨跌幅" />'

def _render_review(analysis):
    """上期预测 vs 实际。"""
    review = (analysis or {}).get('review', '')
    if not review:
        return ''
    return ('<div style="margin:12px 0;padding:10px 14px;background:#fefce8;'
            'border-left:3px solid #ca8a04;border-radius:4px">'
            '<div style="font-size:13px;font-weight:700;color:#854d0e">早报复盘</div>'
            f'{_rich_text(review)}</div>')


def _render_insights(analysis):
    """核心观点 —— 编号，让"十条要点"变成可数、可跳读的清单。"""
    insights = (analysis or {}).get('key_insights', [])
    if not insights:
        return ''
    items = ''.join(
        f'<div style="margin:8px 0;font-size:13px;line-height:1.75">'
        f'<span class="insight-num">{n}</span>{_md_inline(text)}</div>'
        for n, text in enumerate(insights, 1))
    return ('<div class="insight-box"><b>核心观点</b>'
            f'<div style="margin-top:6px">{items}</div></div>')


def _render_highlights(analysis):
    """个股点评卡片。每条 comment 常有 400 字，挤在 <li> 里读不动；
    开头的【价格字段口径…】提成徽章，读者一眼知道这个价是哪天的。"""
    highlights = (analysis or {}).get('stock_highlights', [])
    if not highlights:
        return ''
    cards = ''
    for h in highlights:
        lead, body = _split_lead(h.get('comment', ''))
        asof = h.get('price_as_of') or ''
        badge = ''
        if h.get('price_is_fallback') and asof:
            badge = f'<span class="hl-asof">价格截至 {str(asof)[:10]}</span>'
        elif lead:
            badge = f'<span class="hl-asof">{lead[:18]}</span>'
        cards += (
            '<div class="hl-card">'
            f'<div class="hl-head">{h.get("name", "")}'
            f'<span class="hl-code">{h.get("code", "")}</span>{badge}</div>'
            f'<div class="hl-body">{_md_inline(body or h.get("comment", ""))}</div>'
            '</div>')
    return f'<div style="margin-top:12px"><b>个股点评</b>{cards}</div>'


def _render_analysis(analysis):
    """Render CCR analysis JSON into HTML sections（午报沿用的整块布局）。"""
    if not analysis:
        return ''
    summary = analysis.get('market_summary', '')
    parts = [
        _rich_text(summary) if summary else '',
        _render_review(analysis),
        _render_insights(analysis),
        _render_sector_rotation_block(analysis),
        _render_highlights(analysis),
        _render_sector_analysis_block(analysis),
    ]
    return '\n'.join(p for p in parts if p)


def _render_sector_rotation_block(analysis):
    rotation_html = _render_sector_rotation(analysis)
    return (f'<div style="margin-top:10px"><b>板块轮动判断：</b>{rotation_html}</div>'
            if rotation_html else '')


def _render_sector_analysis_block(analysis):
    sector = (analysis or {}).get('sector_analysis', '')
    return (f'<div style="margin-top:12px"><b>板块解读</b>{_rich_text(sector)}</div>'
            if sector else '')


def _render_sector_read(analysis):
    """板块轮动判断 + 板块解读（早报把两者收进「板块」一节）。"""
    return _render_sector_rotation_block(analysis) + _render_sector_analysis_block(analysis)


_RISK_WORDS = ('事件', '政策', '风险', '波动', '传闻', '不确定', '监管')
_POS_RANGE = re.compile(r'(\d{1,3}\s*[-–~至]\s*\d{1,3}\s*%)')
_POS_SINGLE = re.compile(r'(\d{1,3}\s*%)')


def _position_range(position):
    """从一段仓位说明里抽出数字区间。

    `trading_advice.position` 实测常是 300 字的整段论述（"总仓位建议35-50%（较
    今日早报的40-55%下调…"），截前 40 字只会得到一句半截话。摘要卡要的是
    "35-50%" 这四个字符，理由留在下面的正文里。
    """
    text = str(position or '').strip()
    if not text:
        return ''
    m = _POS_RANGE.search(text) or _POS_SINGLE.search(text)
    if m:
        return m.group(1).replace(' ', '')
    return text if len(text) <= 24 else text[:24] + '…'


def _first_sentence(text, limit=90):
    """取第一句作摘要；带【标题】的先剥掉标题。"""
    _lead, body = _split_lead(text)
    body = (body or '').replace('\n', ' ').strip()
    for sep in ('。', '；', '. '):
        if sep in body[:limit + 30]:
            return body.split(sep)[0] + sep
    return body[:limit] + ('…' if len(body) > limit else '')


def _data_badges(analysis, market_data):
    """数据状态徽章：把 verify/data_quality 里的判定摆到最显眼处。

    这些信息以前只存在于 JSON 和风险提示的第 1、2 条里，读者要读到一千字
    之后才知道"今天的个股价格其实是昨天的"。
    """
    dq = (market_data or {}).get('data_quality') or {}
    verify = (analysis or {}).get('verify') or {}
    prov = dq.get('provenance') or {}
    cc = dq.get('crosscheck') or {}
    out = []

    total = prov.get('fallback_rows')
    by_src = prov.get('by_source') or {}
    live = sum(v for k, v in by_src.items() if k in ('sina', 'tencent', 'yfinance'))
    if isinstance(total, int) and (live or total):
        n = live + total if live else total
        if live == 0:
            out.append(f'<span class="badge badge-bad">个股价格 0/{n} 为当日实时</span>')
        elif live < n:
            out.append(f'<span class="badge badge-warn">当日实时 {live}/{n}</span>')
        else:
            out.append(f'<span class="badge badge-ok">当日实时 {live}/{n}</span>')

    behind = prov.get('seconds_behind_market')
    if isinstance(behind, (int, float)) and behind > 900:
        hours = behind / 3600
        label = f'{hours:.1f} 小时' if hours >= 1 else f'{behind / 60:.0f} 分钟'
        out.append(f'<span class="badge badge-warn">数据落后市场 {label}</span>')

    if cc.get('status') == 'unchecked' or cc.get('checked_pairs') == 0:
        out.append('<span class="badge badge-mute">未做双源交叉验证</span>')
    elif cc.get('checked_conflicts'):
        out.append(f'<span class="badge badge-warn">双源冲突 {cc["checked_conflicts"]} 处</span>')
    elif cc.get('checked_pairs'):
        out.append(f'<span class="badge badge-ok">双源已核对 {cc["checked_pairs"]} 只</span>')

    if not (market_data or {}).get('realtime_indices') and \
            not (market_data or {}).get('indices'):
        out.append('<span class="badge badge-bad">大盘指数本期缺失</span>')

    # 抓数端逐行标了 row_stale，此前只进日志。落后一个交易日的外围指数
    # 与当日个股混在一张快照里，最容易被当成今日数据引用。
    stale_idx = _stale_index_names(market_data)
    if stale_idx:
        out.append(f'<span class="badge badge-warn">'
                   f'{"、".join(stale_idx)} 滞后 1 个交易日</span>')

    if verify.get('blocked'):
        out.append('<span class="badge badge-bad">未通过发送门槛</span>')
    elif verify.get('hard_fail'):
        out.append('<span class="badge badge-bad">存在硬性核对失败</span>')

    return f'<div class="badges">{"".join(out)}</div>' if out else ''


def _render_tldr(analysis, market_data):
    """顶部结论卡：先给结论、仓位、最大风险和数据状态，再让人决定要不要往下读。"""
    if not analysis:
        return ''
    pred = analysis.get('prediction') or {}
    advice = analysis.get('trading_advice') or {}

    line = pred.get('label') or _first_sentence(analysis.get('market_summary', ''))
    if not line:
        return ''

    conf = pred.get('confidence')
    position_short = _position_range(advice.get('position', ''))

    # 最重要的一条风险：先找标题里明写"事件/政策/风险"的，再退回第一条非口径类。
    # 不能简单取第一条——分析层习惯把数据口径说明排在最前面。
    top_risk = ''
    fallback_risk = ''
    for w in analysis.get('risk_warnings') or []:
        title, body = _split_lead(w)
        text = f'{title}：{_first_sentence(body, 70)}' if title else _first_sentence(body, 70)
        if title and any(k in title for k in _RISK_WORDS):
            top_risk = text
            break
        if not fallback_risk and not _is_caveat(title, body):
            fallback_risk = text
    top_risk = top_risk or fallback_risk

    cells = ''
    if position_short and position_short != '-':
        cells += ('<div class="tldr-cell"><div class="tldr-k">建议仓位</div>'
                  f'<div class="tldr-v">{position_short}</div></div>')
    if isinstance(conf, (int, float)):
        cells += ('<div class="tldr-cell"><div class="tldr-k">判断置信度</div>'
                  f'<div class="tldr-v">{conf}%</div></div>')
    grid = f'<div class="tldr-grid">{cells}</div>' if cells else ''

    risk_html = ''
    if top_risk:
        risk_html = ('<div style="margin-top:10px;font-size:12.5px;line-height:1.7;'
                     f'color:#9a3412"><b>主要风险：</b>{top_risk}</div>')

    return f"""
<div class="tldr">
  <span class="tldr-tag">先看这里</span>
  <div class="tldr-line">{line}</div>
  {grid}
  {risk_html}
  {_data_badges(analysis, market_data)}
</div>"""

def _render_trading_advice(analysis):
    """Render trading advice box."""
    advice = analysis.get('trading_advice', {}) if analysis else {}
    if not advice:
        return ''
    style = advice.get('style', '中性')
    position = advice.get('position', '-')
    rationale = advice.get('rationale', '')
    return f"""
<div class="advice-box">
  <div class="style-label">今日风格: {style}</div>
  <div class="pos-range">建议仓位: {position}</div>
  <div class="rationale">{rationale}</div>
</div>"""

def _render_risk_warnings(analysis):
    """风险提示分两级渲染。

    实测一期午报有 12 条 risk_warnings、平均 275 字，其中 11 条是数据口径与
    方法说明（【数据分层】【指数层缺失】【量比口径替换声明】…），只有 1 条
    是真正的市场风险（【事件风险】：CPI）。全部用同一个橙色警告框平铺，
    等于把唯一重要的那条埋掉了。
    分类依据就用分析层自己写的【】标题——它已经把两类分得很清楚。
    """
    warnings = analysis.get('risk_warnings', []) if analysis else []
    if not warnings:
        return ''

    risks, caveats = [], []
    for w in warnings:
        title, body = _split_lead(w)
        (caveats if _is_caveat(title, body) else risks).append((title, body))

    parts = []
    for title, body in risks:
        head = f'<b>{title}</b><br>' if title else ''
        parts.append(f'<div class="risk-item">⚠️ {head}{_md_inline(body)}</div>')

    if caveats:
        items = ''.join(
            f'<div class="caveat-item">{f"<b>{t}</b> " if t else ""}{_md_inline(b)}</div>'
            for t, b in caveats)
        parts.append(
            '<div class="caveat-box">'
            f'<div class="caveat-title">数据口径与方法说明（{len(caveats)} 条）'
            '　—— 影响结论的可信度，但不是市场风险</div>'
            f'{items}</div>')
    return ''.join(parts)

def _render_sectors_summary(sectors):
    """Render structured sector summary table from sectors array."""
    if not sectors:
        return ''
    rows = ''
    for s in sectors:
        avg_chg = _num(s.get('avg_chg'))
        color = _clr(avg_chg)
        up = s.get('up', 0)
        down = s.get('down', 0)
        total = s.get('total', 0)
        leader = s.get('leader', {})
        leader_txt = f"{leader.get('name','')}{_fp(leader.get('chg_pct',0))}" if leader else '-'
        rows += f"""<tr>
            <td><b>{s.get('sector','-')}</b></td>
            <td style="color:{color};font-weight:bold">{_fp(avg_chg)}</td>
            <td style="color:#6b7280">{up}涨/{down}跌/{total}只</td>
            <td style="color:{_clr(leader.get('chg_pct',0))}">{leader_txt}</td>
          </tr>"""
    return f"""<table>
    <tr><th>板块</th><th>平均涨跌</th><th>涨跌家数</th><th>领涨股</th></tr>
    {rows}</table>"""

def _render_sector_rotation(analysis):
    """Render sector rotation analysis from analysis JSON."""
    rotations = analysis.get('sector_rotation', []) if analysis else []
    if not rotations:
        return ''
    role_color = {'主线': '#dc2626', '跟随': '#d97706', '退潮': '#6b7280'}
    items = ''
    for r in rotations:
        role = r.get('role', '')
        color = role_color.get(role, '#374151')
        items += f"""<div style="margin:6px 0;padding:6px 10px;border-left:3px solid {color};background:#f9fafb">
          <span style="color:{color};font-weight:bold;margin-right:8px">[{role}]</span>
          <b>{r.get('sector','')}</b>
          <span style="color:#6b7280;font-size:12px;margin-left:6px">{r.get('evidence','')}</span>
        </div>"""
    return f'<div style="margin-top:8px">{items}</div>'

def _render_prediction(analysis):
    """Render tomorrow prediction box from analysis."""
    pred = analysis.get('prediction', {}) if analysis else {}
    if not pred:
        return ''
    label = pred.get('label', '方向不明')
    confidence = pred.get('confidence', 50)
    reasons = pred.get('reasons', [])
    color = pred.get('color', '#d97706')

    reasons_html = ''.join(
        f'<li style="margin:5px 0;font-size:14px">{r}</li>' for r in reasons
    )
    return f"""
<div class="predict-box" style="border-color:{color}">
  <p style="margin:0 0 10px;font-size:16px">
    预测结论：<span class="predict-label" style="color:{color}">{label}</span>
    <span style="color:#6b7280;font-size:13px;margin-left:10px">置信度 {confidence}%</span>
  </p>
  <ul style="margin:0;padding-left:20px;line-height:2">{reasons_html}</ul>
  <p style="margin:10px 0 0;font-size:13px;color:#6b7280">⚠️ 预测基于量化模型，不构成投资建议。</p>
</div>"""

def _render_hk_us(analysis):
    """Render HK/US market section from CCR analysis."""
    hk_us = analysis.get('hk_us_summary', '') if analysis else ''
    hk_stocks = analysis.get('hk_stocks', []) if analysis else []
    us_stocks = analysis.get('us_stocks', []) if analysis else []
    if not hk_us and not hk_stocks and not us_stocks:
        return ''

    parts = []
    if hk_us:
        parts.append(f'<p style="font-size:13px;line-height:1.7;margin-bottom:10px">{hk_us}</p>')

    if hk_stocks:
        rows = ''
        for s in hk_stocks:
            chg = s.get('chg', 0) or 0
            color = _clr(chg)
            rows += f"""<tr>
            <td><b>{s.get('name','-')}</b></td>
            <td style="color:#6b7280">{s.get('code','-')}</td>
            <td style="font-weight:bold">{s.get('price','-')}</td>
            <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
          </tr>"""
        parts.append(f"""<table>
        <tr><th>港股</th><th>代码</th><th>最新价</th><th>涨跌幅</th></tr>
        {rows}</table>""")

    if us_stocks:
        rows = ''
        for s in us_stocks:
            chg = s.get('chg', 0) or 0
            color = _clr(chg)
            rows += f"""<tr>
            <td><b>{s.get('name','-')}</b></td>
            <td style="color:#6b7280">{s.get('code','-')}</td>
            <td style="font-weight:bold">{s.get('price','-')}</td>
            <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
          </tr>"""
        parts.append(f"""<table style="margin-top:10px">
        <tr><th>美股</th><th>代码</th><th>最新价</th><th>涨跌幅</th></tr>
        {rows}</table>""")

    return '\n'.join(parts)


def _render_degraded_banner(analysis):
    """数据降级横幅。verify.py 在 analysis 写入 degraded / verify 字段时显示；
    旧 analysis 无这些字段则返回空串（完全向后兼容）。"""
    if not analysis:
        return ''
    v = analysis.get('verify') or {}
    degraded = analysis.get('degraded') or v.get('degraded')
    hard = v.get('hard_fail')
    if not degraded and not hard:
        return ''
    reasons = v.get('reasons') or []
    if hard:
        bg, border, icon, title = '#fef2f2', '#dc2626', '⛔', '数据校验未通过（硬失败）——以下数字可信度低，请以券商行情为准'
    else:
        bg, border, icon, title = '#fffbeb', '#d97706', '⚠️', '数据降级提示——本期部分数据为盘中快照/缺失源，请谨慎参考'
    items = ''.join(f'<li>{_safe(r)}</li>' for r in reasons[:6])
    items_html = (f'<ul style="margin:6px 0 0;padding-left:20px;font-size:12px;color:#6b7280">{items}</ul>'
                  if items else '')
    return f"""<div style="background:{bg};border-left:4px solid {border};border-radius:6px;padding:12px 16px;margin:0 0 16px">
  <div style="font-weight:bold;color:{border};font-size:13px">{icon} {title}</div>
  {items_html}
</div>"""


# ── 研报层：分析层每天产出、但一直没有出口的字段 ──────────────────────────
# playbook Step 2 强制模型每期写 forecast_ledger_entry / thesis_updates /
# technical_analysis / fundamental_analysis / sentiment_analysis /
# anomaly_investigation / evidence_log / reflection，实测都是填满的
# （08-13 早报：11 条 thesis、3 档情景、17 条证据）。渲染端一条都没有取。
# 也就是说模型每天写的分析里有一半直接进了归档，从没到过读者眼前。

_SCEN_CN = {'base': '基准', 'bull': '偏多', 'bear': '偏空'}
_SCEN_COLOR = {'base': '#1e3a8a', 'bull': '#dc2626', 'bear': '#16a34a'}


def _bullets(items, color='#6b7280'):
    """把字符串列表渲染成紧凑列表；单个字符串也接受（分析层偶尔不写成数组）。"""
    if isinstance(items, str):
        items = [items] if items.strip() else []
    if not items:
        return ''
    lis = ''.join(f'<li style="margin:2px 0">{_md_inline(str(i))}</li>' for i in items)
    return (f'<ul style="margin:4px 0 0;padding-left:16px;font-size:11.5px;'
            f'line-height:1.65;color:{color}">{lis}</ul>')


def _render_scenarios(analysis):
    """情景与失效条件表。

    研报结论段的核心不是方向标签，而是"什么情况下这个判断作废"。给了失效
    条件，第二天才能机械地判对错；只给"偏多 55%"，复盘时怎么写都能自圆其说。
    分析层已经按 base/bull/bear 三档写好并要求概率合计 100，这里只是把它取出来。
    """
    entry = (analysis or {}).get('forecast_ledger_entry') or {}
    scenarios = entry.get('scenarios') or []
    if not scenarios:
        return ''

    rows = ''
    for s in scenarios:
        key = str(s.get('name', '')).strip().lower()
        label = _SCEN_CN.get(key, s.get('name') or '-')
        color = _SCEN_COLOR.get(key, '#374151')
        prob = s.get('probability')
        prob_txt = f'{_num(prob):.0f}%' if isinstance(prob, (int, float)) else '-'
        conds = _bullets(s.get('conditions'))
        inval = _bullets(s.get('invalidation'), color='#9a3412')
        rows += f"""<tr>
          <td style="white-space:nowrap"><b style="color:{color}">{label}</b></td>
          <td style="white-space:nowrap;font-weight:700;color:{color}">{prob_txt}</td>
          <td>{conds or '<span style="color:#9ca3af">未列出</span>'}</td>
          <td>{inval or '<span style="color:#9ca3af">未列出</span>'}</td>
        </tr>"""

    meta = []
    if entry.get('horizon'):
        meta.append(f'期限 {_safe(entry.get("horizon"))}')
    if entry.get('next_check'):
        meta.append(f'下次检验：{_safe(entry.get("next_check"))}')
    meta_html = (f'<div style="font-size:11.5px;color:#6b7280;margin-top:8px">'
                 f'{"　|　".join(meta)}</div>') if meta else ''

    return f"""<table>
    <tr><th style="width:52px">情景</th><th style="width:52px">概率</th>
        <th>成立条件</th><th>失效条件</th></tr>
    {rows}</table>{meta_html}"""


def _render_view_matrix(analysis):
    """技术／基本面／情绪三面并列。

    这三块分析层分别写在 technical_analysis、fundamental_analysis、
    sentiment_analysis 里。并列摆放的意义是让三者的分歧显形——三面一致和
    "技术偏多但基本面无验证"是完全不同的信号强度，平铺成散文会糊掉。
    """
    a = analysis or {}
    tech = a.get('technical_analysis') or {}
    fund = a.get('fundamental_analysis') or {}
    sent = a.get('sentiment_analysis') or {}
    if not (tech or fund or sent):
        return ''

    blocks = []
    if tech:
        legs = [('短期', tech.get('short_term')), ('中期', tech.get('medium_term')),
                ('长期', tech.get('long_term'))]
        body = ''.join(
            f'<div style="margin:4px 0"><b style="color:#1e3a8a">{k}</b>　'
            f'{_md_inline(str(v))}</div>'
            for k, v in legs if v)
        if body:
            blocks.append(('技术面', body, '#1e3a8a'))
    if fund:
        status = str(fund.get('status') or '').strip()
        tag = ''
        if status:
            tone = {'verified': ('#dcfce7', '#15803d'), 'partial': ('#fef3c7', '#b45309')}
            bg, fg = tone.get(status, ('#f1f5f9', '#64748b'))
            tag = (f'<span style="font-size:10.5px;font-weight:700;background:{bg};'
                   f'color:{fg};padding:1px 7px;border-radius:999px;margin-left:6px">'
                   f'{status}</span>')
        body = _md_inline(str(fund.get('summary') or ''))
        if body:
            blocks.append((f'基本面{tag}', body, '#0891b2'))
    if sent:
        conf = sent.get('confidence')
        parts = []
        if sent.get('hard_data'):
            parts.append(f'<div style="margin:4px 0"><b>硬数据</b>　'
                         f'{_md_inline(str(sent["hard_data"]))}</div>')
        if sent.get('social_signal'):
            # 社交信号和硬数据必须视觉分开：playbook 边界 3 不许拿传闻当事实
            parts.append(f'<div style="margin:4px 0;color:#6b7280"><b>社交信号</b>'
                         f'<span style="font-size:10.5px;background:#f1f5f9;color:#64748b;'
                         f'padding:1px 6px;border-radius:4px;margin:0 6px">未证实</span>'
                         f'{_md_inline(str(sent["social_signal"]))}</div>')
        if isinstance(conf, (int, float)):
            parts.append(f'<div style="font-size:11.5px;color:#6b7280;margin-top:4px">'
                         f'情绪判断置信度 {conf}%</div>')
        if parts:
            blocks.append(('情绪面', ''.join(parts), '#7c3aed'))

    if not blocks:
        return ''
    return ''.join(
        f'<div style="margin:10px 0;padding:10px 12px;background:#f9fafb;'
        f'border-left:3px solid {color};border-radius:0 6px 6px 0">'
        f'<div style="font-size:12.5px;font-weight:700;color:{color};margin-bottom:4px">'
        f'{title}</div>'
        f'<div style="font-size:12.5px;line-height:1.75;color:#374151">{body}</div></div>'
        for title, body, color in blocks)


def _render_reflection(analysis):
    """上期结果认账：对/错/部分对，错在哪一类，形成什么规则。

    这是整套系统区别于"每天重新讲一个故事"的地方，但一直没渲染。
    """
    r = (analysis or {}).get('reflection') or {}
    if not r:
        return ''
    tone = {'correct': ('#dcfce7', '#15803d', '判断正确'),
            'partial': ('#fef3c7', '#b45309', '部分正确'),
            'wrong': ('#fee2e2', '#b91c1c', '判断错误'),
            'pending': ('#f1f5f9', '#64748b', '尚未到期')}
    key = str(r.get('prior_result') or '').strip().lower()
    bg, fg, label = tone.get(key, ('#f1f5f9', '#64748b', key or '未标注'))

    rows = ''
    for k, v in (('错误类型', r.get('error_type')), ('教训', r.get('lesson')),
                 ('规则更新', r.get('rule_update'))):
        if v:
            rows += (f'<div style="margin:4px 0;font-size:12.5px;line-height:1.7">'
                     f'<b style="color:#475569">{k}</b>　{_md_inline(str(v))}</div>')
    return (f'<div style="margin-top:10px;padding:10px 12px;border:1px solid #e2e8f0;'
            f'border-radius:8px">'
            f'<span style="font-size:11px;font-weight:700;background:{bg};color:{fg};'
            f'padding:2px 8px;border-radius:999px">上期结果：{label}</span>{rows}</div>')


def _render_anomalies(analysis):
    """异常追因。已证实／候选／待核实三档必须分开——把候选原因写成结论是
    这类日报最常见的失真方式。"""
    items = (analysis or {}).get('anomaly_investigation') or []
    if not items:
        return ''
    out = ''
    for a in items:
        signal = a.get('signal') or ''
        if not signal:
            continue
        cols = ''
        for label, key, color in (('已证实', 'confirmed_causes', '#15803d'),
                                  ('候选', 'candidate_causes', '#b45309'),
                                  ('待核实', 'unresolved', '#64748b')):
            vals = a.get(key) or []
            body = _bullets(vals, color=color) or (
                '<div style="font-size:11.5px;color:#cbd5e1;margin-top:4px">—</div>')
            cols += (f'<td style="vertical-align:top;width:33%">'
                     f'<div style="font-size:11px;font-weight:700;color:{color}">{label}</div>'
                     f'{body}</td>')
        out += (f'<div style="margin:8px 0;padding:10px 12px;border:1px solid #e5e7eb;'
                f'border-radius:8px">'
                f'<div style="font-size:12.5px;font-weight:700;color:#111827">{_md_inline(signal)}</div>'
                f'<table style="margin-top:6px"><tr>{cols}</tr></table></div>')
    return out


def _render_thesis(analysis):
    """论点跟踪：上期每条 thesis 今天是加强了、减弱了还是关闭了。

    没有这一段，"连续性"就只是 playbook 里的一句要求，读者看不到兑现。
    """
    items = (analysis or {}).get('thesis_updates') or []
    if not items:
        return ''
    tone = {'strengthened': ('#dcfce7', '#15803d', '加强'),
            'weakened': ('#fef3c7', '#b45309', '减弱'),
            'carried_forward': ('#eff6ff', '#1d4ed8', '延续'),
            'closed': ('#f1f5f9', '#64748b', '关闭')}
    rows = ''
    for t in items:
        key = str(t.get('status') or '').strip().lower()
        bg, fg, label = tone.get(key, ('#f1f5f9', '#64748b', key or '-'))
        ev = t.get('evidence_ids') or []
        ev_txt = ('<span style="font-size:11px;color:#9ca3af;margin-left:6px">'
                  f'{"、".join(str(e) for e in ev)}</span>') if ev else ''
        inval = t.get('invalidation')
        inval_html = (f'<div style="font-size:11.5px;color:#9a3412;margin-top:3px">'
                      f'失效条件：{_md_inline(str(inval))}</div>') if inval else ''
        rows += f"""<tr>
          <td style="white-space:nowrap;vertical-align:top">
            <span style="font-size:11px;font-weight:700;background:{bg};color:{fg};
                         padding:2px 8px;border-radius:999px">{label}</span></td>
          <td><b style="font-size:12.5px">{_safe(t.get('thesis_id'), '-')}</b>{ev_txt}{inval_html}</td>
        </tr>"""
    return f'<table>{rows}</table>'


def _render_evidence(analysis):
    """证据链附录。硬事实与社交信号分色，来源与时间逐条摊开。

    放在最后是对的——但"放在最后"和"根本不渲染"是两回事。所有 evidence_ids
    引用的东西读者应当能查到，否则前面那些 E1/E7 就是死链。
    """
    log = (analysis or {}).get('evidence_log') or []
    if not log:
        return ''
    rows = ''
    for e in log:
        kind = str(e.get('kind') or '').strip()
        is_social = kind == 'social_signal'
        bg, fg, label = (('#f1f5f9', '#64748b', '社交信号') if is_social
                         else ('#eff6ff', '#1d4ed8', '硬事实'))
        url = e.get('source_url') or ''
        src = _safe(e.get('source'), '-')
        src_html = (f'<a href="{url}" style="color:#2563eb;text-decoration:none">{src}</a>'
                    if url.startswith('http') else src)
        when = e.get('published_at') or e.get('fetched_at') or ''
        rows += f"""<tr>
          <td style="white-space:nowrap;vertical-align:top;color:#9ca3af;font-size:11px">
            {_safe(e.get('id'), '-')}</td>
          <td style="white-space:nowrap;vertical-align:top">
            <span style="font-size:10.5px;font-weight:700;background:{bg};color:{fg};
                         padding:1px 7px;border-radius:999px">{label}</span></td>
          <td style="font-size:11.5px;line-height:1.6">{_md_inline(str(e.get('claim') or ''))}
            <div style="color:#9ca3af;margin-top:2px">{src_html}　{str(when)[:19]}</div></td>
        </tr>"""
    return f'<table>{rows}</table>'


def _render_verdict(analysis):
    """结论段：方向 + 置信度 + 理由，紧跟操作建议。

    `_render_prediction` 一直只在午报里被调用，早报从未渲染过它——早报
    prediction 的 reasons 每天都写、每天都丢，只有 label 漏进顶部摘要卡。
    """
    parts = [_render_prediction(analysis), _render_trading_advice(analysis)]
    return ''.join(p for p in parts if p)


# ── Main renderers ────────────────────────────────────────────────────────

def render_morning_report(market_data, analysis=None, date_str=''):
    """
    Render morning report HTML.

    market_data: dict from morning_latest.json (indices, ai_boards, board_stocks,
                 capital_flow_top30, watchlist_technicals, index_technicals, etc.)
    analysis: dict from CCR analysis JSON (market_summary, key_insights,
              stock_highlights, trading_advice, risk_warnings, hk_us_summary, etc.)
    """
    if not analysis:
        analysis = {}

    # Index section
    indices = market_data.get('indices', {})
    has_idx = _has_index_data(indices)
    idx_cards = _render_index_cards(indices) if has_idx else ''
    idx_table = _render_index_table(indices) if has_idx else ''

    # When quotes fall back to an earlier trading day, stamp that date on the tables
    quote_date = _quote_date_label(market_data)

    # Index technicals
    idx_tech = market_data.get('index_technicals', {})
    idx_tech_html = ''
    if idx_tech:
        idx_names = {'shanghai': '上证', 'shenzhen': '深证', 'chinext': '创业板', 'star50': '科创50'}
        rows = ''
        for key, t in idx_tech.items():
            name = idx_names.get(key, key)
            rows += f"""<tr>
            <td><b>{name}</b></td>
            <td>{_safe(t.get('ma_trend'))}</td>
            <td>{_safe(t.get('macd_status'))}</td>
            <td>{_num(t.get('rsi_12')):.0f}</td>
            <td>{_num(t.get('volume_ratio')):.1f}x {_safe(t.get('volume_label'))}</td>
          </tr>"""
        idx_tech_html = f"""<table style="margin-top:10px">
        <tr><th>指数</th><th>MA趋势</th><th>MACD</th><th>RSI</th><th>量比</th></tr>
        {rows}</table>"""

    # AI boards
    ai_boards = market_data.get('ai_boards', [])
    board_stocks = market_data.get('board_stocks', [])
    boards_html = _render_ai_boards(ai_boards, board_stocks)

    # Capital flow
    capital = market_data.get('capital_flow_top30', [])
    capital_html = _render_capital_flow(capital)

    # Watchlist technicals
    wt = _filter_tech(market_data.get('watchlist_technicals', []))
    sectors = market_data.get('sectors', [])
    sectors_summary_html = _render_sectors_summary(sectors)
    group = bool(sectors) and any(s.get('sector') for s in wt)
    wt_html = _render_watchlist_technicals(wt, group_by_sector=group, price_date=quote_date)
    score_chart = _render_score_ranking(wt)
    change_chart = _render_change_chart(wt)

    # CCR analysis sections —— 研报顺序：先结论，后论据，最后附录
    summary_html = _rich_text(analysis.get('market_summary', ''))
    verdict_html = _render_verdict(analysis)          # prediction + trading_advice
    scenarios_html = _render_scenarios(analysis)      # 情景与失效条件
    review_html = _render_review(analysis) + _render_reflection(analysis)
    insights_html = _render_insights(analysis)
    matrix_html = _render_view_matrix(analysis)       # 技术/基本面/情绪三面
    sector_read_html = _render_sector_read(analysis)
    highlights_html = _render_highlights(analysis)
    anomaly_html = _render_anomalies(analysis)
    thesis_html = _render_thesis(analysis)
    risk_html = _render_risk_warnings(analysis)
    evidence_html = _render_evidence(analysis)
    hk_us_html = _render_hk_us(analysis)

    # Assemble
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI股市日报 {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>🤖 AI股市机构日报</h1>
  <div class="subtitle">A股科创 · 港股科技 · 美股AI龙头 — 全市场覆盖</div>
  <div class="date-bar">
    <span>📅 {date_str} 早盘报告</span>
    <span>数据+AI分析自动生成</span>
  </div>
</div>

{_render_degraded_banner(analysis)}

{_render_tldr(analysis, market_data)}

{_section('sec-verdict', '🎯', '一、投资结论与操作建议', summary_html + verdict_html) if (summary_html or verdict_html) else ''}

{_section('sec-scenario', '🔀', '二、情景与失效条件', scenarios_html) if scenarios_html else ''}

{_section('sec-review', '🔁', '三、上期复盘', review_html) if review_html else ''}

{_section('sec-analysis', '🧠', '四、核心逻辑', insights_html + matrix_html) if (insights_html or matrix_html) else ''}

{_section('sec-predict', '🌏', '五之1　外围市场：港股 & 美股AI龙头', hk_us_html) if hk_us_html else ''}

{_section('sec-index', '📊', '五之2　A股大盘', idx_cards + idx_table + idx_tech_html) if (idx_cards or idx_tech_html) else ''}

{_section('sec-board', '🔥', '五之3　板块', boards_html + sectors_summary_html + sector_read_html)}

{_section('sec-capital', '💰', '五之4　资金流向 TOP10', capital_html) if capital else ''}

{_section('sec-score', '⭐', '五之5　个股：评分与技术面', score_chart + '<br/>' + wt_html + change_chart + highlights_html) if wt_html else ''}

{_section('sec-anomaly', '🔍', '六、异常追因', anomaly_html) if anomaly_html else ''}

{_section('sec-thesis', '🧭', '七、论点跟踪', thesis_html) if thesis_html else ''}

{_section('sec-risk', '⚠️', '八、风险提示', risk_html) if risk_html else ''}

{_section('sec-evidence', '📎', '附录　证据链', evidence_html) if evidence_html else ''}

<div class="footer">
  ⚠️ 仅供参考，不构成投资建议。股市有风险，入市需谨慎。<br>
  数据来源: 东方财富 + 新浪财经 | AI分析: Claude | 自动推送
</div>

</div>
</body></html>"""
    return html


def render_afternoon_report(market_data, analysis=None, date_str=''):
    """
    Render afternoon report HTML.

    market_data: dict from afternoon_latest.json (realtime_indices, ai_boards_rt,
                 board_stocks_rt, watchlist_rt, capital_flow_top30_rt, etc.)
                 + watchlist_technicals, index_technicals from P1 enhancements
    analysis: dict from CCR analysis JSON (same structure as morning but with
              afternoon-specific fields like intraday_changes, afternoon_plan)
    """
    if not analysis:
        analysis = {}

    # Index section (afternoon uses realtime_indices with different keys)
    rt_indices = market_data.get('realtime_indices', {})
    idx_cards = _render_index_cards(rt_indices) if _has_index_data(rt_indices) else ''

    # When quotes fall back to an earlier trading day, stamp that date on the tables
    quote_date = _quote_date_label(market_data)

    # Watchlist real-time
    watchlist_rt = market_data.get('watchlist_rt', [])
    wl_rows = ''
    # 回填价没有日内高低（缓存只存收盘价）。整池都没有时把两列摘掉，
    # 好过印 51 行「最高＝最低＝现价」——那读起来像全池零振幅。
    show_range = _has_intraday_range(watchlist_rt)
    if watchlist_rt:
        sorted_wl = sorted(watchlist_rt, key=lambda x: _num(x.get('change_pct')), reverse=True)
        for s in sorted_wl:
            name = s.get('name', '-')
            price = _num(s.get('current'))
            if s.get('change_pct') is None:
                prev = _num(s.get('yesterday_close'))
                chg = (price - prev) / prev * 100 if prev else 0
            else:
                chg = _num(s.get('change_pct'))
            vol = s.get('volume')
            color = _clr(chg)
            flag = ''
            if chg >= 9.9: flag = ' 🚀涨停'
            elif chg <= -9.9: flag = ' 💀跌停'
            elif chg >= 7: flag = ' ⚡强势'
            range_cells = (f'<td style="color:#6b7280">{_price_cell(s.get("high"))}</td>'
                           f'<td style="color:#6b7280">{_price_cell(s.get("low"))}</td>'
                           ) if show_range else ''
            wl_rows += f"""<tr>
            <td>{name}{flag}</td>
            <td style="font-weight:bold">{price:.2f}</td>
            <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
            {range_cells}<td>{_fmt_amt(vol)}</td>
          </tr>"""

    wl_price_hdr = f'现价<br/><span style="font-weight:normal;font-size:11px;color:#b45309">{quote_date}</span>' if quote_date else '现价'
    range_hdr = '<th>最高</th><th>最低</th>' if show_range else ''
    range_note = '' if show_range else (
        '<p style="font-size:11px;color:#b45309;margin:0 0 6px">'
        '本期报价来自收盘回填，数据源只提供收盘价，因此不列最高/最低——'
        '日内振幅本期不可得。</p>')
    watchlist_table = f"""{range_note}<table>
    <tr><th>股票</th><th>{wl_price_hdr}</th><th>涨跌幅</th>{range_hdr}<th>成交量</th></tr>
    {wl_rows}</table>""" if wl_rows else ''

    # Watchlist technicals (from P1)
    wt = _filter_tech(market_data.get('watchlist_technicals', []))
    wt_html = _render_watchlist_technicals(wt, price_date=quote_date)
    score_chart = _render_score_ranking(wt)
    change_chart = _render_change_chart(wt)

    # AI boards
    ai_boards = market_data.get('ai_boards_rt', [])
    board_stocks = market_data.get('board_stocks_rt', [])
    boards_html = _render_ai_boards(ai_boards, board_stocks)

    # Capital flow
    capital = market_data.get('capital_flow_top30_rt', [])
    capital_html = _render_capital_flow(capital) if capital else ''

    # CCR analysis
    analysis_html = _render_analysis(analysis)
    advice_html = _render_trading_advice(analysis)
    risk_html = _render_risk_warnings(analysis)
    pred_html = _render_prediction(analysis)

    # Afternoon-specific: intraday changes
    intraday = analysis.get('intraday_changes', '')
    intraday_html = (f'<div style="margin-bottom:12px"><b>盘中变化</b>{_rich_text(intraday)}</div>'
                     if intraday else '')

    # Afternoon plan
    plan = analysis.get('afternoon_plan', '')
    plan_html = f'<p style="font-size:13px;line-height:1.7">{plan}</p>' if plan else ''

    # Sector summary (new structured data)
    sectors = market_data.get('sectors', [])
    sectors_html = _render_sectors_summary(sectors)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI股市午报 {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

<div class="header" style="background:linear-gradient(135deg, #0f766e 0%, #0d9488 50%, #14b8a6 100%)">
  <h1>📊 A股AI板块午报</h1>
  <div class="subtitle">盘中实时数据 · AI分析</div>
  <div class="date-bar">
    <span>📅 {date_str} 14:00</span>
    <span>数据+AI分析自动生成</span>
  </div>
</div>

{_render_degraded_banner(analysis)}

{_render_tldr(analysis, market_data)}

{_section('sec-index', '📊', '大盘指数', idx_cards) if idx_cards else ''}

{_section('sec-board', '🔥', 'AI板块动态', boards_html) if boards_html else ''}

{_section('sec-capital', '💰', '资金流向 TOP10', capital_html) if capital_html else ''}

{_section('sec-chart', '📈', '涨跌幅图表', change_chart) if change_chart else ''}

{_section('sec-sectors', '📊', '板块强弱总览', sectors_html) if sectors_html else ''}

{_section('sec-watchlist', '🤖', f'关注池个股行情（{len(watchlist_rt)}只）' + (f' · 数据日期 {quote_date}' if quote_date else ''), watchlist_table) if watchlist_table else ''}

{_section('sec-score', '⭐', 'AI龙头综合评分', score_chart + '<br/>' + wt_html) if wt_html else ''}

{_section('sec-analysis', '🧠', '盘中分析', intraday_html + analysis_html + advice_html + risk_html) if (analysis_html or intraday_html) else ''}

{_section('sec-predict', '🔮', '明日走势预测', pred_html) if pred_html else ''}

<div class="footer">
  ⚠️ 仅供参考，不构成投资建议。股市有风险，入市需谨慎。<br>
  数据来源: 东方财富 + 新浪财经 | AI分析: Claude | 自动推送: 14:00
</div>

</div>
</body></html>"""
    return html
