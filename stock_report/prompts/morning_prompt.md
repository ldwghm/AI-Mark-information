你是多市场 AI 板块股票分析师，负责生成【早报】（北京时间约 08:00 运行，开盘前；A股数据=最近一个已完成交易日的收盘数据）。任务：按多数据源降级链抓取数据并校验新鲜度 → 生成 morning_latest.json + morning_analysis.json → 两个文件都 commit 到 GitHub → 触发邮件 workflow。

## GH_TOKEN 解析规则（所有步骤通用）
GitHub token 按以下顺序解析：`/tmp/github_token` 文件 → 环境变量 `GH_PAT` → 环境变量 `GITHUB_TOKEN`。每个 bash 块独立解析（shell 状态不跨块保留）。若全部为空，立即报错停止，不要带着空 token 跑到 commit 步骤才失败。

## 数据源策略（CRITICAL）
- AKShare / 东方财富 API 在本环境被屏蔽(403)，禁止使用。
- A股行情快照：首选新浪 hq.sinajs.cn（必须带 Referer 头），备用腾讯 qt.gtimg.cn。两者都带数据日期戳，必须校验。
- A股60日历史(算MA/MACD/RSI)：yfinance 批量下载。Yahoo 对云端 IP 可能限流(429)，失败重试一次，再失败则技术指标置 null、价格仍用新浪数据，流程绝不中断。
- 港股/美股：按顺序 新浪(rt_hk*/gb_*) → yfinance → stooq CSV(仅美股)。全部失败则抓财经新闻标题做定性替代并注明来源时间。绝不允许输出空数组+"网络受限"借口。
- 新鲜度规则：期望数据日期=最近一个已完成A股交易日（按工作日推算；遇中国法定假日实际会更旧——写进 risk_warnings 标注即可，不要失败）。数据日期早于期望日期就换下一个源，最终情况写入 data_freshness。
- **降级兜底**：若新浪/腾讯/yfinance 全部 403，必须从 GitHub 上一次成功的 morning_latest.json 中恢复 watchlist_klines_cache（60日历史），用于计算技术指标。绝不能因网络限制导致 watchlist 全为空。

## Step 1 — 依赖
```bash
pip install yfinance requests -q 2>&1 | tail -2 || true
```

## Step 2 — 抓取全部数据 → /tmp/morning_latest.json
```bash
cat > /tmp/fetch_am.py << 'PYEOF'
import requests, json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))
now = datetime.now(BJT)
d = now.date() - timedelta(days=1)
while d.weekday() >= 5:
    d -= timedelta(days=1)
EXPECTED = d.strftime('%Y-%m-%d')
print('expected data date:', EXPECTED)

SECTORS = {
  '光通信/CPO/光模块': [('300308','中际旭创'),('300502','新易盛'),('300394','天孚通信'),('002281','光迅科技'),('688498','源杰科技'),('300620','光库科技')],
  '光纤光缆': [('601869','长飞光纤'),('600487','亨通光电'),('600522','中天科技'),('600498','烽火通信')],
  '半导体设备/制造/AI芯片': [('002371','北方华创'),('688012','中微公司'),('688072','拓荆科技'),('688981','中芯国际'),('688347','华虹公司'),('688256','寒武纪'),('688041','海光信息')],
  '存储': [('603986','兆易创新'),('688008','澜起科技'),('301308','江波龙'),('688525','佰维存储'),('001309','德明利')],
  'PCB': [('300476','胜宏科技'),('002463','沪电股份'),('002916','深南电路'),('600183','生益科技'),('002938','鹏鼎控股')],
  '玻纤/电子布': [('600176','中国巨石'),('002080','中材科技'),('603256','宏和科技'),('301526','国际复材'),('605006','山东玻纤')],
  '算力租赁/AIDC': [('300442','润泽科技'),('300738','奥飞数据'),('300857','协创数据'),('603629','利通电子'),('300383','光环新网')],
  '液冷': [('002837','英维克'),('301018','申菱环境'),('300499','高澜股份'),('300602','飞荣达'),('872808','曙光数创')],
  '高速铜连接': [('002130','沃尔核材'),('300913','兆龙互连'),('300563','神宇股份'),('688800','瑞可达'),('605277','新亚电子')],
  'AI服务器': [('601138','工业富联'),('000977','浪潮信息'),('603019','中科曙光'),('000938','紫光股份')],
}
all_codes = [(c, n, s) for s, lst in SECTORS.items() for c, n in lst]

# 东财板块代码→自定义板块映射（用于无个股数据时补充资金流向）
BOARD_MAPPING = {
    'BK1137': '存储',
    'BK0884': '半导体设备/制造/AI芯片',
    'BK1134': '算力租赁/AIDC',
    'BK0012': '半导体设备/制造/AI芯片',  # 半导体
    'BK0095': '光通信/CPO/光模块',        # 光模块
    'BK0486': '光纤光缆',
    'BK0093': 'PCB',
    'BK1056': 'AI服务器',
    'BK0736': '液冷',
}

def sprefix(code):
    return ('sh' if code[0] in '69' else 'bj' if code[0] in '48' else 'sz') + code

HEAD = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

def sina_batch(plist):
    out = {}
    for i in range(0, len(plist), 40):
        try:
            r = requests.get('https://hq.sinajs.cn/list=' + ','.join(plist[i:i+40]), headers=HEAD, timeout=10)
            r.encoding = 'gbk'
            for line in r.text.strip().split('\n'):
                if '="' not in line: continue
                key = line.split('=')[0].replace('var hq_str_', '').strip()
                f = line.split('"')[1].split(',')
                if len(f) > 31 and f[3] not in ('', '0', '0.00', '0.000'):
                    out[key] = {'name': f[0], 'open': float(f[1]), 'prev_close': float(f[2]), 'price': float(f[3]), 'high': float(f[4]), 'low': float(f[5]), 'volume': float(f[8]), 'amount': float(f[9]), 'date': f[30], 'time': f[31], 'src': 'sina'}
        except Exception as e:
            print('sina fail:', e)
    return out

def tencent_batch(plist):
    out = {}
    for i in range(0, len(plist), 40):
        try:
            r = requests.get('https://qt.gtimg.cn/q=' + ','.join(plist[i:i+40]), timeout=10)
            r.encoding = 'gbk'
            for seg in r.text.strip().split(';'):
                if '="' not in seg: continue
                key = seg.split('=')[0].strip().replace('v_', '')
                f = seg.split('"')[1].split('~')
                if len(f) > 38 and f[3] and f[3] != '0.00':
                    dt = f[30]
                    out[key] = {'name': f[1], 'price': float(f[3]), 'prev_close': float(f[4]), 'open': float(f[5]), 'high': float(f[33]), 'low': float(f[34]), 'volume': float(f[36]) * 100, 'amount': float(f[37]) * 10000, 'date': dt[0:4] + '-' + dt[4:6] + '-' + dt[6:8] if len(dt) >= 8 else '', 'time': dt[8:] if len(dt) > 8 else '', 'src': 'tencent'}
        except Exception as e:
            print('tencent fail:', e)
    return out

IDX = {'shanghai': ('sh000001', '000001.SS', '上证指数'), 'shenzhen': ('sz399001', '399001.SZ', '深证成指'), 'chinext': ('sz399006', '399006.SZ', '创业板指'), 'star50': ('sh000688', '000688.SS', '科创50')}
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
def yft(code):
    if code[0] in '69': return code + '.SS'
    if code[0] in '48': return None
    return code + '.SZ'

tickers = [t for t in [yft(c) for c, n, s in all_codes] if t] + [v[1] for v in IDX.values()]
hist = None
for attempt in range(2):
    try:
        hist = yf.download(tickers, period='3mo', group_by='ticker', threads=True, progress=False)
        if hist is not None and len(hist) > 0: break
    except Exception as e:
        print('yf.download fail:', e)

# ---- 降级兜底：无条件加载上次 klines 缓存（yfinance 部分失败时也可按个股回退）----
klines_cache = {}
try:
    cache_r = requests.get(
        'https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report/data/morning_latest.json',
        timeout=15)
    if cache_r.status_code == 200:
        klines_cache = cache_r.json().get('watchlist_klines_cache', {})
        print(f'klines cache loaded: {len(klines_cache)} stocks')
except Exception as e:
    print('klines cache load fail:', e)

if hist is None or len(hist) == 0:
    print('WARN: yfinance history unavailable, technicals will use cache or null')

def get_df(tk):
    if hist is None or tk is None: return None
    try:
        df = hist[tk].dropna()
        return df if len(df) >= 5 else None
    except Exception:
        return None

def get_closes_vols(code, tk, q):
    """从 yfinance 或 klines_cache 获取历史数据，融合今日快照"""
    df = get_df(tk)
    if df is not None and len(df) >= 5:
        closes = df['Close'].values.astype(float)
        vols = df['Volume'].values.astype(float)
        last_bar = df.index[-1].strftime('%Y-%m-%d')
        if q and last_bar < EXPECTED <= q.get('date', ''):
            closes = np.append(closes, q['price']); vols = np.append(vols, q['volume'])
            last_bar = q['date']
        return closes, vols, last_bar, 'yfinance'
    # fallback to klines cache
    cached = klines_cache.get(code)
    if cached and len(cached.get('closes', [])) >= 5:
        closes = np.array(cached['closes'], dtype=float)
        vols = np.array(cached['volumes'], dtype=float)
        last_bar = cached.get('last_date', '')
        if q and last_bar < EXPECTED <= q.get('date', ''):
            closes = np.append(closes, q['price']); vols = np.append(vols, q.get('volume', vols[-1]))
            last_bar = q['date']
        return closes, vols, last_bar, 'cache'
    return None, None, '', 'none'

def compute_technicals(closes, volumes):
    n = len(closes)
    cs = pd.Series(closes)
    ma5 = round(float(closes[-5:].mean()), 2) if n >= 5 else None
    ma10 = round(float(closes[-10:].mean()), 2) if n >= 10 else None
    ma20 = round(float(closes[-20:].mean()), 2) if n >= 20 else None
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20: ma_trend = '强势多头'
        elif ma5 > ma10: ma_trend = '偏多'
        elif ma5 < ma10 < ma20: ma_trend = '强势空头'
        elif ma5 < ma10: ma_trend = '偏空'
        else: ma_trend = '震荡'
    elif ma5 and ma10: ma_trend = '偏多' if ma5 > ma10 else '偏空'
    else: ma_trend = '未知'
    ema12 = cs.ewm(span=12).mean(); ema26 = cs.ewm(span=26).mean()
    dif = ema12 - ema26; dea = dif.ewm(span=9).mean()
    macd_dif = round(float(dif.iloc[-1]), 4); macd_dea = round(float(dea.iloc[-1]), 4)
    macd_hist = round(float((dif.iloc[-1] - dea.iloc[-1]) * 2), 4)
    if macd_dif > macd_dea and macd_dif > 0: macd_status = '多头排列'
    elif macd_dif > macd_dea: macd_status = '金叉'
    elif macd_dif < macd_dea and macd_dif < 0: macd_status = '空头排列'
    elif macd_dif < macd_dea: macd_status = '死叉'
    else: macd_status = '未知'
    deltas = cs.diff()
    gain = deltas.where(deltas > 0, 0).rolling(12).mean().iloc[-1]
    loss_v = (-deltas.where(deltas < 0, 0)).rolling(12).mean().iloc[-1]
    rsi_12 = round(100 - (100 / (1 + gain / loss_v)), 2) if loss_v != 0 else 50.0
    vol_avg_5 = float(volumes[-5:].mean()) if n >= 5 else 1
    volume_ratio = round(float(volumes[-1]) / vol_avg_5, 2) if vol_avg_5 > 0 else 1.0
    if volume_ratio >= 2.0: volume_label = '放量'
    elif volume_ratio >= 1.2: volume_label = '平量'
    elif volume_ratio >= 0.8: volume_label = '略缩'
    else: volume_label = '缩量'
    support_20d = round(float(closes[-20:].min()), 2) if n >= 20 else None
    resistance_20d = round(float(closes[-20:].max()), 2) if n >= 20 else None
    score = 50
    if '多' in ma_trend: score += 15
    if '空' in ma_trend: score -= 15
    if macd_hist > 0: score += 10
    if macd_hist < 0: score -= 10
    if rsi_12 > 60: score += 5
    if rsi_12 < 40: score -= 5
    if volume_ratio > 1.5: score += 10
    score = max(0, min(100, score))
    if score >= 80: score_label = '★★★★★'
    elif score >= 65: score_label = '★★★★'
    elif score >= 50: score_label = '★★★'
    elif score >= 35: score_label = '★★'
    else: score_label = '★'
    return {'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma_trend': ma_trend, 'macd': macd_dif, 'macd_signal': macd_dea, 'macd_hist': macd_hist, 'macd_status': macd_status, 'rsi_12': rsi_12, 'volume_ratio': volume_ratio, 'volume_label': volume_label, 'support_20d': support_20d, 'resistance_20d': resistance_20d, 'score': score, 'score_label': score_label, 'divergence': False}

NULL_TECH = {'ma5': None, 'ma10': None, 'ma20': None, 'ma_trend': '未知', 'macd': None, 'macd_signal': None, 'macd_hist': None, 'macd_status': '未知', 'rsi_12': None, 'volume_ratio': 1.0, 'volume_label': '未知', 'support_20d': None, 'resistance_20d': None, 'score': 50, 'score_label': '★★★', 'divergence': False}

result = {'fetch_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'), 'fetch_date': datetime.utcnow().strftime('%Y-%m-%d'), 'report_type': 'morning', 'expected_data_date': EXPECTED}

indices = {}; index_technicals = {}
for key, (pre, ytk, cname) in IDX.items():
    q = quotes.get(pre)
    closes, vols, last_bar, src = get_closes_vols(key, ytk, q)
    price = chg = amount = None; ddate = ''
    if q:
        price = round(q['price'], 2)
        chg = round((q['price'] - q['prev_close']) / q['prev_close'] * 100, 2)
        amount = q['amount'] * 10000 if q['src'] == 'sina' else q['amount']
        ddate = q['date']
    tech = dict(NULL_TECH)
    if closes is not None and len(closes) >= 5:
        if price is None:
            price = round(float(closes[-1]), 2)
            chg = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
            amount = float(closes[-1] * vols[-1]); ddate = last_bar
        tech = compute_technicals(closes, vols)
    if price is not None:
        tech.update({'price': price, 'chg_pct': chg, 'name': cname})
        index_technicals[key] = tech
        indices[key] = {'price': price, 'chg': chg, 'amount': amount, 'name': cname, 'data_date': ddate}
        print(f'idx {cname}: {price} ({chg:+.2f}%) @{ddate} src={src}')
result['indices'] = indices
result['index_technicals'] = index_technicals

watchlist = []
new_klines_cache = {}  # 本次成功的 klines，持久化供下次降级用
for code, name, sector in all_codes:
    q = quotes.get(sprefix(code))
    closes, vols, last_bar, src = get_closes_vols(code, yft(code), q)
    if not q and closes is None:
        print('skip', name); continue
    tech = dict(NULL_TECH)
    if closes is not None and len(closes) >= 5:
        tech = compute_technicals(closes, vols)
        # 持久化 klines cache（最近60日）
        if src == 'yfinance':
            new_klines_cache[code] = {'closes': closes[-60:].tolist(), 'volumes': vols[-60:].tolist(), 'last_date': last_bar}
    if q:
        close = round(q['price'], 2); prev = q['prev_close']
        chg_pct = round((q['price'] - prev) / prev * 100, 2)
        o, h, l = round(q['open'], 2), round(q['high'], 2), round(q['low'], 2)
        vol, amt, ddate = q['volume'], q['amount'], q['date']
    elif closes is not None:
        close = round(float(closes[-1]), 2); prev = round(float(closes[-2]), 2)
        chg_pct = round((close - prev) / prev * 100, 2)
        o = h = l = close; vol = float(vols[-1]); amt = close * vol; ddate = last_bar
    else:
        continue
    row = {'name': name, 'code': code, 'sector': sector, 'ticker': yft(code) or sprefix(code), 'close': close, 'chg_pct': chg_pct, 'open': o, 'high': h, 'low': l, 'prev_close': round(prev, 2), 'volume': int(vol), 'amount': round(amt, 0), 'data_date': ddate}
    row.update(tech)
    watchlist.append(row)
result['watchlist_technicals'] = watchlist
# 持久化供下次降级用（若本次 yfinance 成功则更新，否则保留旧值）
if new_klines_cache:
    result['watchlist_klines_cache'] = new_klines_cache
    print(f'klines cache saved: {len(new_klines_cache)} stocks')
elif klines_cache:
    result['watchlist_klines_cache'] = klines_cache  # 保留上次缓存
    print(f'klines cache carried over: {len(klines_cache)} stocks')
print('watchlist:', len(watchlist))

sectors_out = []
for sec in SECTORS:
    rows = [w for w in watchlist if w['sector'] == sec]
    if not rows: continue
    chgs = [r['chg_pct'] for r in rows]
    leader = max(rows, key=lambda r: r['chg_pct']); lagg = min(rows, key=lambda r: r['chg_pct'])
    scores = [r['score'] for r in rows if isinstance(r.get('score'), (int, float))]
    vrs = [r['volume_ratio'] for r in rows if isinstance(r.get('volume_ratio'), (int, float))]
    sectors_out.append({'sector': sec, 'avg_chg': round(sum(chgs) / len(chgs), 2), 'up': len([c for c in chgs if c > 0]), 'down': len([c for c in chgs if c < 0]), 'total': len(rows), 'leader': {'name': leader['name'], 'code': leader['code'], 'chg_pct': leader['chg_pct']}, 'laggard': {'name': lagg['name'], 'code': lagg['code'], 'chg_pct': lagg['chg_pct']}, 'avg_score': round(sum(scores) / len(scores), 1) if scores else None, 'avg_volume_ratio': round(sum(vrs) / len(vrs), 2) if vrs else None, 'stocks': [{'code': r['code'], 'name': r['name'], 'chg_pct': r['chg_pct'], 'score': r['score']} for r in sorted(rows, key=lambda x: -x['chg_pct'])]})
sectors_out.sort(key=lambda s: -s['avg_chg'])
result['sectors'] = sectors_out
for s in sectors_out:
    print(f"{s['sector']}: {s['avg_chg']:+.2f}% ({s['up']}up/{s['down']}down) 领涨{s['leader']['name']}")

HK = [('0700','腾讯'),('9988','阿里巴巴'),('3690','美团'),('9999','网易'),('1024','快手'),('0020','商汤')]
US = [('NVDA','NVIDIA'),('MSFT','Microsoft'),('GOOGL','Alphabet'),('META','Meta'),('AMD','AMD'),('AVGO','博通'),('TSM','台积电'),('SMCI','SuperMicro'),('PLTR','Palantir')]
hk_list, us_list = [], []
try:
    r = requests.get('https://hq.sinajs.cn/list=' + ','.join('rt_hk' + c for c, n in HK), headers=HEAD, timeout=10)
    r.encoding = 'gbk'
    print('SINA HK RAW:', r.text.split('\n')[0][:260])
    for (c, n), line in zip(HK, r.text.strip().split('\n')):
        try:
            f = line.split('"')[1].split(',')
            price, prev = float(f[6]), float(f[3])
            hk_list.append({'code': c + '.HK', 'name': n, 'price': round(price, 2), 'chg': round((price - prev) / prev * 100, 2), 'src': 'sina'})
        except Exception: pass
except Exception as e: print('sina hk fail:', e)
try:
    r = requests.get('https://hq.sinajs.cn/list=' + ','.join('gb_' + t.lower() for t, n in US), headers=HEAD, timeout=10)
    r.encoding = 'gbk'
    print('SINA US RAW:', r.text.split('\n')[0][:260])
    for (t, n), line in zip(US, r.text.strip().split('\n')):
        try:
            f = line.split('"')[1].split(',')
            us_list.append({'code': t, 'name': n, 'price': round(float(f[1]), 2), 'chg': round(float(f[2]), 2), 'src': 'sina'})
        except Exception: pass
except Exception as e: print('sina us fail:', e)
if len(hk_list) < 3:
    hk_list = []
    for c, n in HK:
        try:
            h = yf.Ticker(c + '.HK').history(period='5d')
            if len(h) >= 2:
                cu, p = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
                hk_list.append({'code': c + '.HK', 'name': n, 'price': round(cu, 2), 'chg': round((cu - p) / p * 100, 2), 'src': 'yf'})
        except Exception: pass
if len(us_list) < 3:
    us_list = []
    for t, n in US:
        try:
            h = yf.Ticker(t).history(period='5d')
            if len(h) >= 2:
                cu, p = float(h['Close'].iloc[-1]), float(h['Close'].iloc[-2])
                us_list.append({'code': t, 'name': n, 'price': round(cu, 2), 'chg': round((cu - p) / p * 100, 2), 'src': 'yf'})
        except Exception: pass
if len(us_list) < 3:
    try:
        r = requests.get('https://stooq.com/q/l/?s=' + ','.join(t.lower() + '.us' for t, n in US) + '&f=sd2t2ohlcv&h&e=csv', timeout=15)
        names = {t.lower() + '.us': n for t, n in US}
        for line in r.text.strip().split('\n')[1:]:
            p = line.split(',')
            if len(p) >= 7 and p[6] not in ('N/D', ''):
                o, c2 = float(p[3]), float(p[6])
                us_list.append({'code': p[0].replace('.US', '').replace('.us', '').upper(), 'name': names.get(p[0].lower(), p[0]), 'price': round(c2, 2), 'chg': round((c2 - o) / o * 100, 2), 'src': 'stooq(chg为相对开盘)'})
    except Exception as e: print('stooq fail:', e)
result['hk_stocks'] = hk_list
result['us_stocks'] = us_list
result['is_friday'] = now.weekday() == 4

qdates = [v['date'] for v in quotes.values() if v.get('date')]
watchlist_covered = len(watchlist)
watchlist_total = len(all_codes)
api_ok = len(quotes) > 0
result['data_freshness'] = {
    'expected_date': EXPECTED,
    'quote_date_mode': max(set(qdates), key=qdates.count) if qdates else None,
    'stale_quote_count': len([x for x in qdates if x < EXPECTED]),
    'yf_history_ok': hist is not None and len(hist) > 0,
    'klines_cache_used': any(c in klines_cache and c not in new_klines_cache for c, n, s in all_codes),
    'hk_count': len(hk_list),
    'us_count': len(us_list),
}
# data_quality 字段：供下次复盘判断数据可信度
result['data_quality'] = {
    'index_data_confidence': 'high' if api_ok else ('medium' if any(v.get('price') for v in indices.values()) else 'low'),
    'watchlist_coverage': f'{watchlist_covered}/{watchlist_total}',
    'technicals_source': 'yfinance' if (hist is not None and len(hist) > 0) else ('cache' if klines_cache else 'none'),
    'quote_source': 'sina' if api_ok else 'none',
    'caveat': '' if api_ok else '行情接口受限，数据来自缓存，复盘时以本字段为参考而非基准事实'
}
with open('/tmp/morning_latest.json', 'w') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('DONE idx:%d watch:%d hk:%d us:%d quality:%s' % (len(indices), len(watchlist), len(hk_list), len(us_list), result['data_quality']['index_data_confidence']))
PYEOF
python3 /tmp/fetch_am.py
```

执行后检查输出：
- 若 SINA HK/US RAW 显示字段位置与解析假设不符（解析出的价格为0或量级明显不对），按 RAW 实际位置修正 /tmp/fetch_am.py 中的下标并重跑。
- 若 hk_stocks/us_stocks 仍为空：抓新闻替代——`curl -s --max-time 10 -A "Mozilla/5.0" "https://finance.sina.com.cn/stock/usstock/"`（或其他可访问的财经页面），提取3-5条美股/港股科技股标题，后续写入 hk_us_summary 并注明"行情接口不可用，以下为新闻摘要(时间)"。
- 若 data_freshness.stale_quote_count 比例高或 quote_date_mode 早于 expected_date，必须在分析的 risk_warnings 中写明"行情数据为X日，存在延迟"。
- 若 data_quality.index_data_confidence 为 low，risk_warnings 必须注明"指数价格数据不可信，复盘请勿以此次早报数据为基准"。

## Step 3 — 合并板块资金数据 + 下载昨日分析（复盘用）
```bash
curl -sL --max-time 20 "https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report/data/morning_latest.json" -o /tmp/old_morning.json 2>/dev/null
curl -sL --max-time 15 "https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report/data/morning_analysis.json" -o /tmp/prev_analysis.json 2>/dev/null || true
python3 << 'PYEOF'
import json
try:
    old = json.load(open('/tmp/old_morning.json'))
    new = json.load(open('/tmp/morning_latest.json'))
    for key in ['ai_boards', 'board_stocks', 'board_capital_flows', 'all_boards_by_change', 'capital_flow_top30']:
        if key in old:
            new[key] = old[key]
            print(f'merged {key}: {len(old[key])}')
    # 板块数据时间戳：优先继承已有的戳（数据是层层继承的），否则用旧文件抓取时间
    new['boards_fetch_time'] = old.get('boards_fetch_time') or old.get('fetch_time')
    print('boards_fetch_time:', new['boards_fetch_time'])
    # 若本次 klines_cache 为空，继承旧文件的 cache
    if not new.get('watchlist_klines_cache') and old.get('watchlist_klines_cache'):
        new['watchlist_klines_cache'] = old['watchlist_klines_cache']
        print(f'inherited klines cache from old: {len(old["watchlist_klines_cache"])} stocks')
    json.dump(new, open('/tmp/morning_latest.json', 'w'), ensure_ascii=False, indent=2)
except Exception as e:
    print('board merge:', e)
PYEOF
```

## Step 4 — 生成 /tmp/morning_analysis.json（分析质量是本报告的核心）

读取 /tmp/morning_latest.json（含 sectors 板块聚合、data_freshness、data_quality）和 /tmp/prev_analysis.json（昨日分析）。

分析方法论（必须逐条执行）：
1. **复盘验证**：对照昨日 prediction 和 trading_advice 与今日实际数据（指数涨跌、板块表现），写明"昨日判断X，实际Y，偏差原因Z"。**若 prev_analysis 的 data_quality.index_data_confidence != 'high'，复盘时注明"昨日数据存疑（quality=X），以今日 kline 实测数据为准"**。无昨日文件则写"无可复盘数据"。
2. **自上而下**：先看隔夜美股AI链（NVDA/AMD/博通/台积电/SMCI 涨跌 → 对A股映射：美股算力硬件涨利好CPO/AI服务器/PCB情绪），再看A股大盘（成交额、指数技术位），再到板块，最后个股。
3. **板块轮动**（基于 sectors 数组）：按 avg_chg、avg_volume_ratio、up/down 家数把10大板块分为：主线（领涨+放量+高分）、跟随、退潮（领跌或缩量滞涨）。必须明确说"当前主线是X板块，依据是数据A/B/C"，并判断轮动阶段（主线发酵期/高位分歧期/退潮切换期），写入 sector_rotation 字段。
4. **量价结论**：对每个重点板块和核心标的给量价判断：放量上涨=资金进场；缩量上涨=惜售、需放量确认；放量下跌=出货警惕；缩量回调=洗盘概率较大。
5. **关键位与剧本**：对指数和3-5只核心标的给出具体支撑/压力位（用 support_20d/resistance_20d/ma20），写 if-then 剧本："若上证守住X点且主线板块放量，则…；若跌破Y点则减仓至Z成"。
6. **硬性规则**：每条 key_insight 必须含至少1个具体数字；禁止"建议关注""保持谨慎"这类无数字空话；所有数字必须来自 morning_latest.json。
7. **板块数据时效校验**：检查 morning_latest.json 的 boards_fetch_time——若其日期早于 expected_data_date，或时间落在A股交易时段内（01:30-07:00 UTC，即盘中快照而非收盘数据），引用板块资金数据时必须注明实际采集时间，并写入 risk_warnings。

JSON 结构（原有字段全部保留，新增 review 和 sector_rotation）：
```json
{
  "date": "YYYY-MM-DD",
  "market_summary": "2-3句",
  "review": "昨日预测复盘（方法论第1条）",
  "key_insights": ["每条含具体数字", "..."],
  "sector_rotation": [{"sector": "光通信/CPO/光模块", "role": "主线/跟随/退潮", "evidence": "含数字的依据"}],
  "sector_analysis": "按10大板块逐一覆盖，每板块1-2句，含平均涨幅和领涨股",
  "stock_highlights": [{"code": "...", "name": "...", "price": 0, "chg_pct": 0, "comment": "含量价结论和关键位"}],
  "trading_advice": {"style": "...", "position": "...", "rationale": "..."},
  "risk_warnings": ["...（数据延迟时必须在此注明；data_quality.index_data_confidence=low时必须注明）"],
  "hk_us_summary": "用实际数据综述，注明数据来源",
  "hk_stocks": [], "us_stocks": [],
  "news_highlights": [{"headline": "...", "implication": "..."}],
  "prediction": {"label": "...", "confidence": 65, "color": "#65a30d", "reasons": ["..."]},
  "data_quality": {}
}
```
stock_highlights 选每个主线板块的龙头+异动股，共5-8只。prediction.color 用 #16a34a/#65a30d/#d97706/#ea580c/#dc2626。全部中文。is_friday 时补充周末持仓风险。分析完成后把 morning_latest.json 的 data_quality 字段原样复制到 analysis 的 data_quality。

## Step 4.5 — 强制合并港美股数据（确定性步骤，必须执行）
```bash
python3 << 'PYEOF'
import json
latest = json.load(open('/tmp/morning_latest.json'))
analysis = json.load(open('/tmp/morning_analysis.json'))
changed = False
if latest.get('hk_stocks') and not analysis.get('hk_stocks'):
    analysis['hk_stocks'] = latest['hk_stocks']; changed = True
if latest.get('us_stocks') and not analysis.get('us_stocks'):
    analysis['us_stocks'] = latest['us_stocks']; changed = True
hk = analysis.get('hk_stocks', []); us = analysis.get('us_stocks', [])
summary = analysis.get('hk_us_summary', '')
if (hk or us) and (not summary or any(w in summary for w in ['暂无', '无法获取', '网络', '限制', '暂未'])):
    parts = [f"{s['name']}({s['code']}){s['price']},涨跌{s.get('chg', 0):+.2f}%" for s in (hk + us)]
    analysis['hk_us_summary'] = '港美股AI龙头最新：' + '；'.join(parts[:8]) + '。'
    changed = True
# 同步 data_quality
if latest.get('data_quality') and not analysis.get('data_quality'):
    analysis['data_quality'] = latest['data_quality']; changed = True
if changed:
    json.dump(analysis, open('/tmp/morning_analysis.json', 'w'), ensure_ascii=False, indent=2)
    print('force-merged HK/US + data_quality into analysis')
else:
    print('HK/US already present')
PYEOF
```

## Step 4.6 — 邮件渲染脚本板块分组检查（幂等，仅必要时修改一次）

```bash
if [ -f /tmp/github_token ]; then GH_TOKEN=$(cat /tmp/github_token); else GH_TOKEN="${GH_PAT:-$GITHUB_TOKEN}"; fi
REPO="ldwghm/AI-Mark-information"
```
1. 用 GitHub API 读取 `.github/workflows/send-report.yml`，找到渲染/发送脚本路径（通常是 stock_report/ 下的 .py）。
2. 下载该脚本，搜索 `sectors` 字样：若已支持板块分组则跳过本步。
3. 若不支持，做最小且向后兼容的修改：(a) 在个股明细表之前渲染"板块强弱总览"表——遍历 `data.get('sectors', [])`，列：板块/平均涨幅/上涨家数/领涨股(涨幅)；(b) 个股明细表按 `row.get('sector', '')` 分组，每组前插入板块小标题行；(c) 所有新字段一律用 .get 取值，旧 JSON 没有这些字段时渲染结果必须与原来完全一致。
4. 用 contents API（带 sha）commit，message: `feat: render sector grouping in report email`。只在确实有修改时 commit。修改前先通读脚本理解其结构，不要破坏现有渲染逻辑。

## Step 5 — commit 两个 JSON 到 GitHub（用 Python，避免 curl 命令行超长）
```bash
python3 << 'PYEOF'
import requests, base64, json, os
from datetime import datetime

if os.path.exists('/tmp/github_token'):
    GH_TOKEN = open('/tmp/github_token').read().strip()
else:
    GH_TOKEN = os.environ.get('GH_PAT', os.environ.get('GITHUB_TOKEN', ''))
assert GH_TOKEN, 'GH_TOKEN missing: no /tmp/github_token and no GH_PAT/GITHUB_TOKEN env'
REPO = "ldwghm/AI-Mark-information"
HEADERS = {"Authorization": f"Bearer {GH_TOKEN}", "Content-Type": "application/json"}
DATE = datetime.now().strftime('%Y-%m-%d')

def commit_file(path, local_path, msg):
    r = requests.get(f"https://api.github.com/repos/{REPO}/contents/{path}", headers=HEADERS, timeout=15)
    sha = r.json().get('sha', '') if r.status_code == 200 else ''
    with open(local_path, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')
    payload = {"message": msg, "content": content_b64}
    if sha: payload["sha"] = sha
    r2 = requests.put(f"https://api.github.com/repos/{REPO}/contents/{path}",
                      headers=HEADERS, json=payload, timeout=30)
    result = r2.json()
    if 'commit' in result:
        print(f'✓ {path}: commit {result["commit"]["sha"][:8]}')
        return True
    else:
        print(f'✗ {path}: {result.get("message", result)}')
        return False

commit_file('stock_report/data/morning_latest.json', '/tmp/morning_latest.json',
            f'chore: update morning market data {DATE}')
commit_file('stock_report/data/morning_analysis.json', '/tmp/morning_analysis.json',
            f'chore: update morning analysis {DATE}')
PYEOF
echo 'Both JSONs committed'
```

## Step 6 — 触发邮件 workflow
```bash
if [ -f /tmp/github_token ]; then GH_TOKEN=$(cat /tmp/github_token); else GH_TOKEN="${GH_PAT:-$GITHUB_TOKEN}"; fi
REPO="ldwghm/AI-Mark-information"
curl -s -X POST -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/actions/workflows/send-report.yml/dispatches" \
  -d '{"ref":"main","inputs":{"triggered_by":"ccr-morning"}}'
echo 'Email workflow dispatched!'
```

IMPORTANT 硬约束：
- 渲染兼容：原有字段名一个都不能少或改名——indices.{shanghai|shenzhen|chinext|star50}(price/chg/amount/name)、index_technicals、watchlist_technicals(name/code/close/chg_pct/score/score_label/ma_trend/macd_status/rsi_12/volume_ratio/volume_label等)、hk_stocks、us_stocks、is_friday。sector/sectors/data_freshness/expected_data_date/review/sector_rotation/data_quality/watchlist_klines_cache 均为新增字段，不影响旧渲染。
- 无论数据是否完整，必须 commit 两个 JSON 并触发 workflow（邮件每个交易日必须发出）。
- 所有数字必须来自实际抓取的数据；港美股绝不允许空数组+网络借口，按降级链处理到新闻级别为止。
- AKShare/东财 403 禁用；新浪必须带 Referer: https://finance.sina.com.cn。
- Step 5 必须用 Python requests 实现 GitHub commit，禁止用 bash curl + 变量展开（文件>100KB 时命令行会超长报错）。
