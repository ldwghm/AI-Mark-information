#!/usr/bin/env python3
"""持久化 K 线缓存（收盘后增量更新）。

**为什么要单独做这件事。** 原来的技术指标链路是：午报生成时临时为 50 只股票
逐只请求 yfinance，失败就退回 `--merge-from` 里顺带捎上的 60 根缓存，再失败
就整片置 null。于是出现了实测中"多数个股 MA/MACD/RSI 缺失"——不是算不出来，
是取历史数据这一步在报告生成的关键路径上，一抖动就全丢。

改法是把历史数据从关键路径上摘下来：

    收盘后（独立 workflow）  ->  增量更新 klines_cache.json（120 交易日）
    早报/午报生成时          ->  只读缓存 + 追加当日快照，不再临时请求 yfinance

缓存是仓库里的持久文件，每个标的记录 `last_date` / `source` / `adjust`，
可以判断这根 K 线是什么时候、从哪来、用的什么复权方式。

用法:
    python -m stock_report.klines_cache --update            # 收盘后全量增量更新
    python -m stock_report.klines_cache --update --codes 600522,000725
"""
import argparse
import json
import os
from pathlib import Path

try:
    from . import timeutil
except ImportError:                    # 直接执行
    import timeutil

HERE = Path(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = HERE / 'data' / 'klines_cache.json'
MAX_BARS = 120                         # 保留 120 个交易日
ADJUST = 'qfq_yfinance_auto'           # yfinance 默认 auto_adjust 行为，记录下来避免口径混淆


def empty_entry():
    return {'dates': [], 'closes': [], 'volumes': [],
            'last_date': '', 'source': '', 'adjust': ADJUST, 'updated_at': None}


def merge_series(existing, incoming, max_bars=MAX_BARS, source='yfinance', now=None):
    """按日期合并两段序列，去重、排序、只保留最近 max_bars 根。

    `incoming` 形如 {'dates': [...], 'closes': [...], 'volumes': [...]}。
    同一天两边都有时**以 incoming 为准**（收盘后的修订值比旧值可信）。
    """
    existing = existing or empty_entry()
    by_date = {}
    for series in (existing, incoming or {}):
        dates = series.get('dates') or []
        closes = series.get('closes') or []
        volumes = series.get('volumes') or []
        for i, day in enumerate(dates):
            if i >= len(closes):
                break
            close = closes[i]
            if close is None:
                continue
            volume = volumes[i] if i < len(volumes) else None
            by_date[day] = (float(close), float(volume) if volume is not None else 0.0)

    ordered = sorted(by_date.items())[-max_bars:]
    merged = empty_entry()
    merged['dates'] = [d for d, _ in ordered]
    merged['closes'] = [round(v[0], 4) for _, v in ordered]
    merged['volumes'] = [v[1] for _, v in ordered]
    merged['last_date'] = merged['dates'][-1] if merged['dates'] else ''
    merged['source'] = source if incoming else existing.get('source', '')
    merged['adjust'] = ADJUST
    merged['updated_at'] = timeutil.utc_iso(now)
    return merged


def needs_update(entry, expected_date):
    """缓存是否已经覆盖到期望交易日。"""
    if not entry or not entry.get('last_date'):
        return True
    return entry['last_date'] < expected_date


def stale_entries(cache, expected_date):
    """返回尚未更新到 expected_date 的标的代码。"""
    return sorted(code for code, entry in (cache or {}).items()
                  if needs_update(entry, expected_date))


def coverage(cache, codes, expected_date, min_bars=20):
    """缓存对给定股票池的可用覆盖率——技术指标能否算得出来看这个。"""
    usable = 0
    for code in codes:
        entry = (cache or {}).get(code) or {}
        if len(entry.get('closes') or []) >= min_bars and not needs_update(entry, expected_date):
            usable += 1
    total = len(codes)
    return usable, total, (usable / total if total else 0.0)


def load_cache(path=CACHE_PATH):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as exc:
        print(f'klines cache unreadable ({exc}), starting empty')
        return {}


def save_cache(cache, path=CACHE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, separators=(',', ':')),
                    encoding='utf-8')
    return path


def _load_universe():
    for candidate in (HERE / 'sectors.json', Path('/tmp/sectors.json')):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding='utf-8-sig'))
    raise SystemExit('sectors.json not found')


def _yf_ticker(code):
    if code[0] in '69':
        return code + '.SS'
    if code[0] in '48':
        return None
    return code + '.SZ'


def update(codes=None, path=CACHE_PATH, period='6mo'):
    """增量更新缓存。返回 (更新数, 跳过数)。"""
    import yfinance as yf

    universe = _load_universe()
    all_codes = [c for _, lst in universe['sectors'].items() for c, _n in lst]
    targets = [c for c in (codes or all_codes) if _yf_ticker(c)]
    expected = timeutil.trading_date_bjt('morning')

    cache = load_cache(path)
    tickers = [_yf_ticker(c) for c in targets]
    print(f'updating {len(targets)} codes (expected trading date {expected})')

    hist = None
    for _attempt in range(2):
        try:
            hist = yf.download(tickers, period=period, group_by='ticker',
                               threads=True, progress=False)
            if hist is not None and len(hist):
                break
        except Exception as exc:
            print('yf.download fail:', exc)
    if hist is None or not len(hist):
        print('WARN: yfinance unavailable, cache left unchanged')
        return 0, len(targets)

    updated = skipped = 0
    for code in targets:
        ticker = _yf_ticker(code)
        try:
            frame = hist[ticker].dropna()
        except (KeyError, TypeError):
            skipped += 1
            continue
        if not len(frame):
            skipped += 1
            continue
        incoming = {
            'dates': [d.strftime('%Y-%m-%d') for d in frame.index],
            'closes': [float(x) for x in frame['Close'].values],
            'volumes': [float(x) for x in frame['Volume'].values],
        }
        cache[code] = merge_series(cache.get(code), incoming)
        updated += 1

    save_cache(cache, path)
    usable, total, ratio = coverage(cache, targets, expected)
    print(f'klines cache: updated {updated}, skipped {skipped}, '
          f'usable {usable}/{total} ({ratio:.0%}) -> {path}')
    return updated, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='执行增量更新')
    parser.add_argument('--codes', help='逗号分隔的股票代码，默认全池')
    parser.add_argument('--path', default=str(CACHE_PATH))
    parser.add_argument('--period', default='6mo')
    args = parser.parse_args()

    if not args.update:
        cache = load_cache(args.path)
        expected = timeutil.trading_date_bjt('morning')
        stale = stale_entries(cache, expected)
        print(json.dumps({'entries': len(cache), 'expected_date': expected,
                          'stale': len(stale), 'stale_codes': stale[:20]},
                         ensure_ascii=False, indent=2))
        return

    codes = [c.strip() for c in args.codes.split(',')] if args.codes else None
    update(codes=codes, path=Path(args.path), period=args.period)


if __name__ == '__main__':
    main()
