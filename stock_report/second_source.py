#!/usr/bin/env python3
"""A 股第二数据源：给 Actions 侧的东方财富快照做独立对账。

## 为什么放在 Actions 侧

CCR 会话和 GitHub Actions runner 的网络完全不同。CCR 里新浪、腾讯、
yfinance 全部被出口代理拦掉，所以 `cloud_fetch` 里那套双源交叉验证
虽然写好了，实际每期都是 `checked_pairs: 0`——不是没写，是跑不到。
而 Actions 上这些源都通。2026-08-12 从 runner 上实测：

    eastmoney push2   ✅ 6177ms   （现用基线）
    sina              ✅  718ms   与基线 0.000% × 3
    tencent           ✅  957ms   与基线 0.000% × 3
    netease           ❌ ConnectionError
    mootdx            ✅ 18076ms  与基线 0.000% × 3

所以第二数据源不需要新库：新浪最快、协议最简单，且与东财是完全独立的
行情通道。腾讯作为新浪不可用时的替补。

## 为什么不选 AKShare

AKShare 的 A 股实时行情底层就是东方财富。拿它和东方财富对账，两边错了
也会一起错——那不是交叉验证，是把同一个数字读两遍。独立性比可达性重要。

mootdx（通达信协议）确实独立，但 18 秒对一个每天跑六次的抓数任务太慢，
而且要引入新依赖。留作后备方案，不作首选。
"""
try:
    from . import crosscheck, http_util, provenance, timeutil
except ImportError:      # 平铺执行
    import crosscheck
    import http_util
    import provenance
    import timeutil

SINA_URL = 'https://hq.sinajs.cn/list='
TENCENT_URL = 'https://qt.gtimg.cn/q='
SINA_HEAD = {'Referer': 'https://finance.sina.com.cn',
             'User-Agent': 'Mozilla/5.0'}
BATCH = 40


def sina_symbol(code):
    """裸**个股**代码 -> 新浪/腾讯的带前缀代码。

    刻意不做指数特判。裸代码分不出指数和个股：`000001` 既是上证指数
    也是平安银行。实测踩到——把东财观察池里的 000001（平安银行，约 11 元）
    映射成 sh000001（上证指数，3940 点），交叉验证报出 34981% 的"冲突"。

    交叉验证只比对观察池里的个股（attach_crosscheck 会与主源报价取交集），
    所以这里一律按个股规则走。要比指数得另配显式的代码表，不能靠猜。
    """
    code = str(code).strip()[-6:]
    return ('sh' if code[0] in '65' else 'sz') + code


def _chunks(items, size=BATCH):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_sina(codes, fetcher=None):
    """返回 {带前缀代码: {price, chg_pct, date, time, src, ...}}。

    整批失败不拖垮其余分片：每片独立取，取不到就跳过这一片。
    """
    get_text = fetcher or (lambda url: http_util.get_text(
        url, headers=SINA_HEAD, timeout=10, encoding='gbk'))
    out = {}
    for chunk in _chunks([sina_symbol(c) for c in codes]):
        text = get_text(SINA_URL + ','.join(chunk))
        if not text:
            continue
        retrieved = timeutil.utc_iso()
        for line in text.strip().split('\n'):
            if '="' not in line:
                continue
            try:
                key = line.split('=')[0].replace('var hq_str_', '').strip()
                f = line.split('"')[1].split(',')
                if len(f) <= 31:
                    continue
                price, prev = float(f[3]), float(f[2])
                if price <= 0 or prev <= 0:
                    continue
                row = {'name': f[0], 'price': price, 'prev_close': prev,
                       'chg_pct': round((price - prev) / prev * 100, 2),
                       'date': f[30], 'time': f[31], 'src': 'sina'}
                provenance.stamp(row, 'sina',
                                 as_of=provenance.market_as_of(f[30], f[31]),
                                 retrieved_at=retrieved)
                out[key] = row
            except (ValueError, IndexError):
                continue
    return out


def fetch_tencent(codes, fetcher=None):
    """新浪不可用时的替补。字段位置与新浪完全不同，单独解析。"""
    get_text = fetcher or (lambda url: http_util.get_text(
        url, timeout=10, encoding='gbk'))
    out = {}
    for chunk in _chunks([sina_symbol(c) for c in codes]):
        text = get_text(TENCENT_URL + ','.join(chunk))
        if not text:
            continue
        retrieved = timeutil.utc_iso()
        for seg in text.strip().split(';'):
            if '="' not in seg:
                continue
            try:
                key = seg.split('=')[0].strip().replace('v_', '')
                f = seg.split('"')[1].split('~')
                if len(f) <= 38:
                    continue
                price = float(f[3])
                if price <= 0:
                    continue
                stamp = f[30]
                date = f'{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}' if len(stamp) >= 8 else ''
                clock = f'{stamp[8:10]}:{stamp[10:12]}:{stamp[12:14]}' if len(stamp) >= 14 else ''
                row = {'name': f[1], 'price': price, 'prev_close': float(f[4]),
                       'chg_pct': float(f[32]), 'date': date, 'time': clock,
                       'src': 'tencent'}
                provenance.stamp(row, 'tencent',
                                 as_of=provenance.market_as_of(date, clock),
                                 retrieved_at=retrieved)
                out[key] = row
            except (ValueError, IndexError):
                continue
    return out


PROVIDERS = (('sina', fetch_sina), ('tencent', fetch_tencent))


def fetch_second_source(codes, providers=PROVIDERS):
    """依次尝试各候选源，返回 (来源名, 行情字典)。全失败返回 (None, {})。

    不合并多个源：合并会让"这个价来自哪里"变得说不清，而交叉验证的全部
    意义就在于两个数字各有明确出处。
    """
    codes = [c for c in codes if c]
    if not codes:
        return None, {}
    for name, fn in providers:
        try:
            quotes = fn(codes)
        except Exception as exc:
            print(f'[second_source] {name} failed: {type(exc).__name__}: {exc}')
            continue
        if quotes:
            print(f'[second_source] {name}: {len(quotes)}/{len(codes)} quotes')
            return name, quotes
        print(f'[second_source] {name}: 0 quotes')
    return None, {}


def primary_quotes(snapshot):
    """从东财快照里取出主源报价，键用裸代码。"""
    out = {}
    for row in (snapshot.get('watchlist_rt') or []):
        code = str(row.get('code') or '')
        price = row.get('current')
        if code and isinstance(price, (int, float)):
            out[code] = {'price': price, 'chg_pct': row.get('change_pct'),
                         'src': 'eastmoney', 'date': row.get('data_date', '')}
    for row in (snapshot.get('watchlist_technicals') or []):
        code = str(row.get('code') or '')
        price = row.get('close')
        if code and code not in out and isinstance(price, (int, float)):
            out[code] = {'price': price, 'chg_pct': row.get('chg_pct'),
                         'src': 'eastmoney', 'date': row.get('data_date', '')}
    return out


SKEW_LIMIT_SECONDS = 120


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if not ordered:
        return None
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


MARKET_CLOSE_HOUR = 15


def as_of_skew(snapshot, secondary, now=None):
    """第二源的行情时点落后当前多少秒。取中位数，个别坏时间戳不该主导判断。

    收盘后返回 0：两个源报的都是同一根收盘价，"时点差"不影响可比性。
    只有盘中——第二源的时点还在收盘之前——两次取数的间隔才会让价格
    真实地走开，那时价差才不能归因于来源分歧。
    """
    now = now or timeutil.now_utc()
    gaps = []
    for row in (secondary or {}).values():
        moment = timeutil.parse_iso((row or {}).get('as_of'))
        if moment is None:
            continue
        if moment.astimezone(timeutil.BJT).hour >= MARKET_CLOSE_HOUR:
            gaps.append(0.0)          # 已收盘，双方都是当日收盘价
        else:
            gaps.append(abs((now - moment).total_seconds()))
    return _median(gaps)


def attach_crosscheck(snapshot, providers=PROVIDERS, now=None):
    """给东财快照加上真实的双源交叉验证结果，就地写入并返回摘要。

    只核对真正会进结论的标的（指数、涨跌幅前 10、板块龙头/落后），
    不是给 51 只都查两遍——那只是把请求量翻倍。
    """
    primary = primary_quotes(snapshot)
    targets = sorted(crosscheck.select_crosscheck_targets(snapshot) & set(primary))
    if not targets:
        summary = crosscheck.summarize([], 0)
        summary['note'] = '主源无可用报价，无从比对'
        snapshot['source_crosscheck'] = summary
        return summary

    source, secondary = fetch_second_source(targets, providers)
    conflicts = crosscheck.cross_validate(primary, secondary, targets)
    checked = crosscheck.count_checked_pairs(primary, secondary, targets)
    summary = crosscheck.summarize(conflicts, checked)
    summary['primary_source'] = 'eastmoney'
    summary['secondary_source'] = source
    summary['checked_at'] = timeutil.utc_iso()

    # 两次抓取不是同一时点时，价差归因于"源不一致"是错的——盘中一分钟的
    # 真实波动就能越过 0.5% 阈值。这种情况下差异说明不了任何来源问题。
    skew = as_of_skew(snapshot, secondary, now=now)
    summary['as_of_skew_seconds'] = None if skew is None else round(skew, 1)
    if conflicts and skew is not None and skew > SKEW_LIMIT_SECONDS:
        summary['status'] = 'skewed'
        summary['note'] = (f'两个源的取数时点相差约 {skew / 60:.1f} 分钟，'
                           f'{len(conflicts)} 处价差不能归因于来源分歧，本期不作为冲突')

    if checked == 0:
        summary['note'] = ('第二数据源不可达或无重叠标的，本期未做交叉验证'
                           if not source else f'{source} 未返回任何目标标的报价')
    snapshot['source_crosscheck'] = summary
    print(f'[second_source] crosscheck: {summary["status"]} '
          f'({checked}/{len(targets)} pairs, {len(conflicts)} conflicts)')
    return summary
