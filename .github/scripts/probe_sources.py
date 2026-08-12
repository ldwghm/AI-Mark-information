#!/usr/bin/env python3
"""从 GitHub Actions runner 探测各行情源的可达性与一致性。

一次性诊断脚本，不参与生产链路。回答一个具体问题：给 A 股快照配第二
数据源，在 **Actions 上** 哪些源真能用、报的数字和东方财富对不对得上。

判据不只是"能连上"。一个包装了东方财富的源（AKShare 就是）即使能通，
拿它和东方财富对账也证明不了任何事——必须是独立的行情通道。
"""
import json
import sys
import time

import requests

# 三只有代表性的：主板、创业板、科创板
TARGETS = [
    ('600522', '中天科技', 'sh600522', 's_sh600522', '1.600522'),
    ('300308', '中际旭创', 'sz300308', 's_sz300308', '0.300308'),
    ('688012', '中微公司', 'sh688012', 's_sh688012', '1.688012'),
]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0'}


def timed(fn):
    start = time.time()
    try:
        return fn(), None, round((time.time() - start) * 1000)
    except Exception as exc:
        return None, f'{type(exc).__name__}: {exc}'[:160], round((time.time() - start) * 1000)


def probe_eastmoney():
    """基线：生产环境现在就在用这条。"""
    out = {}
    for code, name, _, _, secid in TARGETS:
        r = requests.get('https://push2.eastmoney.com/api/qt/stock/get',
                         params={'secid': secid, 'fields': 'f43,f58,f60,f169,f170',
                                 'ut': 'bd1d9ddb04089700cf9c27f6f7426281'},
                         headers=UA, timeout=15)
        r.raise_for_status()
        d = (r.json() or {}).get('data') or {}
        if d.get('f43'):
            out[code] = {'price': d['f43'] / 100, 'chg_pct': d.get('f170', 0) / 100}
    return out


def probe_sina():
    codes = ','.join(t[2] for t in TARGETS)
    r = requests.get(f'https://hq.sinajs.cn/list={codes}',
                     headers={**UA, 'Referer': 'https://finance.sina.com.cn'}, timeout=15)
    r.raise_for_status()
    r.encoding = 'gbk'
    out = {}
    for line, (code, *_rest) in zip(r.text.strip().split('\n'), TARGETS):
        f = line.split('"')[1].split(',') if '="' in line else []
        if len(f) > 31 and f[3] not in ('', '0', '0.00'):
            prev = float(f[2])
            out[code] = {'price': float(f[3]),
                         'chg_pct': round((float(f[3]) - prev) / prev * 100, 2) if prev else None,
                         'as_of': f'{f[30]}T{f[31]}'}
    return out


def probe_tencent():
    codes = ','.join(t[2] for t in TARGETS)
    r = requests.get(f'https://qt.gtimg.cn/q={codes}', headers=UA, timeout=15)
    r.raise_for_status()
    r.encoding = 'gbk'
    out = {}
    for seg in r.text.strip().split(';'):
        if '="' not in seg:
            continue
        f = seg.split('"')[1].split('~')
        if len(f) > 38 and f[3] and f[3] != '0.00':
            out[f[2]] = {'price': float(f[3]), 'chg_pct': float(f[32]), 'as_of': f[30]}
    return out


def probe_netease():
    """网易财经，独立于东财/新浪/腾讯的第四条通道。"""
    codes = ','.join(('0' if t[0].startswith('6') else '1') + t[0] for t in TARGETS)
    r = requests.get(f'https://api.money.126.net/data/feed/{codes},money.api',
                     headers=UA, timeout=15)
    r.raise_for_status()
    body = r.text.strip()
    payload = json.loads(body[body.index('(') + 1:body.rindex(')')])
    out = {}
    for key, row in payload.items():
        out[str(row.get('symbol') or key[1:])] = {
            'price': row.get('price'),
            'chg_pct': round((row.get('percent') or 0) * 100, 2),
            'as_of': row.get('time')}
    return out


def probe_mootdx():
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')
    out = {}
    for code, *_rest in TARGETS:
        df = client.quotes(symbol=code)
        if df is not None and len(df):
            row = df.iloc[0]
            out[code] = {'price': float(row['price']),
                         'chg_pct': round((float(row['price']) - float(row['last_close']))
                                          / float(row['last_close']) * 100, 2)}
    return out


PROBES = (('eastmoney (push2, 现用基线)', probe_eastmoney, True),
          ('sina (hq.sinajs.cn)', probe_sina, True),
          ('tencent (qt.gtimg.cn)', probe_tencent, True),
          ('netease (api.money.126.net)', probe_netease, True),
          ('mootdx (通达信协议)', probe_mootdx, False))


def main():
    print('## 行情源可达性探测（GitHub Actions runner）\n')
    print(f'探测时间 UTC: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}\n')
    results = {}
    print('| 源 | 结果 | 耗时 | 拿到 | 备注 |')
    print('|---|---|---|---|---|')
    for label, fn, required in PROBES:
        data, err, ms = timed(fn)
        if err:
            print(f'| {label} | ❌ | {ms}ms | 0 | `{err}` |')
            continue
        results[label] = data or {}
        print(f'| {label} | ✅ | {ms}ms | {len(data or {})}/{len(TARGETS)} | |')

    baseline_key = next((k for k in results if k.startswith('eastmoney')), None)
    if not baseline_key:
        print('\n**东财基线都没通，本次探测无法判断一致性。**')
        return 1
    base = results[baseline_key]

    print('\n### 与东财基线的价格一致性\n')
    print('| 源 | 标的 | 东财 | 该源 | 差异% |')
    print('|---|---|---|---|---|')
    for label, data in results.items():
        if label == baseline_key:
            continue
        for code, _name, *_ in TARGETS:
            a, b = (base.get(code) or {}).get('price'), (data.get(code) or {}).get('price')
            if a and b:
                print(f'| {label} | {code} | {a} | {b} | {abs(a - b) / a * 100:.3f}% |')
            else:
                print(f'| {label} | {code} | {a or "—"} | {b or "—"} | 无法比对 |')
    print('\n> 差异接近 0 说明两个源在同一时点看到同一个市场；'
          '差异大可能是时点不同（一个延迟一个实时），也可能是复权口径不同。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
