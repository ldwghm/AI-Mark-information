import requests, os, base64, json, time
from datetime import datetime

RESEND_API_KEY = os.environ['RESEND_API_KEY']
GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
RECIPIENT      = '1654155512@qq.com'
REPO           = 'ldwghm/AI-Mark-information'

INDICES = ['sh000001', 'sz399001', 'sz399006', 'sh000688']
INDEX_NAMES = {
    'sh000001': '上证指数', 'sz399001': '深证成指',
    'sz399006': '创业板指', 'sh000688': '科创50',
}

WATCHLIST = [
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
WATCHLIST_CODES = {s[0] for s in WATCHLIST}

EM_BASE = 'https://push2.eastmoney.com/api/qt/clist/get'
EM_UT   = 'bd1d9ddb04089700cf9c27f6f7426281'
SINA_VIP = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'

# ── Helpers ────────────────────────────────────────────────────────────────

def clr(p): return '#16a34a' if p >= 0 else '#dc2626'
def fp(p):  return f'{p:+.2f}%'

def fmt_amt(a):
    if a >= 1e8: return f'{a/1e8:.1f}亿'
    if a >= 1e4: return f'{a/1e4:.0f}万'
    return f'{a:.0f}'

def fmt_flow(v):
    """Format main force net flow (yuan) in 亿/万."""
    if v is None: return '-'
    if v >= 1e8:  return f'+{v/1e8:.1f}亿' if v >= 0 else f'{v/1e8:.1f}亿'
    if v >= 1e4:  return f'+{v/1e4:.0f}万' if v >= 0 else f'{v/1e4:.0f}万'
    if v <= -1e8: return f'{v/1e8:.1f}亿'
    if v <= -1e4: return f'{v/1e4:.0f}万'
    return f'{v:.0f}'

def vol_badge(cur, prev):
    if not prev or prev == 0:
        return '<span style="color:#9ca3af;font-size:11px">首日</span>'
    pct = (cur - prev) / prev * 100
    if pct > 20:
        label, color = f'放量+{pct:.0f}%', '#16a34a'
    elif pct < -20:
        label, color = f'缩量{pct:.0f}%', '#dc2626'
    else:
        label, color = f'平量{pct:+.0f}%', '#9ca3af'
    arrow = '▲' if pct > 0 else '▼'
    return f"<span style='color:{color};font-size:11px'>{arrow}{label}</span>"

def pace_badge(cur_amt, prev_full_amt):
    """Volume pace: how much of yesterday's full-day volume is reached by 2pm."""
    if not prev_full_amt or prev_full_amt == 0:
        return '<span style="color:#9ca3af;font-size:11px">-</span>'
    pct = cur_amt / prev_full_amt * 100
    if pct >= 80:
        color, label = '#16a34a', f'量能充足{pct:.0f}%'
    elif pct >= 55:
        color, label = '#d97706', f'量能正常{pct:.0f}%'
    else:
        color, label = '#dc2626', f'量能不足{pct:.0f}%'
    return f"<span style='color:{color};font-size:12px'>{label}</span>"

def limit_flag(pct):
    if pct >= 9.9:  return ' 🚀涨停'
    if pct <= -9.9: return ' 💀跌停'
    if pct >= 7.0:  return ' ⚡强势'
    return ''

def code_prefix(code_bare):
    """Infer exchange prefix from bare code."""
    if code_bare.startswith('6'): return 'sh'
    if code_bare.startswith(('0', '3')): return 'sz'
    return 'bj'  # BSE codes start with 8/9

def is_bse(code_bare):
    return code_bare.startswith(('8', '9'))

# ── Data sources ───────────────────────────────────────────────────────────

def fetch_eastmoney(fs, fid='f3', po=1, pz=50):
    """Generic East Money list fetch. Returns list of field dicts or []."""
    try:
        r = requests.get(EM_BASE, params={
            'pn': 1, 'pz': pz, 'po': po, 'np': 1,
            'ut': EM_UT, 'fltt': 2, 'invt': 2, 'fid': fid, 'fs': fs,
            'fields': 'f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f62,f184',
        }, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.eastmoney.com/',
        }, timeout=12)
        if r.status_code != 200:
            print(f'[EM] HTTP {r.status_code} for fs={fs}')
            return []
        data = r.json()
        diff = data.get('data', {}) or {}
        return diff.get('diff', []) or []
    except Exception as e:
        print(f'[EM] Error: {e}')
        return []

def fetch_sina_toplist(sort='changepercent', num=50, node='hs_a'):
    """Sina VIP top stocks. Returns list of dicts or []."""
    try:
        r = requests.get(SINA_VIP, params={
            'page': 1, 'num': num, 'sort': sort, 'asc': 0, 'node': node,
        }, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn',
        }, timeout=12)
        if r.status_code != 200:
            return []
        return json.loads(r.text) or []
    except Exception as e:
        print(f'[SinaVIP] Error sort={sort}: {e}')
        return []

def fetch_sina_hq(codes):
    """Sina hq real-time data. Returns dict {code: parsed_dict}."""
    try:
        r = requests.get(
            f'https://hq.sinajs.cn/list={",".join(codes)}',
            headers={'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'},
            timeout=12)
        r.encoding = 'gbk'
        result = {}
        for line in r.text.strip().split('\n'):
            p = _parse_sina_line(line)
            if p:
                result[p['code']] = p
        return result
    except Exception as e:
        print(f'[Sina HQ] Error: {e}')
        return {}

def _parse_sina_line(line):
    if '="' not in line or line.strip().endswith('="";'):
        return None
    code = line.split('hq_str_')[1].split('=')[0]
    d = line.split('="')[1].rstrip('";').split(',')
    if len(d) < 10:
        return None
    try:
        prev, cur = float(d[2]), float(d[3])
        return {
            'code': code, 'name': d[0],
            'open': float(d[1]), 'prev': prev, 'cur': cur,
            'high': float(d[4]), 'low': float(d[5]),
            'vol': float(d[8]) if d[8] else 0,
            'amt': float(d[9]) if d[9] else 0,
            'pct': (cur - prev) / prev * 100 if prev else 0,
        }
    except:
        return None

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
        print(f'[history] read error: {e}')
    return {}, None

# ── Candidate pool ─────────────────────────────────────────────────────────

def build_candidate_pool():
    """
    Collect stock candidates from East Money + Sina VIP.
    Returns list of dicts with keys: code(with prefix), name, pct, amt,
    turnover_rate, main_net_inflow, main_ratio, mktcap, source
    """
    candidates = {}  # code -> dict

    # ── East Money: top gainers ──
    em_gainers = fetch_eastmoney(
        fs='m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f3', pz=50)
    for item in em_gainers:
        code_bare = str(item.get('f12', ''))
        if not code_bare or is_bse(code_bare):
            continue
        full_code = code_prefix(code_bare) + code_bare
        candidates[full_code] = {
            'code': full_code, 'name': item.get('f14', '?'),
            'pct': item.get('f3', 0) or 0,
            'amt': item.get('f6', 0) or 0,
            'turnover_rate': item.get('f8', 0) or 0,
            'main_net_inflow': item.get('f62', 0) or 0,
            'main_ratio': item.get('f184', 0) or 0,
            'mktcap': item.get('f20', 0) or 0,
            'source': 'em_gain',
        }
    print(f'[pool] EM gainers: {len(em_gainers)}, added {len(candidates)}')
    time.sleep(0.3)

    # ── East Money: main force money flow ──
    em_flow = fetch_eastmoney(
        fs='m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23', fid='f62', pz=50)
    em_flow_added = 0
    for item in em_flow:
        code_bare = str(item.get('f12', ''))
        if not code_bare or is_bse(code_bare):
            continue
        full_code = code_prefix(code_bare) + code_bare
        if full_code not in candidates:
            candidates[full_code] = {
                'code': full_code, 'name': item.get('f14', '?'),
                'pct': item.get('f3', 0) or 0,
                'amt': item.get('f6', 0) or 0,
                'turnover_rate': item.get('f8', 0) or 0,
                'main_net_inflow': item.get('f62', 0) or 0,
                'main_ratio': item.get('f184', 0) or 0,
                'mktcap': item.get('f20', 0) or 0,
                'source': 'em_flow',
            }
            em_flow_added += 1
        else:
            # Enrich with flow data
            candidates[full_code]['main_net_inflow'] = item.get('f62', candidates[full_code]['main_net_inflow']) or 0
            candidates[full_code]['main_ratio'] = item.get('f184', candidates[full_code]['main_ratio']) or 0
    print(f'[pool] EM flow: {len(em_flow)}, new added {em_flow_added}')
    time.sleep(0.3)

    # ── East Money: hot concept sectors → constituent stocks ──
    sectors = fetch_eastmoney(fs='m:90+t:3+f:!50', fid='f3', pz=10)
    sector_names = {}
    hot_sector_codes = []
    for i, sec in enumerate(sectors[:5]):
        sec_code = str(sec.get('f12', ''))
        sec_name = sec.get('f14', f'板块{i+1}')
        if not sec_code:
            continue
        hot_sector_codes.append((sec_code, sec_name, i))
        sector_names[sec_code] = sec_name
        time.sleep(0.2)
        stocks = fetch_eastmoney(fs=f'b:{sec_code}', fid='f3', pz=20)
        added = 0
        for item in stocks:
            code_bare = str(item.get('f12', ''))
            if not code_bare or is_bse(code_bare):
                continue
            full_code = code_prefix(code_bare) + code_bare
            if full_code not in candidates:
                candidates[full_code] = {
                    'code': full_code, 'name': item.get('f14', '?'),
                    'pct': item.get('f3', 0) or 0,
                    'amt': item.get('f6', 0) or 0,
                    'turnover_rate': item.get('f8', 0) or 0,
                    'main_net_inflow': item.get('f62', 0) or 0,
                    'main_ratio': item.get('f184', 0) or 0,
                    'mktcap': item.get('f20', 0) or 0,
                    'source': f'sector_{sec_name}',
                }
                added += 1
        print(f'[pool] sector {sec_name}: {len(stocks)} stocks, {added} new')

    # ── Fallback: Sina VIP top gainers (if East Money gave nothing) ──
    if len(candidates) < 10:
        print('[pool] EM thin, trying Sina VIP...')
        sina_gainers = fetch_sina_toplist(sort='changepercent', num=50)
        for item in sina_gainers:
            sym = item.get('symbol', '')  # e.g. sh600522
            if not sym or sym.startswith('bj'):
                continue
            full_code = sym  # already has prefix
            code_bare = sym[2:]
            if is_bse(code_bare):
                continue
            name = item.get('name', '?')
            try:
                pct  = float(item.get('changepercent', 0))
                amt  = float(item.get('amount', 0))
                turn = float(item.get('turnoverratio', 0))
                if full_code not in candidates:
                    candidates[full_code] = {
                        'code': full_code, 'name': name,
                        'pct': pct, 'amt': amt,
                        'turnover_rate': turn,
                        'main_net_inflow': None,
                        'main_ratio': None,
                        'mktcap': float(item.get('mktcap', 0)),
                        'source': 'sina_vip',
                    }
            except:
                pass
        print(f'[pool] After Sina VIP: {len(candidates)} total candidates')

    return list(candidates.values()), sectors[:10], hot_sector_codes

# ── Scoring & recommendation ───────────────────────────────────────────────

def score_stock(c, all_candidates, vol_history, hot_sector_codes):
    """Return (score 0-100, reasons list)."""
    score = 0
    reasons = []

    # 1. Pct change (20 pts)
    pct = c['pct'] or 0
    if 3 <= pct <= 7:
        score += 20; reasons.append(f'涨幅{pct:.1f}%（区间理想）')
    elif 7 < pct < 9.9:
        score += 10; reasons.append(f'涨幅{pct:.1f}%（偏高，追高有风险）')
    elif 1 <= pct < 3:
        score += 12; reasons.append(f'涨幅{pct:.1f}%（温和上涨）')
    elif 0 <= pct < 1:
        score += 5
    elif pct < 0:
        score += max(0, int(5 + pct))  # -5% → 0, -1% → 4

    # 2. Main force net inflow (25 pts)
    mni = c['main_net_inflow']
    if mni is not None:
        flows = [x['main_net_inflow'] for x in all_candidates
                 if x['main_net_inflow'] is not None]
        flows_sorted = sorted(flows, reverse=True)
        n = len(flows_sorted)
        if n > 0:
            try:
                rank = flows_sorted.index(mni)
                if rank < n * 0.10:
                    score += 25; reasons.append(f'主力净流入{fmt_flow(mni)}（前10%）')
                elif rank < n * 0.25:
                    score += 18; reasons.append(f'主力净流入{fmt_flow(mni)}（前25%）')
                elif rank < n * 0.50:
                    score += 10; reasons.append(f'主力净流入{fmt_flow(mni)}')
                elif mni < 0:
                    score -= 5; reasons.append(f'主力净流出{fmt_flow(mni)}')
            except ValueError:
                pass

    # 3. Main force ratio (10 pts)
    mr = c['main_ratio'] or 0
    if mr > 20:
        score += 10; reasons.append(f'主力占比{mr:.0f}%（强势）')
    elif mr > 10:
        score += 6
    elif mr > 0:
        score += 2

    # 4. Turnover rate (10 pts)
    tr = c['turnover_rate'] or 0
    if 5 <= tr <= 15:
        score += 10; reasons.append(f'换手率{tr:.1f}%（活跃）')
    elif 3 <= tr < 5 or 15 < tr <= 25:
        score += 6
    elif tr > 0:
        score += 2

    # 5. Hot sector membership (15 pts)
    # hot_sector_codes: list of (sec_code, sec_name, rank_index)
    # We'd need to know which sector each candidate belongs to, but EM doesn't
    # directly tag stocks with sector codes in the current payload.
    # We use source field as a proxy.
    src = c.get('source', '')
    if src.startswith('sector_'):
        sec_name = src[len('sector_'):]
        # Find rank in hot_sector_codes
        for sc, sn, ri in hot_sector_codes:
            if sn == sec_name:
                if ri < 3:
                    score += 15; reasons.append(f'所属概念「{sec_name}」今日第{ri+1}强')
                elif ri < 5:
                    score += 10; reasons.append(f'所属概念「{sec_name}」今日前5')
                else:
                    score += 5; reasons.append(f'所属热门概念「{sec_name}」')
                break

    # 6. Volume pace (10 pts) - compare current turnover vs yesterday's full day
    prev_info = vol_history.get(c['code'], {})
    prev_amt  = prev_info.get('amt', 0)
    if prev_amt > 0:
        pace = (c['amt'] or 0) / prev_amt
        if pace >= 0.8:
            score += 10; reasons.append(f'量能节奏{pace*100:.0f}%（充足）')
        elif pace >= 0.55:
            score += 6
        elif pace >= 0.3:
            score += 2
        else:
            score -= 3

    # 7. Price range (10 pts)
    # We don't have price directly in candidates from EM (only available if
    # we joined with hq data); skip if not available
    # (price comes from Sina HQ fetch done separately)

    return min(score, 100), reasons

def generate_recommendations(candidates, vol_history, hot_sector_codes, watchlist_hq):
    """Filter, score, and return top recommended stocks."""
    # Filter
    valid = []
    for c in candidates:
        pct = c['pct'] or 0
        amt = c['amt'] or 0
        name = c['name'] or ''
        if pct >= 9.9:   continue  # limit up, can't buy
        if amt < 1e8:    continue  # < 1亿 turnover, illiquid
        if 'ST' in name: continue  # ST/\*ST
        if is_bse(c['code'][2:]): continue
        valid.append(c)

    print(f'[recommend] {len(candidates)} candidates → {len(valid)} after filter')

    # Score
    scored = []
    for c in valid:
        sc, reasons = score_stock(c, valid, vol_history, hot_sector_codes)
        scored.append({**c, 'score': sc, 'reasons': reasons})

    scored.sort(key=lambda x: x['score'], reverse=True)

    # Split into watchlist and new discovery
    top = scored[:15]  # consider top 15 before split
    in_watch  = [s for s in top if s['code'] in WATCHLIST_CODES][:3]
    new_found = [s for s in top if s['code'] not in WATCHLIST_CODES][:5]
    return new_found, in_watch

# ── Prediction engine ──────────────────────────────────────────────────────

def predict_tomorrow(idx_hq, watchlist_hq, sectors_em, vol_history):
    """
    Returns (label, color, confidence%, reasons_list).
    Signals: index trend, sector breadth, money flow direction,
             volume pace, limit ratio (within watchlist), sector concentration.
    """
    score = 0
    reasons = []

    mi = idx_hq.get('sh000001')
    idx_pct = mi['pct'] if mi else 0

    # Signal 1: Index intraday performance
    if idx_pct > 1.5:
        score += 3; reasons.append(('✅', f'上证涨{idx_pct:.2f}%，盘面强势，多头占优'))
    elif idx_pct > 0.5:
        score += 2; reasons.append(('✅', f'上证涨{idx_pct:.2f}%，偏多格局'))
    elif idx_pct > 0:
        score += 1; reasons.append(('⚠️', f'上证小幅翻红{idx_pct:.2f}%，方向不明'))
    elif idx_pct > -0.5:
        score -= 1; reasons.append(('⚠️', f'上证小幅下跌{idx_pct:.2f}%，谨慎'))
    elif idx_pct > -1.5:
        score -= 2; reasons.append(('❌', f'上证下跌{idx_pct:.2f}%，空头压力较大'))
    else:
        score -= 3; reasons.append(('❌', f'上证大跌{idx_pct:.2f}%，空头占优'))

    # Signal 2: Sector breadth (East Money concept sectors up/down ratio)
    if sectors_em:
        up_sec = sum(1 for s in sectors_em if (s.get('f3') or 0) > 0)
        total_sec = len(sectors_em)
        breadth = up_sec / total_sec * 100 if total_sec else 50
        if breadth > 70:
            score += 3; reasons.append(('✅', f'概念板块涨跌比{up_sec}/{total_sec}，市场广度健康'))
        elif breadth > 50:
            score += 1; reasons.append(('⚠️', f'概念板块涨跌比{up_sec}/{total_sec}，方向偏多'))
        elif breadth > 30:
            score -= 1; reasons.append(('⚠️', f'概念板块涨跌比{up_sec}/{total_sec}，市场分化'))
        else:
            score -= 3; reasons.append(('❌', f'概念板块涨跌比{up_sec}/{total_sec}，普跌格局'))
    else:
        # Fallback: use watchlist sector breadth
        all_w = list(watchlist_hq.values())
        up_w  = sum(1 for x in all_w if x['pct'] > 0)
        reasons.append(('⚠️', f'关注池{up_w}/{len(all_w)}只上涨（板块数据不可用）'))
        score += 1 if up_w > len(all_w) * 0.6 else (-1 if up_w < len(all_w) * 0.4 else 0)

    # Signal 3: Main force money flow (sum of top candidates)
    all_w_list = list(watchlist_hq.values())
    w_amt_now  = sum(x['amt'] for x in all_w_list if x['amt'])
    prev_amts  = [vol_history.get(x['code'], {}).get('amt', 0) for x in all_w_list]
    w_amt_prev = sum(a for a in prev_amts if a)
    if w_amt_prev > 0:
        flow_ratio = w_amt_now / w_amt_prev
        if flow_ratio > 1.3:
            score += 2; reasons.append(('✅', f'关注池成交额较昨日放量{(flow_ratio-1)*100:.0f}%，资金积极'))
        elif flow_ratio > 0.9:
            score += 1; reasons.append(('⚠️', f'关注池成交额与昨日持平'))
        else:
            score -= 2; reasons.append(('❌', f'关注池成交额较昨日缩量{(1-flow_ratio)*100:.0f}%，资金撤退'))

    # Signal 4: Volume pace of main index at 2pm
    if mi:
        prev_idx_amt = vol_history.get('sh000001', {}).get('amt', 0)
        if prev_idx_amt > 0:
            pace = mi['amt'] / prev_idx_amt
            if pace >= 0.85:
                score += 2; reasons.append(('✅', f'上证14:00量能{pace*100:.0f}%（充足，全天量能有望超昨日）'))
            elif pace >= 0.60:
                score += 1; reasons.append(('⚠️', f'上证14:00量能{pace*100:.0f}%（正常节奏）'))
            elif pace >= 0.40:
                score -= 1; reasons.append(('❌', f'上证14:00量能{pace*100:.0f}%（偏低，市场观望）'))
            else:
                score -= 2; reasons.append(('❌', f'上证14:00量能{pace*100:.0f}%（严重缩量，谨慎）'))

    # Signal 5: Limit up/down ratio in watchlist
    lu = sum(1 for x in all_w_list if x['pct'] >= 9.9)
    ld = sum(1 for x in all_w_list if x['pct'] <= -9.9)
    if lu >= 3:
        score += 2; reasons.append(('✅', f'关注池{lu}只涨停，赚钱效应强'))
    elif lu >= 1:
        score += 1; reasons.append(('✅', f'关注池{lu}只涨停'))
    if ld >= 3:
        score -= 2; reasons.append(('❌', f'关注池{ld}只跌停，杀跌情绪蔓延'))
    elif ld >= 1:
        score -= 1; reasons.append(('❌', f'关注池{ld}只跌停'))

    # Signal 6: Hot sector concentration / momentum
    if sectors_em:
        top_sec_pcts = [s.get('f3', 0) or 0 for s in sectors_em[:5]]
        avg_top5 = sum(top_sec_pcts) / len(top_sec_pcts) if top_sec_pcts else 0
        if avg_top5 > 2:
            score += 2; reasons.append(('✅', f'前5热门板块平均涨{avg_top5:.1f}%，主线热度高'))
        elif avg_top5 > 0:
            score += 1; reasons.append(('⚠️', f'前5热门板块均小幅上涨'))
        else:
            score -= 1; reasons.append(('❌', f'前5热门板块整体偏弱'))

    # Map score to prediction
    if score >= 10:
        label, color, conf = '明日大概率上涨', '#16a34a', min(90, 60 + score * 2)
    elif score >= 5:
        label, color, conf = '明日偏多', '#65a30d', min(75, 50 + score * 2)
    elif score >= -4:
        label, color, conf = '明日方向不明', '#d97706', 40
    elif score >= -9:
        label, color, conf = '明日偏空', '#ea580c', min(75, 50 + abs(score) * 2)
    else:
        label, color, conf = '明日大概率下跌', '#dc2626', min(90, 60 + abs(score) * 2)

    return label, color, conf, score, reasons

# ── Trading style (reused from morning logic) ─────────────────────────────

def trading_style_score(idx_hq, watchlist_hq, vol_history):
    """Return (style, color, pos_range, style_desc, score, factors)."""
    mi = idx_hq.get('sh000001')
    idx_pct = mi['pct'] if mi else 0

    all_w = list(watchlist_hq.values())
    lu_cnt = sum(1 for x in all_w if x['pct'] >= 9.9)
    ld_cnt = sum(1 for x in all_w if x['pct'] <= -9.9)
    pos_sec = sum(1 for x in all_w if x['pct'] > 0)
    breadth = pos_sec / len(all_w) * 100 if all_w else 50

    # Volume change
    prev_idx_amt = vol_history.get('sh000001', {}).get('amt', 0)
    vol_chg = None
    if mi and prev_idx_amt > 0:
        vol_chg = (mi['amt'] - prev_idx_amt) / prev_idx_amt * 100

    score = 0
    factors = []

    if idx_pct > 1.5:
        score += 3; factors.append(('✅', f'大盘强势+{idx_pct:.2f}%，做多情绪高涨'))
    elif idx_pct > 0.5:
        score += 2; factors.append(('✅', f'大盘上涨{idx_pct:.2f}%，偏多格局'))
    elif idx_pct > 0:
        score += 1; factors.append(('⚠️', f'大盘小幅翻红，方向不明'))
    elif idx_pct > -0.5:
        score -= 1; factors.append(('⚠️', f'大盘小幅回落{idx_pct:.2f}%'))
    elif idx_pct > -1.5:
        score -= 2; factors.append(('❌', f'大盘下跌{idx_pct:.2f}%，控制仓位'))
    else:
        score -= 3; factors.append(('❌', f'大盘大跌{idx_pct:.2f}%，建议轻仓'))

    if vol_chg is not None:
        if vol_chg > 30:
            score += 2; factors.append(('✅', f'成交额较昨放量{vol_chg:.0f}%，资金积极'))
        elif vol_chg > 10:
            score += 1; factors.append(('✅', f'成交额温和放量{vol_chg:.0f}%'))
        elif vol_chg < -30:
            score -= 2; factors.append(('❌', f'成交额缩量{abs(vol_chg):.0f}%，市场观望'))
        elif vol_chg < -10:
            score -= 1; factors.append(('❌', f'成交额缩量{abs(vol_chg):.0f}%'))
        else:
            factors.append(('⚠️', f'成交额变化不大（{vol_chg:+.0f}%）'))
    else:
        factors.append(('⚠️', '历史量能数据不足，无法对比'))

    if lu_cnt >= 2:
        score += 2; factors.append(('✅', f'关注池{lu_cnt}只涨停，赚钱效应强'))
    elif lu_cnt >= 1:
        score += 1; factors.append(('✅', f'关注池{lu_cnt}只涨停'))
    if ld_cnt >= 2:
        score -= 2; factors.append(('❌', f'关注池{ld_cnt}只跌停，情绪偏差'))

    if breadth > 70:
        score += 1; factors.append(('✅', f'关注池{pos_sec}/{len(all_w)}只上涨，普涨格局'))
    elif breadth < 30:
        score -= 1; factors.append(('❌', f'关注池仅{pos_sec}/{len(all_w)}只上涨，市场分化'))

    if score >= 5:
        style, scolor, pos = '激进', '#16a34a', '60-80%'
        desc = '市场强势，可积极参与强势股，追随最强板块龙头，止损-3%。'
    elif score >= 3:
        style, scolor, pos = '偏多', '#65a30d', '40-60%'
        desc = '市场偏强，适度参与，选量能配合的强势股，止损-5%。'
    elif score >= 1:
        style, scolor, pos = '中性偏多', '#d97706', '30-50%'
        desc = '轻仓参与确定性机会，等待明确信号再加仓，止损-5%。'
    elif score >= -1:
        style, scolor, pos = '中性', '#6b7280', '20-40%'
        desc = '以观望为主，持有已盈利仓位，控制新开仓。'
    elif score >= -3:
        style, scolor, pos = '偏空', '#ea580c', '≤30%'
        desc = '减仓为主，只持高确定性个股，严格止损，优先保护本金。'
    else:
        style, scolor, pos = '保守', '#dc2626', '0-20%'
        desc = '市场弱势，建议空仓或极轻仓观望，等待更好时机。'

    return style, scolor, pos, desc, score, factors

# ── HTML builder ───────────────────────────────────────────────────────────

def build_pm_html(today, idx_hq, watchlist_hq, vol_history,
                  new_recs, watch_recs, sectors_em,
                  pred_label, pred_color, pred_conf, pred_score, pred_reasons,
                  ts_style, ts_color, ts_pos, ts_desc, ts_score, ts_factors):

    stock_map = {s[0]: s for s in WATCHLIST}

    # ── Index table ──
    idx_rows = ''
    for code in INDICES:
        d = idx_hq.get(code)
        if not d:
            continue
        prev_amt = vol_history.get(code, {}).get('amt', 0)
        pb = pace_badge(d['amt'], prev_amt)
        idx_rows += (
            f"<tr>"
            f"<td><b>{INDEX_NAMES.get(code, code)}</b></td>"
            f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
            f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
            f"<td style='color:#6b7280'>{d['open']:.2f}</td>"
            f"<td>{fmt_amt(d['amt'])}</td>"
            f"<td>{pb}</td>"
            f"</tr>"
        )

    # ── Hot sectors (East Money) ──
    if sectors_em:
        sec_rows = ''
        for i, s in enumerate(sectors_em[:10]):
            sp = s.get('f3', 0) or 0
            sname = s.get('f14', '-')
            sec_rows += (
                f"<tr>"
                f"<td style='color:#6b7280'>{i+1}</td>"
                f"<td><b>{sname}</b></td>"
                f"<td style='color:{clr(sp)};font-weight:bold'>{fp(sp)}</td>"
                f"</tr>"
            )
        sectors_html = (
            "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
            "<tr style='background:#f3f4f6'><th>#</th><th>概念板块</th><th>涨跌幅</th></tr>"
            + sec_rows + "</table>"
        )
    else:
        sectors_html = "<p style='color:#9ca3af'>板块数据获取失败，仅展示关注池行情</p>"

    # ── Recommendation table ──
    def rec_row(r, is_new):
        sc = r['score']
        pct = r['pct'] or 0
        amt = r['amt'] or 0
        mni = r['main_net_inflow']
        tr  = r['turnover_rate'] or 0
        name = r['name']
        code_display = r['code'][2:]
        reason = '；'.join(r['reasons'][:3]) or '-'
        flag = '🆕' if is_new else '📌'
        return (
            f"<tr>"
            f"<td>{flag} <b>{name}</b></td>"
            f"<td style='font-family:monospace;color:#6b7280'>{code_display}</td>"
            f"<td style='font-weight:bold;color:{clr(pct)}'>{fp(pct)}</td>"
            f"<td style='color:#6b7280'>{fmt_amt(amt)}</td>"
            f"<td style='color:{'#16a34a' if (mni or 0)>=0 else '#dc2626'}'>{fmt_flow(mni)}</td>"
            f"<td style='color:#6b7280'>{tr:.1f}%</td>"
            f"<td style='color:#374151;font-size:12px'>{sc}分 | {reason}</td>"
            f"</tr>"
        )

    all_recs = [(r, False) for r in new_recs] + [(r, True) for r in watch_recs]
    if all_recs:
        rec_rows = ''.join(rec_row(r, is_new) for r, is_new in all_recs)
        rec_html = (
            "<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>"
            "<tr style='background:#fef9c3'>"
            "<th>股票</th><th>代码</th><th>涨跌幅</th><th>成交额</th>"
            "<th>主力净流入</th><th>换手率</th><th>评分 & 理由</th></tr>"
            + rec_rows + "</table>"
            "<p style='color:#9ca3af;font-size:12px;margin-top:6px'>"
            "🆕=全市场新发现 &nbsp; 📌=关注池加仓机会 &nbsp; "
            "⚠️ 评分仅供参考，不构成投资建议</p>"
        )
    else:
        rec_html = "<p style='color:#9ca3af'>今日推荐数据不足（候选池为空），请查看关注池行情</p>"

    # ── Watchlist stocks ──
    all_w = sorted(watchlist_hq.values(), key=lambda x: x['pct'], reverse=True)
    watch_rows = ''
    for d in all_w:
        info = stock_map.get(d['code']) or ('', '', '', '')
        prev_amt = vol_history.get(d['code'], {}).get('amt', 0)
        badge = vol_badge(d['amt'], prev_amt)
        watch_rows += (
            f"<tr>"
            f"<td>{d['name']}{limit_flag(d['pct'])}</td>"
            f"<td style='font-family:monospace;color:#6b7280'>{d['code'][2:]}</td>"
            f"<td style='color:#6b7280;font-size:12px'>{info[2]}</td>"
            f"<td style='font-weight:bold'>{d['cur']:.2f}</td>"
            f"<td style='color:{clr(d['pct'])};font-weight:bold'>{fp(d['pct'])}</td>"
            f"<td style='color:#6b7280'>{fmt_amt(d['amt'])}</td>"
            f"<td>{badge}</td>"
            f"</tr>"
        )

    # ── Limit alerts ──
    lus = [d for d in all_w if d['pct'] >= 9.9]
    lds = [d for d in all_w if d['pct'] <= -9.9]
    alert_html = ''
    if lus:
        alert_html += '<p>🚀 <b>涨停</b>：' + '、'.join(f"<b>{d['name']}</b>({d['code'][2:]})" for d in lus) + '</p>'
    if lds:
        alert_html += '<p>💀 <b>跌停</b>：' + '、'.join(f"<b>{d['name']}</b>({d['code'][2:]})" for d in lds) + '</p>'
    if not alert_html:
        alert_html = '<p style="color:#9ca3af">关注池内无涨跌停个股</p>'

    # ── Prediction box ──
    pred_factors_html = ''.join(
        f"<li style='margin:5px 0;font-size:14px'>{ic} {tx}</li>"
        for ic, tx in pred_reasons
    )
    pred_html = f"""
<div style='border:2px solid {pred_color};border-radius:10px;padding:18px;margin:8px 0;background:#fafafa'>
  <p style='margin:0 0 10px;font-size:16px'>
    预测结论：
    <span style='color:{pred_color};font-weight:bold;font-size:22px'>{pred_label}</span>
    <span style='color:#6b7280;font-size:13px;margin-left:10px'>置信度 {pred_conf}%（综合评分 {pred_score:+d}）</span>
  </p>
  <ul style='margin:0;padding-left:20px;line-height:2'>{pred_factors_html}</ul>
  <p style='margin:10px 0 0;font-size:13px;color:#6b7280'>⚠️ 预测基于量化模型，不构成投资建议。市场受多方因素影响，请结合自身判断操作。</p>
</div>"""

    # ── Trading style box ──
    ts_factors_html = ''.join(
        f"<li style='margin:5px 0;font-size:14px'>{ic} {tx}</li>"
        for ic, tx in ts_factors
    )
    style_html = f"""
<div style='border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin:8px 0;background:#f9fafb'>
  <p style='margin:0 0 8px;font-size:15px'>
    今日风格：
    <span style='color:{ts_color};font-weight:bold;font-size:20px'>{ts_style}</span>
    <span style='color:#6b7280;font-size:13px;margin-left:10px'>建议仓位：{ts_pos}</span>
  </p>
  <ul style='margin:0;padding-left:20px;line-height:1.9'>{ts_factors_html}</ul>
  <p style='margin:8px 0 0;font-size:14px'><b>操作方向：</b>{ts_desc}</p>
</div>"""

    # ── Tail-end guide (2 windows only) ──
    is_bull = ts_score >= 3
    is_bear = ts_score <= -3
    w1_action = ('量能持续则持仓，涨停未封者可轻仓参与；跌破午盘低点减半仓' if is_bull
                 else '强势反弹无量勿追，弱势继续则减仓' if is_bear
                 else '观察成交额变化方向，有量则跟，缩量则等')
    w2_action = ('最强板块维持涨势可持仓过夜；尾盘缩量阴线则止损出局' if is_bull
                 else '坚决清仓或轻仓，不冒过夜风险' if is_bear
                 else '缩量转阴则减仓；周五尾盘需额外谨慎，不留无把握仓位')

    tail_html = f"""
<table border='1' cellpadding='10' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'>
  <th style='width:22%'>时间窗口</th><th style='width:33%'>观察重点</th><th>操作建议</th>
</tr>
<tr>
  <td><b>14:00-14:30</b><br><span style='color:#9ca3af;font-size:11px'>午后行情</span></td>
  <td style='font-size:13px'>成交额是否持续放大 / 龙头个股是否维持强势</td>
  <td style='font-size:13px'>{w1_action}</td>
</tr>
<tr>
  <td><b>14:30-15:00</b><br><span style='color:#9ca3af;font-size:11px'>尾盘决策</span></td>
  <td style='font-size:13px'>尾盘量能方向 / 主力护盘意愿 / 过夜风险</td>
  <td style='font-size:13px'>{w2_action}</td>
</tr>
</table>"""

    return f"""<html><body style='font-family:Arial,sans-serif;max-width:800px;margin:0 auto;color:#111'>
<h2 style='color:#1d4ed8;border-bottom:2px solid #1d4ed8;padding-bottom:8px'>
  📊 A股AI板块午报 &middot; {today} 14:00
  <span style='font-size:13px;font-weight:normal;color:#6b7280;margin-left:12px'>盘中实时数据</span>
</h2>

<h3>📊 大盘指数</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>指数</th><th>现价</th><th>涨跌幅</th><th>今开</th><th>成交额</th><th>量能节奏</th></tr>
{idx_rows}</table>

<h3>🔥 今日热门概念板块 TOP10</h3>
{sectors_html}

<h3>⭐ 今日推荐股票</h3>
{rec_html}

<h3>🤖 关注池个股行情（共{len(all_w)}只）</h3>
<table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'>
<tr style='background:#f3f4f6'><th>股票</th><th>代码</th><th>板块</th><th>现价</th><th>涨跌幅</th><th>成交额</th><th>量变</th></tr>
{watch_rows}</table>

<h3>⚡ 涨跌停提示</h3>
{alert_html}

<h3>🔮 明日走势预测</h3>
{pred_html}

<h3>🧠 今日风格判断</h3>
{style_html}

<h3>⏰ 尾盘操作指南</h3>
{tail_html}

<hr style='margin-top:28px'>
<p style='color:#9ca3af;font-size:12px'>
  ⚠️ 仅供参考，不构成投资建议。股市有风险，入市需谨慎。<br>
  数据来源：新浪财经 + 东方财富 | 自动推送：北京时间 14:00
</p>
</body></html>"""

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    today = datetime.now().strftime('%Y-%m-%d')

    # 1. Volume history (read-only)
    vol_history, _ = gh_read_history()
    print(f'[main] history: {len(vol_history)} entries')

    # 2. Watchlist real-time (Sina HQ)
    all_codes = INDICES + [s[0] for s in WATCHLIST]
    hq = fetch_sina_hq(all_codes)
    idx_hq   = {c: hq[c] for c in INDICES if c in hq}
    watch_hq = {c: hq[c] for c in [s[0] for s in WATCHLIST] if c in hq}
    print(f'[main] HQ: {len(idx_hq)} indices, {len(watch_hq)} watchlist stocks')

    # 3. Discovery: candidates + hot sectors
    candidates, sectors_em, hot_sector_codes = build_candidate_pool()
    print(f'[main] candidates={len(candidates)}, sectors={len(sectors_em)}')

    # 4. Recommendations
    new_recs, watch_recs = generate_recommendations(
        candidates, vol_history, hot_sector_codes, watch_hq)
    print(f'[main] recs: {len(new_recs)} new + {len(watch_recs)} watchlist')

    # 5. Prediction
    pred_label, pred_color, pred_conf, pred_score, pred_reasons = predict_tomorrow(
        idx_hq, watch_hq, sectors_em, vol_history)
    print(f'[main] prediction: {pred_label} (score={pred_score})')

    # 6. Trading style
    ts_style, ts_color, ts_pos, ts_desc, ts_score, ts_factors = trading_style_score(
        idx_hq, watch_hq, vol_history)
    print(f'[main] style: {ts_style}')

    # 7. Build HTML
    html = build_pm_html(
        today, idx_hq, watch_hq, vol_history,
        new_recs, watch_recs, sectors_em,
        pred_label, pred_color, pred_conf, pred_score, pred_reasons,
        ts_style, ts_color, ts_pos, ts_desc, ts_score, ts_factors)

    # 8. Send email
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
