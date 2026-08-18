#!/usr/bin/env python3
"""A 股之外市场的行情抓取（在 GitHub Actions 里跑）。

**为什么必须放在 Actions 而不是 CCR 会话里。** 实测证据：
  - CCR 会话：新浪/腾讯/yfinance 全部不可达，港美股常年空数组；
  - GitHub Actions：yfinance 完全正常（一次批量拉 50 只 A 股 ×119 根 K 线，25 秒）。
所以抓取属于"确定性数据平面"（Actions），分析属于"可替换分析平面"（Claude）。
本脚本产出 `data/global_markets.json`，CCR 只读它，不再自己尝试联网取价。

**每个市场写自己的 as_of。** 日/韩/台/港/美收盘时刻各不相同，混用北京时间会
让"隔夜表现"错位一整天。这里按各市场本地时区标注收盘时点，并给出相对北京
时间的 ISO 串，分析层不用自己换算。

用法:
    python -m stock_report.global_markets --update
    python -m stock_report.global_markets            # 只打印现有快照的状态
"""
import argparse
import json
import os
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from . import provenance, timeutil
except ImportError:                    # 平铺执行
    import provenance
    import timeutil

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_PATH = HERE / 'global_universe.json'
OUTPUT_PATH = HERE / 'data' / 'global_markets.json'

# 超过这个天数就认为该市场数据不可用（长假另说，但要显式看到）
STALE_DAYS = 5


def load_universe(path=UNIVERSE_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))['markets']


def market_close_iso(date_str, timezone_name, close_hhmm):
    """把"某市场某交易日收盘"表示成带该市场时区偏移的 ISO 串。

    这样 2026-08-10 的东京收盘是 15:00+09:00，纽约收盘是 16:00-04:00（夏令时
    自动处理），不会被误当成同一时刻。
    """
    try:
        hour, minute = (int(x) for x in close_hhmm.split(':'))
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, AttributeError):
        return None
    stamped = datetime.combine(day, dtime(hour, minute), tzinfo=ZoneInfo(timezone_name))
    return stamped.isoformat()


def classify(as_of_iso, now=None):
    """fresh / stale / unavailable —— 报告里 global_markets[].status 用的就是它。"""
    if not as_of_iso:
        return 'unavailable'
    age = timeutil.age_seconds(as_of_iso, now=now)
    if age is None:
        return 'unavailable'
    return 'fresh' if age <= STALE_DAYS * 86400 else 'stale'


def _rows_from_frame(frame, code, name, market_key, meta, retrieved_at):
    """把 yfinance 的日线切片转成一行报价（含来源与市场时点）。"""
    if frame is None or len(frame) < 2:
        return None
    closes = frame['Close'].dropna()
    if len(closes) < 2:
        return None
    last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
    if prev == 0:
        return None
    date_str = closes.index[-1].strftime('%Y-%m-%d')
    as_of = market_close_iso(date_str, meta['timezone'], meta['close'])
    row = {
        'code': code,
        'name': name,
        'market': market_key,
        'price': round(last, 2),
        'chg': round((last - prev) / prev * 100, 2),
        'prev_close': round(prev, 2),
        'market_date': date_str,
        'as_of_bjt': timeutil.bjt_iso(timeutil.parse_iso(as_of)) if as_of else None,
    }
    provenance.stamp(row, 'yfinance', as_of=as_of, retrieved_at=retrieved_at)
    return row


def _finalize_market(block, total, now=None):
    """由 indices/stocks 两个列表重算市场级的日期、状态与覆盖率。

    build_snapshot 和 merge_forward 都要做这件事，且必须做得一模一样——
    合并之后如果忘了重算，market_date 会停在合并前的值，报告里的"外围指数
    滞后"判定就会读到自相矛盾的快照。
    """
    rows = list(block.get('indices') or []) + list(block.get('stocks') or [])
    dates = sorted({r['market_date'] for r in rows if r.get('market_date')})
    newest = max((r['as_of'] for r in rows if r.get('as_of')), default=None)

    # 同一市场内各标的的交易日可能不一致——Yahoo 的港/日/台指数实测比其
    # 成分股慢一天。取 max 会把这件事盖住，所以逐行标出来并单独计数。
    newest_date = dates[-1] if dates else None
    for row in rows:
        row['row_stale'] = bool(newest_date and row.get('market_date')
                                and row['market_date'] < newest_date)

    block.update({
        'as_of': newest,
        'as_of_bjt': timeutil.bjt_iso(timeutil.parse_iso(newest)) if newest else None,
        'market_date': newest_date,
        'status': classify(newest, now=now),
        'coverage': f'{len(rows)}/{total}',
        'date_spread': [dates[0], dates[-1]] if dates else None,
        'stale_rows': [r['code'] for r in rows if r['row_stale']],
    })
    return block


def build_snapshot(download, universe, now=None):
    """纯逻辑：给定一个 `download(tickers) -> frame_getter`，产出快照结构。

    download 抽出来是为了能在测试里注入假数据——真实网络调用留在 update()。
    """
    retrieved_at = timeutil.utc_iso(now)
    snapshot = {
        'fetch_time': retrieved_at,
        'fetch_time_bjt': timeutil.bjt_iso(now),
        'markets': {},
    }

    for market_key, meta in universe.items():
        entries = [(c, n, 'index') for c, n in meta.get('indices', [])] + \
                  [(c, n, 'stock') for c, n in meta.get('stocks', [])]
        get_frame = download([c for c, _n, _k in entries])

        indices, stocks = [], []
        for code, name, kind in entries:
            row = _rows_from_frame(get_frame(code), code, name, market_key,
                                   meta, retrieved_at)
            if row is None:
                continue
            (indices if kind == 'index' else stocks).append(row)

        snapshot['markets'][market_key] = _finalize_market({
            'name': meta.get('name', market_key),
            'timezone': meta['timezone'],
            'indices': indices,
            'stocks': stocks,
        }, len(entries), now=now)
    return snapshot


def _total_from_coverage(block, fallback):
    """coverage 形如 "8/8"，分母是该市场的标的总数。"""
    try:
        return int(str(block.get('coverage', '')).split('/')[1])
    except (IndexError, ValueError):
        return fallback


def merge_forward(previous, snapshot, now=None):
    """新抓的一期不许把某一行**退回**到更早的交易日。

    实测（2026-08-12→13）：16:11 与 17:54 两次抓取，港/日/韩/台四个市场的
    指数 market_date 都是正确的 08-12；随后 05:41 那次（21:41 UTC，为美股收盘
    而跑）把它们统统覆盖成 08-11，^N225 更是退到 08-10。Yahoo 在那个时点对
    亚洲代码给不出当日日线，而我们照单全收。

    后果不是"数据旧了"，是**每天必然触发一次 global_index_staleness 降级**——
    一个天天亮的灯等于没有灯。所以这里按行取较新的那个交易日；新抓的一期整行
    缺失时同样沿用旧行（那是同一类失败）。沿用的行保留它自己的 as_of 与
    retrieved_at（它确实是那时取的），另加 carried_forward 标记，让"这个数字
    来自上一次抓取"在快照里看得见，而不是靠猜。
    """
    if not isinstance(previous, dict) or not previous.get('markets'):
        return snapshot

    fetch_time = snapshot.get('fetch_time')
    for key, block in (snapshot.get('markets') or {}).items():
        old_block = (previous.get('markets') or {}).get(key)
        if not isinstance(old_block, dict):
            continue
        old_rows = {r.get('code'): r for kind in ('indices', 'stocks')
                    for r in (old_block.get(kind) or []) if r.get('code')}
        if not old_rows:
            continue

        carried = []

        def _keep(old, reason):
            row = dict(old)
            row['carried_forward'] = True
            row['carried_reason'] = reason
            row['carried_at'] = fetch_time
            carried.append(row['code'])
            return row

        def _fresh_enough(old):
            # 沿用旧值也有限度：超过 STALE_DAYS 就让它掉出去，由 status
            # 如实报 unavailable，而不是永久保留一具尸体。
            age = timeutil.age_seconds(old.get('as_of'), now=now)
            return age is not None and age <= STALE_DAYS * 86400

        for kind in ('indices', 'stocks'):
            merged, seen = [], set()
            for row in (block.get(kind) or []):
                code = row.get('code')
                seen.add(code)
                old = old_rows.get(code)
                if (old and _fresh_enough(old)
                        and (old.get('market_date') or '') > (row.get('market_date') or '')):
                    merged.append(_keep(old, 'regressed'))
                else:
                    merged.append(row)
            # 本次整行没抓到的，沿用旧行（顺序排在后面，不打乱本次的顺序）
            for old in (old_block.get(kind) or []):
                if old.get('code') not in seen and _fresh_enough(old):
                    merged.append(_keep(old, 'missing'))
            block[kind] = merged

        # 分母是 universe 里该市场的标的数，新旧两期同源，取本期的即可
        rows_now = len(block.get('indices') or []) + len(block.get('stocks') or [])
        _finalize_market(block, _total_from_coverage(block, rows_now), now=now)
        if carried:
            block['carried_rows'] = carried
    return snapshot


def summarize(snapshot):
    out = {}
    for key, m in (snapshot.get('markets') or {}).items():
        line = f"{m['status']}({m['coverage']}) @{m.get('market_date') or m.get('as_of_bjt')}"
        if m.get('carried_rows'):
            line += f" carried={','.join(m['carried_rows'])}"
        out[key] = line
    return out


def load_previous(path):
    """读上一期快照；不存在或坏了都当作没有，绝不让它挡住本次抓取。"""
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def update(path=OUTPUT_PATH, universe_path=UNIVERSE_PATH, period='1mo'):
    import yfinance as yf

    universe = load_universe(universe_path)

    def download(tickers):
        frame = None
        for _attempt in range(2):
            try:
                frame = yf.download(tickers, period=period, group_by='ticker',
                                    threads=True, progress=False)
                if frame is not None and len(frame):
                    break
            except Exception as exc:
                print('yf.download fail:', exc)

        def get(code):
            if frame is None or not len(frame):
                return None
            try:
                return frame[code].dropna()
            except (KeyError, TypeError):
                return None
        return get

    path = Path(path)
    snapshot = merge_forward(load_previous(path), build_snapshot(download, universe))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    print('global markets ->', path)
    for line in summarize(snapshot).items():
        print('  ', line[0], line[1])
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--path', default=str(OUTPUT_PATH))
    parser.add_argument('--period', default='1mo')
    args = parser.parse_args()

    if args.update:
        update(path=Path(args.path), period=args.period)
        return
    path = Path(args.path)
    if not path.is_file():
        print('no snapshot yet:', path)
        return
    print(json.dumps(summarize(json.loads(path.read_text(encoding='utf-8-sig'))),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
