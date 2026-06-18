#!/usr/bin/env python3
"""统一 AI 板块行情抓取脚本（早报/午报共用，云端 routine 调用）。

Loop Engineering "抽公共脚本去重"：早报/午报原本各自内联 ~200 行几乎相同的抓取代码，
现在合并为本脚本一处维护。股票池放在同目录 sectors.json，改一处两个 routine 都生效。

用法:
    python3 cloud_fetch.py --mode morning
    python3 cloud_fetch.py --mode afternoon --merge-from /tmp/old_pm.json
    python3 cloud_fetch.py --mode morning --merge-from /tmp/old_morning.json --out /tmp/morning_latest.json

参数:
    --mode        morning | afternoon（必填）
    --merge-from  已 commit 的同名 latest.json（GitHub Actions efinance 数据），
                  合并其板块/资金流向键到本次输出（互补双路径，必须保留，否则邮件丢板块）。
    --out         输出路径，默认 /tmp/{mode}_latest.json

数据源策略（项目硬规则）:
    - AKShare / 东方财富 API 云端被屏蔽(403) —— 禁止使用。
    - A股行情:  新浪 hq.sinajs.cn(必须带 Referer) -> 腾讯 qt.gtimg.cn 备用。带日期戳，校验新鲜度。
    - A股60日历史(MA/MACD/RSI): yfinance，限流(429)重试一次；再失败则用 --merge-from 里的
      watchlist_klines_cache 兜底；都没有则技术指标置 null、价格仍用新浪，绝不中断。
    - 港/美股: 新浪(rt_hk*/gb_*) -> yfinance -> stooq CSV(仅美股)。绝不输出空数组+网络借口。

输出字段与原 fetch_am.py/fetch_pm.py 完全一致；额外 sectors/data_freshness/data_quality/
watchlist_klines_cache 均为新增，用 .get 读取，不影响旧渲染。
"""
import argparse
import json
import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BJT = timezone(timedelta(hours=8))
HEAD = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

# --merge-from 时按 mode 合并的板块/资金流向键（与线上 routine 行为逐字一致）
MERGE_KEYS = {
    'morning': ['ai_boards', 'board_stocks', 'board_capital_flows',
                'all_boards_by_change', 'capital_flow_top30'],
    'afternoon': ['ai_boards', 'ai_boards_rt', 'board_stocks', 'board_stocks_rt',
                  'board_capital_flows', 'capital_flow_top30', 'capital_flow_top30_rt',
                  'all_boards_by_change'],
}


def load_universe():
    """读取 sectors.json（本脚本同目录；云端 curl 到 /tmp 时也兼容）。"""
    for p in (os.path.join(HERE, 'sectors.json'), '/tmp/sectors.json'):
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8-sig'))
    raise SystemExit('sectors.json not found (放 cloud_fetch.py 同目录，或 curl 到 /tmp/sectors.json)')


def sprefix(code):
    return ('sh' if code[0] in '69' else 'bj' if code[0] in '48' else 'sz') + code


def yft(code):
    if code[0] in '69':
        return code + '.SS'
    if code[0] in '48':
        return None
    return code + '.SZ'


def sina_batch(plist):
    out = {}
    for i in range(0, len(plist), 40):
        try:
            r = requests.get('https://hq.sinajs.cn/list=' + ','.join(plist[i:i + 40]), headers=HEAD, timeout=10)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\n'):
                if '="' not in line:
                    continue
                key = line.split('=')[0].replace('var hq_str_', '').strip()
                f = line.split('"')[1].split(',')
                if len(f) > 31 and f[3] not in ('', '0', '0.00', '0.000'):
                    out[key] = {'name': f[0], 'open': float(f[1]), 'prev_close': float(f[2]), 'price': float(f[3]),
                                'high': float(f[4]), 'low': float(f[5]), 'volume': float(f[8]), 'amount': float(f[9]),
                                'date': f[30], 'time': f[31], 'src': 'sina'}
        except Exception as e:
            print('sina fail:', e)
    return out


def tencent_batch(plist):
    out = {}
    for i in range(0, len(plist), 40):
        try:
            r = requests.get('https://qt.gtimg.cn/q=' + ','.join(plist[i:i + 40]), timeout=10)
            r.encoding = 'gbk'
            for seg in r.text.strip().split(';'):
                if '="' not in seg:
                    continue
                key = seg.split('=')[0].strip().replace('v_', '')
                f = seg.split('"')[1].split('~')
                if len(f) > 38 and f[3] and f[3] != '0.00':
                    dt = f[30]
                    out[key] = {'name': f[1], 'price': float(f[3]), 'prev_close': float(f[4]), 'open': float(f[5]),
                                'high': float(f[33]), 'low': float(f[34]), 'volume': float(f[36]) * 100,
                                'amount': float(f[37]) * 10000,
                                'date': dt[0:4] + '-' + dt[4:6] + '-' + dt[6:8] if len(dt) >= 8 else '',
                                'time': dt[8:] if len(dt) > 8 else '', 'src': 'tencent'}
        except Exception as e:
            print('tencent fail:', e)
    return out


def compute_technicals(closes, volumes):
    n = len(closes)
    cs = pd.Series(closes)
    ma5 = round(float(closes[-5:].mean()), 2) if n >= 5 else None
    ma10 = round(float(closes[-10:].mean()), 2) if n >= 10 else None
    ma20 = round(float(closes[-20:].mean()), 2) if n >= 20 else None
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            ma_trend = '强势多头'
        elif ma5 > ma10:
            ma_trend = '偏多'
        elif ma5 < ma10 < ma20:
            ma_trend = '强势空头'
        elif ma5 < ma10:
            ma_trend = '偏空'
        else:
            ma_trend = '震荡'
    elif ma5 and ma10:
        ma_trend = '偏多' if ma5 > ma10 else '偏空'
    else:
        ma_trend = '未知'
    ema12 = cs.ewm(span=12).mean()
    ema26 = cs.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    macd_dif = round(float(dif.iloc[-1]), 4)
    macd_dea = round(float(dea.iloc[-1]), 4)
    macd_hist = round(float((dif.iloc[-1] - dea.iloc[-1]) * 2), 4)
    if macd_dif > macd_dea and macd_dif > 0:
        macd_status = '多头排列'
    elif macd_dif > macd_dea:
        macd_status = '金叉'
    elif macd_dif < macd_dea and macd_dif < 0:
        macd_status = '空头排列'
    elif macd_dif < macd_dea:
        macd_status = '死叉'
    else:
        macd_status = '未知'
    deltas = cs.diff()
    gain = deltas.where(deltas > 0, 0).rolling(12).mean().iloc[-1]
    loss_v = (-deltas.where(deltas < 0, 0)).rolling(12).mean().iloc[-1]
    rsi_12 = round(100 - (100 / (1 + gain / loss_v)), 2) if loss_v != 0 else 50.0
    vol_avg_5 = float(volumes[-5:].mean()) if n >= 5 else 1
    volume_ratio = round(float(volumes[-1]) / vol_avg_5, 2) if vol_avg_5 > 0 else 1.0
    if volume_ratio >= 2.0:
        volume_label = '放量'
    elif volume_ratio >= 1.2:
        volume_label = '平量'
    elif volume_ratio >= 0.8:
        volume_label = '略缩'
    else:
        volume_label = '缩量'
    support_20d = round(float(closes[-20:].min()), 2) if n >= 20 else None
    resistance_20d = round(float(closes[-20:].max()), 2) if n >= 20 else None
    score = 50
    if '多' in ma_trend:
        score += 15
    if '空' in ma_trend:
        score -= 15
    if macd_hist > 0:
        score += 10
    if macd_hist < 0:
        score -= 10
    if rsi_12 > 60:
        score += 5
    if rsi_12 < 40:
        score -= 5
    if volume_ratio > 1.5:
        score += 10
    score = max(0, min(100, score))
    if score >= 80:
        score_label = '★★★★★'
    elif score >= 65:
        score_label = '★★★★'
    elif score >= 50:
        score_label = '★★★'
    elif score >= 35:
        score_label = '★★'
    else:
        score_label = '★'
    return {'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma_trend': ma_trend, 'macd': macd_dif,
            'macd_signal': macd_dea, 'macd_hist': macd_hist, 'macd_status': macd_status, 'rsi_12': rsi_12,
            'volume_ratio': volume_ratio, 'volume_label': volume_label, 'support_20d': support_20d,
            'resistance_20d': resistance_20d, 'score': score, 'score_label': score_label, 'divergence': False}


NULL_TECH = {'ma5': None, 'ma10': None, 'ma20': None, 'ma_trend': '未知', 'macd': None, 'macd_signal': None,
             'macd_hist': None, 'macd_status': '未知', 'rsi_12': None, 'volume_ratio': 1.0, 'volume_label': '未知',
             'support_20d': None, 'resistance_20d': None, 'score': 50, 'score_label': '★★★', 'divergence': False}


def closes_vols(df, q, expected, cache_entry):
    """统一历史序列来源：yfinance -> klines_cache 兜底 -> None。融合今日快照。
    返回 (closes, vols, last_bar, src)。"""
    if df is not None and len(df) >= 5:
        closes = df['Close'].values.astype(float)
        vols = df['Volume'].values.astype(float)
        last_bar = df.index[-1].strftime('%Y-%m-%d')
        src = 'yfinance'
    elif cache_entry and len(cache_entry.get('closes', [])) >= 5:
        closes = np.array(cache_entry['closes'], dtype=float)
        vols = np.array(cache_entry['volumes'], dtype=float)
        last_bar = cache_entry.get('last_date', '')
        src = 'cache'
    else:
        return None, None, '', 'none'
    if q and last_bar < expected <= q.get('date', ''):
        closes = np.append(closes, q['price'])
        vols = np.append(vols, q.get('volume', vols[-1]))
        last_bar = q['date']
    return closes, vols, last_bar, src


def fetch_hk_us(uni, yf):
    HK = [tuple(x) for x in uni['hk']]
    US = [tuple(x) for x in uni['us']]
    hk_list, us_list = [], []
    try:
        r = requests.get('https://hq.sinajs.cn/list=' + ','.join('rt_hk' + c for c, n in HK), headers=HEAD, timeout=10)
        r.encoding = 'gbk'
        print('SINA HK RAW:', r.text.split('\n')[0][:260])
        for (c, n), line in zip(HK, r.text.strip().split('\n')):
            try:
                f = line.split('"')[1].split(',')
                price, prev = float(f[6]), float(f[3])
                hk_list.append({'code': c + '.HK', 'name': n, 'price': round(price, 2),
                                'chg': round((price - prev) / prev * 100, 2), 'src': 'sina'})
            except Exception:
                pass
    except Exception as e:
        print('sina hk fail:', e)
    try:
        r = requests.get('https://hq.sinajs.cn/list=' + ','.join('gb_' + t.lower() for t, n in US), headers=HEAD, timeout=10)
        r.encoding = 'gbk'
        print('SINA US RAW:', r.text.split('\n')[0][:260])
        for (t, n), line in zip(US, r.text.strip().split('\n')):
            try:
                f = line.split('"')[1].split(',')
                us_list.append({'code': t, 'name': n, 'price': round(float(f[1]), 2),
                                'chg': round(float(f[2]), 2), 'src': 'sina'})
            except Exception:
                pass
    except Exception as e:
        print('sina us fail:', e)
    if len(hk_list) < 3:
        hk_list = []
        for c, n in HK:
            try:
                h = yf.Ticker(c + '.HK').history(period='5d')
                if len(h) >= 2:
                    cu, p = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
                    hk_list.append({'code': c + '.HK', 'name': n, 'price': round(cu, 2),
                                    'chg': round((cu - p) / p * 100, 2), 'src': 'yf'})
            except Exception:
                pass
    if len(us_list) < 3:
        us_list = []
        for t, n in US:
            try:
                h = yf.Ticker(t).history(period='5d')
                if len(h) >= 2:
                    cu, p = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
                    us_list.append({'code': t, 'name': n, 'price': round(cu, 2),
                                    'chg': round((cu - p) / p * 100, 2), 'src': 'yf'})
            except Exception:
                pass
    if len(us_list) < 3:
        try:
            r = requests.get('https://stooq.com/q/l/?s=' + ','.join(t.lower() + '.us' for t, n in US) + '&f=sd2t2ohlcv&h&e=csv', timeout=15)
            names = {t.lower() + '.us': n for t, n in US}
            for line in r.text.strip().split('\n')[1:]:
                p = line.split(',')
                if len(p) >= 7 and p[6] not in ('N/D', ''):
                    o, c2 = float(p[3]), float(p[6])
                    us_list.append({'code': p[0].replace('.US', '').replace('.us', '').upper(),
                                    'name': names.get(p[0].lower(), p[0]), 'price': round(c2, 2),
                                    'chg': round((c2 - o) / o * 100, 2), 'src': 'stooq(chg为相对开盘)'})
        except Exception as e:
            print('stooq fail:', e)
    return hk_list, us_list


def aggregate_sectors(tech_rows, sector_names):
    out = []
    for sec in sector_names:
        rows = [w for w in tech_rows if w['sector'] == sec]
        if not rows:
            continue
        chgs = [r['chg_pct'] for r in rows]
        leader = max(rows, key=lambda r: r['chg_pct'])
        lagg = min(rows, key=lambda r: r['chg_pct'])
        scores = [r['score'] for r in rows if isinstance(r.get('score'), (int, float))]
        vrs = [r['volume_ratio'] for r in rows if isinstance(r.get('volume_ratio'), (int, float))]
        out.append({'sector': sec, 'avg_chg': round(sum(chgs) / len(chgs), 2),
                    'up': len([c for c in chgs if c > 0]), 'down': len([c for c in chgs if c < 0]),
                    'total': len(rows),
                    'leader': {'name': leader['name'], 'code': leader['code'], 'chg_pct': leader['chg_pct']},
                    'laggard': {'name': lagg['name'], 'code': lagg['code'], 'chg_pct': lagg['chg_pct']},
                    'avg_score': round(sum(scores) / len(scores), 1) if scores else None,
                    'avg_volume_ratio': round(sum(vrs) / len(vrs), 2) if vrs else None,
                    'stocks': [{'code': r['code'], 'name': r['name'], 'chg_pct': r['chg_pct'], 'score': r['score']}
                               for r in sorted(rows, key=lambda x: -x['chg_pct'])]})
    out.sort(key=lambda s: -s['avg_chg'])
    return out


def apply_merge(result, merge_from, mode):
    """合并 efinance 板块/资金流向键（互补双路径）+ 继承 klines 缓存。"""
    if not merge_from or not os.path.exists(merge_from):
        print('merge skipped (no --merge-from file)')
        return
    try:
        old = json.load(open(merge_from, encoding='utf-8-sig'))
    except Exception as e:
        print('merge load fail:', e)
        return
    for key in MERGE_KEYS[mode]:
        if key in old:
            result[key] = old[key]
            try:
                print(f'merged {key}: {len(old[key])}')
            except Exception:
                print(f'merged {key}')
    result['boards_fetch_time'] = old.get('boards_fetch_time') or old.get('fetch_time')
    print('boards_fetch_time:', result.get('boards_fetch_time'))
    if not result.get('watchlist_klines_cache') and old.get('watchlist_klines_cache'):
        result['watchlist_klines_cache'] = old['watchlist_klines_cache']
        print(f'inherited klines cache: {len(old["watchlist_klines_cache"])} stocks')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['morning', 'afternoon'])
    ap.add_argument('--merge-from', dest='merge_from', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    mode = args.mode
    out_path = args.out or f'/tmp/{mode}_latest.json'

    uni = load_universe()
    SECTORS = {k: [tuple(x) for x in v] for k, v in uni['sectors'].items()}
    all_codes = [(c, n, s) for s, lst in SECTORS.items() for c, n in lst]

    now = datetime.now(BJT)
    d = (now.date() - timedelta(days=1)) if mode == 'morning' else now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    EXPECTED = d.strftime('%Y-%m-%d')
    print('mode:', mode, '| expected data date:', EXPECTED)

    # klines 缓存（yfinance 失败时兜底），从 --merge-from 文件预读
    klines_cache = {}
    if args.merge_from and os.path.exists(args.merge_from):
        try:
            klines_cache = json.load(open(args.merge_from, encoding='utf-8-sig')).get('watchlist_klines_cache', {})
            if klines_cache:
                print(f'klines cache preloaded: {len(klines_cache)} stocks')
        except Exception:
            pass

    IDX = {'shanghai': ('sh000001', '000001.SS', '上证指数'),
           'shenzhen': ('sz399001', '399001.SZ', '深证成指'),
           'chinext': ('sz399006', '399006.SZ', '创业板指'),
           'star50': ('sh000688', '000688.SS', '科创50')}
    idx_pre = [v[0] for v in IDX.values()]
    stock_pre = [sprefix(c) for c, n, s in all_codes]

    quotes = sina_batch(idx_pre + stock_pre)
    fresh_n = len([1 for v in quotes.values() if v['date'] >= EXPECTED])
    print(f'sina: {len(quotes)} quotes / {fresh_n} fresh')
    if fresh_n < len(idx_pre + stock_pre) * 0.6:
        tq = tencent_batch(idx_pre + stock_pre)
        for k, v in tq.items():
            if k not in quotes or v.get('date', '') > quotes[k].get('date', ''):
                quotes[k] = v
        print('after tencent merge:', len(quotes))

    import yfinance as yf
    tickers = [t for t in [yft(c) for c, n, s in all_codes] if t] + [v[1] for v in IDX.values()]
    hist = None
    for attempt in range(2):
        try:
            hist = yf.download(tickers, period='3mo', group_by='ticker', threads=True, progress=False)
            if hist is not None and len(hist) > 0:
                break
        except Exception as e:
            print('yf.download fail:', e)
    if hist is None or len(hist) == 0:
        print('WARN: yfinance history unavailable, technicals use cache or null')

    def get_df(tk):
        if hist is None or tk is None:
            return None
        try:
            df = hist[tk].dropna()
            return df if len(df) >= 5 else None
        except Exception:
            return None

    result = {'fetch_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
              'fetch_date': datetime.utcnow().strftime('%Y-%m-%d'),
              'report_type': mode, 'expected_data_date': EXPECTED}

    # ---- 指数 ----
    indices = {}
    realtime_indices = {}
    index_technicals = {}
    for key, (pre, ytk, cname) in IDX.items():
        q = quotes.get(pre)
        closes, vols, last_bar, src = closes_vols(get_df(ytk), q, EXPECTED, None)
        price = chg = amount = None
        ddate = ''
        if q:
            price = round(q['price'], 2)
            chg = round((q['price'] - q['prev_close']) / q['prev_close'] * 100, 2)
            amount = q['amount'] * 10000 if q['src'] == 'sina' else q['amount']
            ddate = q['date']
        tech = dict(NULL_TECH)
        if closes is not None:
            if price is None:
                price = round(float(closes[-1]), 2)
                chg = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                amount = float(closes[-1] * vols[-1])
                ddate = last_bar
            tech = compute_technicals(closes, vols)
        if price is not None:
            tech.update({'price': price, 'chg_pct': chg, 'name': cname})
            index_technicals[key] = tech
            indices[key] = {'price': price, 'chg': chg, 'amount': amount, 'name': cname, 'data_date': ddate}
            realtime_indices[pre] = {'price': price, 'current': price, 'chg': chg, 'change_pct': chg,
                                     'name': cname, 'data_date': ddate}
            print(f'idx {cname}: {price} ({chg:+.2f}%) @{ddate} src={src}')
    if mode == 'morning':
        result['indices'] = indices
    else:
        result['realtime_indices'] = realtime_indices
    result['index_technicals'] = index_technicals

    # ---- 自选股 ----
    watchlist_rt = []
    watchlist_tech = []
    new_cache = {}
    for code, name, sector in all_codes:
        q = quotes.get(sprefix(code))
        closes, vols, last_bar, src = closes_vols(get_df(yft(code)), q, EXPECTED, klines_cache.get(code))
        if not q and closes is None:
            print('skip', name)
            continue
        tech = dict(NULL_TECH)
        if closes is not None:
            tech = compute_technicals(closes, vols)
            if src == 'yfinance':
                new_cache[code] = {'closes': closes[-60:].tolist(), 'volumes': vols[-60:].tolist(), 'last_date': last_bar}
        if q:
            close = round(q['price'], 2)
            prev = q['prev_close']
            chg_pct = round((q['price'] - prev) / prev * 100, 2)
            o, h, l = round(q['open'], 2), round(q['high'], 2), round(q['low'], 2)
            vol, amt, ddate = q['volume'], q['amount'], q['date']
        else:
            close = round(float(closes[-1]), 2)
            prev = round(float(closes[-2]), 2)
            chg_pct = round((close - prev) / prev * 100, 2)
            o = h = l = close
            vol = float(vols[-1])
            amt = close * vol
            ddate = last_bar
        watchlist_rt.append({'name': name, 'code': code, 'sector': sector, 'current': close, 'change_pct': chg_pct,
                             'high': h, 'low': l, 'volume': int(vol), 'data_date': ddate})
        row = {'name': name, 'code': code, 'sector': sector, 'ticker': yft(code) or sprefix(code),
               'close': close, 'chg_pct': chg_pct, 'open': o, 'high': h, 'low': l,
               'prev_close': round(prev, 2), 'volume': int(vol), 'amount': round(amt, 0), 'data_date': ddate}
        row.update(tech)
        watchlist_tech.append(row)
    result['watchlist_technicals'] = watchlist_tech
    if mode == 'afternoon':
        result['watchlist_rt'] = watchlist_rt
    if new_cache:
        result['watchlist_klines_cache'] = new_cache
    elif klines_cache:
        result['watchlist_klines_cache'] = klines_cache
    print('watchlist:', len(watchlist_tech))

    # ---- 板块聚合 ----
    result['sectors'] = aggregate_sectors(watchlist_tech, SECTORS.keys())
    for s in result['sectors']:
        print(f"{s['sector']}: {s['avg_chg']:+.2f}% ({s['up']}up/{s['down']}down) 领涨{s['leader']['name']}")

    # ---- 港美股 ----
    hk_list, us_list = fetch_hk_us(uni, yf)
    result['hk_stocks'] = hk_list
    result['us_stocks'] = us_list
    result['is_friday'] = now.weekday() == 4

    qdates = [v['date'] for v in quotes.values() if v.get('date')]
    api_ok = len(quotes) > 0
    result['data_freshness'] = {'expected_date': EXPECTED,
                                'quote_date_mode': max(set(qdates), key=qdates.count) if qdates else None,
                                'stale_quote_count': len([x for x in qdates if x < EXPECTED]),
                                'yf_history_ok': hist is not None and len(hist) > 0,
                                'hk_count': len(hk_list), 'us_count': len(us_list)}
    result['data_quality'] = {
        'index_data_confidence': 'high' if api_ok else ('medium' if index_technicals else 'low'),
        'watchlist_coverage': f'{len(watchlist_tech)}/{len(all_codes)}',
        'technicals_source': 'yfinance' if (hist is not None and len(hist) > 0) else ('cache' if klines_cache else 'none'),
        'quote_source': 'sina/tencent' if api_ok else 'none',
        'caveat': '' if api_ok else '行情接口受限，数据来自缓存，复盘以本字段为参考而非基准事实'}

    # ---- 合并 efinance 板块数据（互补双路径，必须在写盘前）----
    apply_merge(result, args.merge_from, mode)

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print('DONE %s idx:%d watch:%d hk:%d us:%d quality:%s -> %s' % (
        mode, len(index_technicals), len(watchlist_tech), len(hk_list), len(us_list),
        result['data_quality']['index_data_confidence'], out_path))


if __name__ == '__main__':
    main()
