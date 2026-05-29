"""
report_renderer.py — Shared HTML rendering for morning & afternoon stock reports.

Takes structured JSON data (from fetch scripts) + CCR analysis JSON → produces
complete HTML email body. Charts via quickchart.io image URLs.
"""
import json
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
"""

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
            chg = _num(data.get('chg') or data.get('change_pct') or data.get('pct'))
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

def _render_watchlist_technicals(technicals):
    """Render watchlist stocks with technical indicators and scores."""
    if not technicals:
        return '<p style="color:#9ca3af">技术指标数据不可用</p>'
    rows = ''
    # Sort by score descending
    sorted_t = sorted(technicals, key=lambda x: _num(x.get('score')), reverse=True)
    for s in sorted_t:
        name = s.get('name', '-')
        code = s.get('code', '-')
        chg = _num(s.get('chg_pct'))
        price = _num(s.get('close'))
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
    <tr><th>股票</th><th>代码</th><th>现价</th><th>涨跌幅</th><th>评分</th><th>MA趋势</th><th>MACD</th><th>RSI</th><th>量比</th></tr>
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

def _render_analysis(analysis):
    """Render CCR analysis JSON into HTML sections."""
    if not analysis:
        return ''
    parts = []

    # Market summary
    summary = analysis.get('market_summary', '')
    if summary:
        parts.append(f'<p style="font-size:14px;line-height:1.8;margin-bottom:12px">{summary}</p>')

    # Key insights
    insights = analysis.get('key_insights', [])
    if insights:
        items = ''.join(f'<li>{i}</li>' for i in insights)
        parts.append(f'<div class="insight-box"><b>核心观点：</b><ul style="margin-top:6px;padding-left:18px">{items}</ul></div>')

    # Stock highlights
    highlights = analysis.get('stock_highlights', [])
    if highlights:
        hl_items = ''
        for h in highlights:
            hl_items += f'<li><b>{h.get("name", "")}</b>({h.get("code", "")}): {h.get("comment", "")}</li>'
        parts.append(f'<div style="margin-top:10px"><b>个股点评：</b><ul style="margin-top:4px;padding-left:18px;font-size:13px;line-height:1.7">{hl_items}</ul></div>')

    # Sector analysis
    sector = analysis.get('sector_analysis', '')
    if sector:
        parts.append(f'<div style="margin-top:10px"><b>板块解读：</b><p style="font-size:13px;line-height:1.7;margin-top:4px">{sector}</p></div>')

    return '\n'.join(parts)

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
    """Render risk warnings."""
    warnings = analysis.get('risk_warnings', []) if analysis else []
    if not warnings:
        return ''
    items = ''.join(f'<div class="risk-item">⚠️ {w}</div>' for w in warnings)
    return items

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
    idx_cards = _render_index_cards(indices)
    idx_table = _render_index_table(indices)

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
    wt = market_data.get('watchlist_technicals', [])
    wt_html = _render_watchlist_technicals(wt)
    score_chart = _render_score_ranking(wt)
    change_chart = _render_change_chart(wt)

    # CCR analysis sections
    analysis_html = _render_analysis(analysis)
    advice_html = _render_trading_advice(analysis)
    risk_html = _render_risk_warnings(analysis)
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

{_section('sec-index', '📊', '大盘指数概览', idx_cards + idx_table + idx_tech_html)}

{_section('sec-capital', '💰', 'AI板块资金流向 TOP10', capital_html) if capital else ''}

{_section('sec-board', '🔥', 'AI板块动态', boards_html)}

{_section('sec-chart', '📈', '个股涨跌幅图表', change_chart) if change_chart else ''}

{_section('sec-score', '⭐', 'AI龙头综合评分', score_chart + '<br/>' + wt_html) if wt else ''}

{_section('sec-analysis', '🧠', 'AI深度分析', analysis_html + advice_html + risk_html) if analysis_html else ''}

{_section('sec-predict', '🌏', '港股 & 美股AI龙头', hk_us_html) if hk_us_html else ''}

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
    idx_cards = _render_index_cards(rt_indices)

    # Watchlist real-time
    watchlist_rt = market_data.get('watchlist_rt', [])
    wl_rows = ''
    if watchlist_rt:
        sorted_wl = sorted(watchlist_rt, key=lambda x: _num(x.get('change_pct')), reverse=True)
        for s in sorted_wl:
            name = s.get('name', '-')
            price = _num(s.get('current'))
            chg = _num(s.get('change_pct'))
            high = _num(s.get('high'))
            low = _num(s.get('low'))
            vol = s.get('volume')
            color = _clr(chg)
            flag = ''
            if chg >= 9.9: flag = ' 🚀涨停'
            elif chg <= -9.9: flag = ' 💀跌停'
            elif chg >= 7: flag = ' ⚡强势'
            wl_rows += f"""<tr>
            <td>{name}{flag}</td>
            <td style="font-weight:bold">{price:.2f}</td>
            <td style="color:{color};font-weight:bold">{_fp(chg)}</td>
            <td style="color:#6b7280">{high:.2f}</td>
            <td style="color:#6b7280">{low:.2f}</td>
            <td>{_fmt_amt(vol)}</td>
          </tr>"""

    watchlist_table = f"""<table>
    <tr><th>股票</th><th>现价</th><th>涨跌幅</th><th>最高</th><th>最低</th><th>成交量</th></tr>
    {wl_rows}</table>""" if wl_rows else ''

    # Watchlist technicals (from P1)
    wt = market_data.get('watchlist_technicals', [])
    wt_html = _render_watchlist_technicals(wt) if wt else ''
    score_chart = _render_score_ranking(wt) if wt else ''
    change_chart = _render_change_chart(wt) if wt else ''

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
    intraday_html = f'<p style="font-size:13px;line-height:1.7">{intraday}</p>' if intraday else ''

    # Afternoon plan
    plan = analysis.get('afternoon_plan', '')
    plan_html = f'<p style="font-size:13px;line-height:1.7">{plan}</p>' if plan else ''

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

{_section('sec-index', '📊', '大盘指数', idx_cards)}

{_section('sec-board', '🔥', 'AI板块动态', boards_html)}

{_section('sec-capital', '💰', '资金流向 TOP10', capital_html) if capital_html else ''}

{_section('sec-chart', '📈', '涨跌幅图表', change_chart) if change_chart else ''}

{_section('sec-watchlist', '🤖', f'关注池个股行情（{len(watchlist_rt)}只）', watchlist_table)}

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
