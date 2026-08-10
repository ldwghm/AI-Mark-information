#!/usr/bin/env python3
"""字段级来源元信息。

原来只有港美股行带一个 `src`，A 股行完全看不出这个价是新浪实时价、efinance
收盘回填价还是 K 线缓存里的旧价。分析层无从区分，于是把回填价当实时价写进
报告——这正是"数据滞后一个交易日"反复出现的根源。

**不改变既有数值字段的形状。** `price` / `close` / `chg_pct` 仍是裸数字，
渲染端和 verify.py 不受影响；来源信息作为同级字段附加：

    {
      "code": "600522", "close": 39.56, "chg_pct": 1.2,
      "source": "sina", "as_of": "2026-08-10T14:21:38+08:00",
      "retrieved_at": "2026-08-10T06:21:40.956545Z",
      "is_fallback": false, "stale_seconds": 3
    }
"""
try:                        # 作为包导入
    from . import timeutil
except ImportError:         # 云端 curl 到 /tmp 平铺执行
    import timeutil

# 哪些来源属于"降级回填"而非当次实时抓取
FALLBACK_SOURCES = frozenset({'efinance_backfill', 'cache', 'klines_cache', 'stooq'})

PROVENANCE_FIELDS = ('source', 'as_of', 'retrieved_at', 'is_fallback', 'stale_seconds')


def build(source, as_of=None, retrieved_at=None, now=None):
    """构造一行的来源元信息。

    as_of        该数值实际对应的市场时点（带时区；A 股通常是 +08:00）
    retrieved_at 我们把它取回来的时刻（UTC，Z 结尾）
    stale_seconds  as_of 距 retrieved_at 多少秒——判断"能不能叫实时"的唯一依据
    """
    retrieved = retrieved_at or timeutil.utc_iso(now)
    stale = timeutil.age_seconds(as_of, now=timeutil.parse_iso(retrieved)) if as_of else None
    return {
        'source': source,
        'as_of': as_of,
        'retrieved_at': retrieved,
        'is_fallback': source in FALLBACK_SOURCES,
        'stale_seconds': round(stale, 1) if stale is not None else None,
    }


def stamp(row, source, as_of=None, retrieved_at=None, now=None):
    """就地给一行数据打上来源标记，返回该行（便于链式使用）。"""
    row.update(build(source, as_of=as_of, retrieved_at=retrieved_at, now=now))
    return row


def market_as_of(quote_date, quote_time):
    """把新浪/腾讯返回的 `date` + `time` 拼成带 +08:00 的时点。

    两者任一缺失就返回 None——宁可没有，也不要编一个看似精确的时间。
    """
    if not quote_date or not quote_time:
        return None
    text = f'{quote_date}T{quote_time}+08:00'
    return text if timeutil.parse_iso(text) else None


def summarize(rows):
    """统计一批行的来源分布，供 data_quality 使用。"""
    counts = {}
    fallback = 0
    worst_stale = None
    for row in rows or []:
        source = row.get('source') or 'unknown'
        counts[source] = counts.get(source, 0) + 1
        if row.get('is_fallback'):
            fallback += 1
        stale = row.get('stale_seconds')
        if isinstance(stale, (int, float)):
            worst_stale = stale if worst_stale is None else max(worst_stale, stale)
    return {
        'by_source': counts,
        'fallback_rows': fallback,
        'max_stale_seconds': worst_stale,
    }
