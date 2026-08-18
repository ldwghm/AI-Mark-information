#!/usr/bin/env python3
"""
fetch_market_data.py
Pre-fetches A-share AI sector market data for morning report (daily report)
Runs on GitHub Actions at 7:50 CST (23:50 UTC Sunday-Thursday)
Saves to: stock_report/data/morning_latest.json
"""
import requests, json, os, time
from datetime import datetime, timedelta
from technical_indicators import compute_stock_technical
from stock_report import flow_divergence
from stock_report import macd_state
from stock_report import second_source

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.eastmoney.com/"
}

# 突发限流才值得退避重试。2026-08-18 实测：push2his 前 4 个请求成功、之后整批
# `RemoteDisconnected`，连观察池 10 只的日线一起挂掉——于是 technicals 每天静默
# 退回 klines_cache（`is_fallback: true`、17 小时陈旧、且 cache 没有 OHLC，
# 这正是 playbook 规则 1 那次「51 行最高＝最低＝现价」的根源）。
#
# ⚠️ 别和 cloud_fetch 里"yfinance 不重试"的判断搞混：那边是代理
# `CONNECT tunnel failed, response 403`，确定性策略拦截，重试两次报同样的错。
# 这里是连打请求把对端打崩，退避正是对症的。
RETRY_ON = ('remotedisconnected', 'connection aborted', 'connection reset',
            'connection refused', 'timed out', 'timeout',
            'temporarily unavailable', 'bad gateway', 'service unavailable')


def safe_get(url, params=None, timeout=20, attempts=3, backoff=1.5):
    last = None
    for attempt in range(max(1, attempts)):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            text = f'{type(e).__name__}: {e}'.lower()
            if not any(k in text for k in RETRY_ON):
                break
            if attempt < attempts - 1:
                time.sleep(backoff * (attempt + 1))
    print(f"  WARN {url[:70]}: {last}")
    return None


# MACD(12,26,9) 需要 slow+signal=35 根才有值。原来固定取 25 根，于是
# index_technicals 的 macd/macd_signal/macd_hist **每天都是 null**、
# macd_status 恒为「未知」——报告里那一列从来没有过内容。60 根同时
# 覆盖 MA20 与 20 日支撑压力，代价只是每只多 35 行。
DAILY_BARS = 60

DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def datacenter_get(label, params, timeout=25):
    """东财 datacenter 报表查询。**返回 (rows, error)，不把失败吞成空表。**

    这个接口用 HTTP 200 + body 里的 `success:false` 报错，所以 safe_get 那层
    看不出任何问题，旧写法 `data["result"]["data"] if ... else []` 会把它悄悄
    变成空列表。实测后果：northbound / dragon_tiger / margin_trading 三个字段
    因为东财改了列名（`SECURITY_NAME` → `SECURITY_NAME_ABBR` 等）连续多期
    返回 `[]`，而日志里一个字都没有，报告端只当"今天没有龙虎榜"。
    错误码 9501「XXX返回字段不存在」必须响，否则下次改名还是这样。
    """
    payload = dict(params)
    payload.setdefault("client", "WEB")
    data = safe_get(DATACENTER, payload, timeout=timeout)
    if data is None:
        return [], f"{label}: 请求失败"
    if not data.get("success"):
        msg = data.get("message") or data.get("code") or "unknown"
        print(f"  ERROR {label}: 东财返回 success=false（{msg}）—— 报表字段可能已变更")
        return [], f"{label}: {msg}"
    rows = (data.get("result") or {}).get("data") or []
    return rows, None


def _latest_trade_date(report_name, date_column):
    """先问该报表的最新日期。

    两融旧写法按 RZYE 倒序且不带日期过滤，会把历史最高融资余额的行捞上来——
    实测探到的样本日期是 2024-06-07。就算列名修好，不锁日期照样是错的。
    """
    rows, err = datacenter_get(
        f"{report_name}.{date_column}",
        {"reportName": report_name, "columns": date_column, "pageNumber": 1,
         "pageSize": 1, "sortTypes": -1, "sortColumns": date_column})
    if err or not rows:
        return None
    value = rows[0].get(date_column)
    return str(value)[:10] if value else None

def fetch_daily_klines_em(secid, days=DAILY_BARS):
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": days,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    return data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []


def fetch_daily_klines_yf(ticker, days=DAILY_BARS):
    """yfinance 日线 → 东财 klt=101 的行格式，下游 parse_klines 不用改。

    字段顺序照 f51..f61：`日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率`。
    **成交额与换手率留空**——Yahoo 不给，空着比编一个 `close*volume` 诚实
    （parse_klines 已能把缺失读成 None 而不丢整行）。
    """
    try:
        import yfinance as yf
        frame = yf.download(ticker, period='3mo', interval='1d',
                            progress=False, auto_adjust=False)
    except Exception as exc:
        print(f"  WARN yf daily {ticker}: {type(exc).__name__}: {exc}")
        return []
    if frame is None or len(frame) == 0:
        return []

    def col(name):
        c = frame[name]
        return c.iloc[:, 0] if hasattr(c, 'columns') else c

    o, h, l, c, v = (col(x) for x in ('Open', 'High', 'Low', 'Close', 'Volume'))
    lines, prev_close = [], None
    for stamp in frame.index:
        try:
            row = [float(o[stamp]), float(h[stamp]), float(l[stamp]),
                   float(c[stamp]), float(v[stamp])]
        except (TypeError, ValueError, KeyError):
            continue
        if any(x != x for x in row):          # NaN
            continue
        op, hi, lo, cl, vol = (round(x, 3) for x in row)
        if prev_close:
            amp = round((hi - lo) / prev_close * 100, 2)
            chg_pct = round((cl - prev_close) / prev_close * 100, 2)
            chg = round(cl - prev_close, 2)
        else:
            amp = chg_pct = chg = 0
        lines.append(f"{str(stamp)[:10]},{op},{cl},{hi},{lo},{int(vol)},,"
                     f"{amp},{chg_pct},{chg},")
        prev_close = cl
    return lines[-days:]


def fetch_daily_from_60m_yf(ticker, days=DAILY_BARS):
    """把 60 分钟聚合成日线。

    Yahoo 对**创业板指(399006.SZ) 与科创50(000688.SS) 没有日线历史**——
    period 取 3mo/6mo/1y、start/end、Ticker.history 四种问法都只回今天一根
    （2026-08-18 实测），但同一个 ticker 的 60 分钟有 110 根。上证与深证成指
    的日线则正常。差异在 Yahoo 那边，问不出所以然，只能绕。

    60m 的 period='3mo' 覆盖 65 个交易日，聚合后够 MACD(12,26,9) 的 35 根。
    开＝当日首根开、收＝末根收、高低＝当日极值、量＝求和；**成交额仍留空**。
    ⚠️ 聚合用的 60m 已剔除午休切片，日内极值取自剩下的 5 根，
    与交易所口径的当日最高/最低可能有细微出入。
    """
    frame = fetch_index_60m_yf(ticker, period='3mo')
    if frame is None:
        return []

    def col(name):
        c = frame[name]
        return c.iloc[:, 0] if hasattr(c, 'columns') else c

    o, h, l, c, v = (col(x) for x in ('Open', 'High', 'Low', 'Close', 'Volume'))
    buckets, order = {}, []
    for stamp in frame.index:
        label = str(stamp)[:16]
        if label[11:16] == macd_state.LUNCH_BUCKET:
            continue
        day = label[:10]
        try:
            bar = [float(o[stamp]), float(h[stamp]), float(l[stamp]),
                   float(c[stamp]), float(v[stamp])]
        except (TypeError, ValueError, KeyError):
            continue
        if any(x != x for x in bar):
            continue
        op, hi, lo, cl, vol = bar
        if day not in buckets:
            buckets[day] = [op, hi, lo, cl, vol]
            order.append(day)
            continue
        agg = buckets[day]
        agg[1] = max(agg[1], hi)
        agg[2] = min(agg[2], lo)
        agg[3] = cl
        agg[4] += vol

    lines, prev_close = [], None
    for day in order:
        op, hi, lo, cl, vol = (round(x, 3) for x in buckets[day])
        if prev_close:
            amp = round((hi - lo) / prev_close * 100, 2)
            chg_pct = round((cl - prev_close) / prev_close * 100, 2)
            chg = round(cl - prev_close, 2)
        else:
            amp = chg_pct = chg = 0
        lines.append(f"{day},{op},{cl},{hi},{lo},{int(vol)},,{amp},{chg_pct},{chg},")
        prev_close = cl
    return lines[-days:]


def fetch_daily_klines(secid, ticker, days=DAILY_BARS, min_bars=35):
    """日线：东财优先（有成交额），yfinance 兜底，再退到 60m 聚合。

    东财在这里是优先项而不是像 60m 那样退居兜底，因为它给的是完整
    OHLC＋成交额，且日线的 bar 口径两边一致（不像 60 分钟那样一个 4 根/天、
    一个 5 根/天）。但 push2his 从 Actions runner 间歇性整体不可达，
    实测三次运行里两次这里拿到 0 根——所以必须有兜底，否则 technicals
    每天静默退回 klines_cache（无 OHLC，playbook 规则 1 那次事故的根源）。

    `min_bars=35` 是 MACD(12,26,9) 的下限。加这道判断是因为 Yahoo 对
    创业板指与科创50 只回一根日线——"拿到 1 根"和"没拿到"一样没用，
    不能因为列表非空就当成功，必须继续往下退。
    """
    lines = fetch_daily_klines_em(secid, days)
    if lines:
        return lines, 'eastmoney'
    if not ticker:
        return [], 'unavailable'
    lines = fetch_daily_klines_yf(ticker, days)
    if len(lines) >= min_bars:
        return lines, 'yfinance'
    agg = fetch_daily_from_60m_yf(ticker, days)
    if len(agg) > len(lines):
        return agg, 'yfinance_60m_agg'
    return lines, 'yfinance' if lines else 'unavailable'


def fetch_index_kline(secid, name, days=DAILY_BARS, ticker=None):
    klines, source = ((fetch_daily_klines(secid, ticker, days)) if ticker
                      else (fetch_daily_klines_em(secid, days), 'eastmoney'))
    return {"name": name, "secid": secid, "klines": klines, "klines_source": source}

def fetch_index_kline_60m_em(secid, bars=260):
    """东财 klt=60。单次约 128 根（~32 个交易日）。"""
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "60", "fqt": "1", "end": "20500101", "lmt": bars,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    return data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []


def fetch_index_60m_yf(ticker, period='1mo'):
    """yfinance interval='60m'。返回 DataFrame 或 None。"""
    try:
        import yfinance as yf
        frame = yf.download(ticker, period=period, interval='60m',
                            progress=False, auto_adjust=False)
    except Exception as exc:
        print(f"  WARN yf 60m {ticker}: {type(exc).__name__}: {exc}")
        return None
    return frame if frame is not None and len(frame) else None


def fetch_index_60m_series(secid, ticker):
    """60 分钟收盘序列，返回 (times, closes, source)。

    **yfinance 优先，东财兜底** —— 顺序是照实测定的，不是偏好：
    push2his 从 Actions runner 间歇性整体不可达（2026-08-18 三次运行里两次
    连指数日线都拿不到，run 32084883565 / 32137224403），而 yfinance 是本仓库
    唯一被证明在 Actions 上天天成功的行情源（update-klines-cache.yml 靠它）。
    退避重试解决不了——同一次运行的整个时间窗都在不可达状态里。

    ⚠️ 两个源的"60 分钟"不是同一种：Yahoo 给 A 股 5 根/天，东财 4 根/天。
    DIF 因此不可跨源比较，所以把 source 一路带到报告里。
    """
    frame = fetch_index_60m_yf(ticker)
    if frame is not None:
        times, closes = macd_state.parse_yf_60m(frame)
        if closes:
            return times, closes, 'yfinance'
    times, closes = macd_state.parse_60m(fetch_index_kline_60m_em(secid))
    return times, closes, 'eastmoney' if closes else 'unavailable'


def fetch_concept_boards(fid="f3", pz=200):
    data = safe_get("https://push2delay.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": pz, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": fid, "fs": "m:90+t:3+f:!50",
        "fields": "f2,f3,f4,f5,f6,f12,f14,f20,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f104,f105"
    })
    return data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []

AI_KEYWORDS = ["算力", "光模块", "CPO", "光纤", "光缆", "光通信",
               "AI", "人工智能", "数据中心", "芯片", "半导体",
               "算法", "大模型", "服务器", "液冷", "信创", "华为"]

def filter_ai(boards):
    return [b for b in boards if any(kw in (b.get("f14", "") or "") for kw in AI_KEYWORDS)]

BOARD_FIELDS = ("f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f22,"
                "f23,f62,f184,f66,f84")


def fetch_board_stocks(bk_code, board_name, top=25, ascending=False):
    """板块成分。`ascending=True` 取跌幅榜（po=0）。

    只取涨幅榜的后果：整份快照里一只下跌股都没有（08-13 实测 130 只样本
    涨跌幅最小 +0.9%），于是"跌但主力净流入＝逆势承接"这一类背离
    **永远检测不到**，而且看起来像是"今天没有"，不像是取数看不见。
    """
    data = safe_get("https://push2delay.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": top, "po": 0 if ascending else 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": f"b:{bk_code}+f:!50",
        "fields": BOARD_FIELDS
    })
    stocks = data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []
    return {"board_name": board_name, "bk_code": bk_code, "stocks": stocks}

def fetch_capital_flow_top30():
    data = safe_get("https://push2delay.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": 30, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f62",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f6,f7,f8,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
    })
    return data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []

def yf_ticker(secid):
    """东财 secid（`1.600519` / `0.300308`）→ yfinance ticker。

    `1.` 是沪市 → `.SS`，`0.` 是深市（含创业板）→ `.SZ`。北交所（`0.` 开头的
    8/9 字头）Yahoo 没有，返回 None，让调用方老实报 unavailable。
    """
    text = str(secid or '')
    if '.' not in text:
        return None
    market, code = text.split('.', 1)
    if not code.isdigit():
        return None
    if market == '1':
        return f'{code}.SS'
    if market == '0':
        return None if code[0] in ('4', '8', '9') else f'{code}.SZ'
    return None


def fetch_stock_kline(secid, name, days=DAILY_BARS):
    klines, source = fetch_daily_klines(secid, yf_ticker(secid), days)
    return {"name": name, "secid": secid, "klines": klines, "klines_source": source}

# 北向净买入自 2024-08 起停止披露：RPT_MUTUAL_DEAL_HISTORY 里 NET_DEAL_AMT /
# FUND_INFLOW / BUY_AMT / SELL_AMT 四个字段仍在，值恒为 null（2026-08-17 实测）。
# 只有 DEAL_AMT（成交额，单位万元）是真数据。写清楚拿不到什么，比留个空数组强。
NORTHBOUND_TYPES = {"001": "沪股通", "003": "深股通"}


def fetch_northbound():
    """北向：只剩成交额。净买入不可得，且不会再回来——不要拿成交额冒充净流入。"""
    rows, err = datacenter_get("northbound", {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "TRADE_DATE,MUTUAL_TYPE,DEAL_AMT,NET_DEAL_AMT,FUND_INFLOW",
        "filter": '(MUTUAL_TYPE in ("001","003"))',
        "pageNumber": 1, "pageSize": 10,
        "sortTypes": -1, "sortColumns": "TRADE_DATE"})
    if err:
        return {"status": "error", "note": err, "rows": []}

    latest = rows[0]["TRADE_DATE"][:10] if rows else None
    out = []
    for r in rows:
        if latest and str(r.get("TRADE_DATE", ""))[:10] != latest:
            continue
        out.append({
            "trade_date": str(r.get("TRADE_DATE", ""))[:10],
            "channel": NORTHBOUND_TYPES.get(str(r.get("MUTUAL_TYPE")), str(r.get("MUTUAL_TYPE"))),
            # 原值直接存，不换算。东财没有文档标单位：按万元算沪股通只有 13.7 亿，
            # 对单日成交额明显偏小；按百万元算是 1368 亿，量级才对得上。两种都
            # 只是推断，没有第二来源能证，所以不换算也不在报告里写成"亿元"。
            "deal_amt_raw": r.get("DEAL_AMT"),
            "net_buy": None,
        })
    return {
        "status": "partial" if out else "unavailable",
        "trade_date": latest,
        "unit_verified": False,
        "note": ("净买入自2024-08起交易所停止披露，恒为不可得；"
                 "deal_amt_raw 为东财原值，单位未核实，引用前须自行标注口径"),
        "rows": out,
    }


def fetch_dragon_tiger(top=60):
    """龙虎榜：最新一个榜单日，按机构口径净买入排序。

    列名已随东财改版变更（`SECURITY_NAME`→`SECURITY_NAME_ABBR`、
    `NET_BUY_AMT`→`BILLBOARD_NET_AMT`、`OPERATEDEPT_NAME`/`RANK` 已不在本表）。
    改版后多出 DEAL_AMOUNT_RATIO（龙虎榜成交占全天成交比）和上榜后 N 日涨幅，
    后者让"上榜"这件事第一次可以被回测。
    """
    latest = _latest_trade_date("RPT_DAILYBILLBOARD_DETAILSNEW", "TRADE_DATE")
    if not latest:
        return {"status": "unavailable", "trade_date": None, "rows": []}

    rows, err = datacenter_get("dragon_tiger", {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": ("TRADE_DATE,SECURITY_CODE,SECURITY_NAME_ABBR,CLOSE_PRICE,CHANGE_RATE,"
                    "EXPLANATION,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,"
                    "BILLBOARD_DEAL_AMT,DEAL_AMOUNT_RATIO,ACCUM_AMOUNT,TURNOVERRATE,"
                    "D1_CLOSE_ADJCHRATE,D5_CLOSE_ADJCHRATE,D10_CLOSE_ADJCHRATE"),
        "filter": f"(TRADE_DATE='{latest} 00:00:00')",
        "pageNumber": 1, "pageSize": top,
        "sortTypes": -1, "sortColumns": "BILLBOARD_NET_AMT"})
    if err:
        return {"status": "error", "note": err, "trade_date": latest, "rows": []}

    return {"status": "ok" if rows else "unavailable", "trade_date": latest,
            "rows": _dedupe_billboard(rows)}


def _dedupe_billboard(rows):
    """同一只股票同一天可以因多个原因分别上榜（实测 000620 盈新发展当日两行，
    净买入 2.53 亿与 1.91 亿，上榜原因不同）。

    这几行的成交是重叠的，**不能相加**；直接平铺又会让"净买入前十"里同一只
    股票占两格。取绝对值最大的那条作代表，把其余原因收进 also_listed_for，
    并记下上榜次数——一天上多个榜本身就是强度信号，不该丢。
    """
    best = {}
    order = []
    for r in rows:
        code = r.get("SECURITY_CODE")
        if code is None:
            continue
        item = {
            "code": code,
            "name": r.get("SECURITY_NAME_ABBR"),
            "price": r.get("CLOSE_PRICE"),
            "chg_pct": r.get("CHANGE_RATE"),
            "net_buy": r.get("BILLBOARD_NET_AMT"),
            "buy": r.get("BILLBOARD_BUY_AMT"),
            "sell": r.get("BILLBOARD_SELL_AMT"),
            "board_deal_ratio": r.get("DEAL_AMOUNT_RATIO"),
            "turnover_rate": r.get("TURNOVERRATE"),
            "reason": r.get("EXPLANATION"),
            "after_1d": r.get("D1_CLOSE_ADJCHRATE"),
            "after_5d": r.get("D5_CLOSE_ADJCHRATE"),
            "after_10d": r.get("D10_CLOSE_ADJCHRATE"),
            "board_count": 1,
            "also_listed_for": [],
        }
        if code not in best:
            best[code] = item
            order.append(code)
            continue
        kept = best[code]
        kept["board_count"] += 1
        loser = item
        if abs(_f(item["net_buy"])) > abs(_f(kept["net_buy"])):
            item["board_count"] = kept["board_count"]
            item["also_listed_for"] = kept["also_listed_for"]
            best[code] = item
            loser = kept
        if loser.get("reason"):
            best[code]["also_listed_for"].append(loser["reason"])
    return [best[c] for c in order]


def _f(v):
    return v if isinstance(v, (int, float)) else 0.0


def fetch_margin_trading(top=100):
    """两融：锁定最新披露日，按融资净买入排序。

    旧写法按 RZYE 倒序且不带日期过滤，会把历史上融资余额最高的行捞出来——
    探测样本日期是 2024-06-07。锁日期这件事和改列名同样重要。
    """
    latest = _latest_trade_date("RPTA_WEB_RZRQ_GGMX", "DATE")
    if not latest:
        return {"status": "unavailable", "trade_date": None, "rows": []}

    rows, err = datacenter_get("margin_trading", {
        "reportName": "RPTA_WEB_RZRQ_GGMX",
        "columns": ("DATE,SCODE,SECNAME,SPJ,ZDF,RZYE,RZMRE,RZCHE,RZJME,RQYE,RZRQYE,"
                    "RZYEZB,RZJME3D,RZJME5D"),
        "filter": f"(DATE='{latest} 00:00:00')",
        "pageNumber": 1, "pageSize": top,
        "sortTypes": -1, "sortColumns": "RZJME"})
    if err:
        return {"status": "error", "note": err, "trade_date": latest, "rows": []}

    out = [{
        "code": r.get("SCODE"),
        "name": r.get("SECNAME"),
        "price": r.get("SPJ"),
        "chg_pct": r.get("ZDF"),
        "fin_net_buy": r.get("RZJME"),          # 融资净买入
        "fin_balance": r.get("RZYE"),           # 融资余额
        "fin_buy": r.get("RZMRE"),
        "fin_repay": r.get("RZCHE"),
        "short_balance": r.get("RQYE"),         # 融券余额
        "total_balance": r.get("RZRQYE"),
        "fin_pct_of_float": r.get("RZYEZB"),    # 融资余额占流通市值%
        "fin_net_buy_3d": r.get("RZJME3D"),
        "fin_net_buy_5d": r.get("RZJME5D"),
    } for r in rows]
    return {"status": "ok" if out else "unavailable", "trade_date": latest, "rows": out}

def main():
    print(f"=== Morning fetch started {datetime.now().isoformat()} ===")
    result = {
        "fetch_time": datetime.now().isoformat(),
        "fetch_date": datetime.now().strftime("%Y-%m-%d"),
        "report_type": "morning"
    }

    print("1. Index K-lines...")
    result["indices"] = {
        "shanghai": fetch_index_kline("1.000001", "上证指数", ticker="000001.SS"),
        "shenzhen": fetch_index_kline("0.399001", "深证成指", ticker="399001.SZ"),
        "chinext":  fetch_index_kline("0.399006", "创业板指", ticker="399006.SZ"),
        "star50":   fetch_index_kline("1.000688", "科创50", ticker="000688.SS"),
    }
    for k, v in result["indices"].items():
        print(f"   {v['name']}: {len(v['klines'])} bars ({v.get('klines_source')})")
    time.sleep(0.5)

    print("1b. Index technicals...")
    result["index_technicals"] = {}
    for k, v in result["indices"].items():
        tech = compute_stock_technical(v["klines"])
        if tech:
            result["index_technicals"][k] = tech
            print(f"   {v['name']}: {tech['ma_trend']}")

    # 1c 才是唯一有 60 分钟粒度的地方。日线 MACD 看不出"这一轮上涨的动能
    # 什么时候开始跟不上价格"——那是小时级的事。分析层拿到的一直只有最后
    # 一根的三个标量，看不到序列，所以背离只能靠猜；这里把判定算完再给它。
    print("1c. Index 60m MACD state...")
    result["index_macd_60m"] = {}
    for key, secid, ticker, name in (("shanghai", "1.000001", "000001.SS", "上证指数"),
                                     ("shenzhen", "0.399001", "399001.SZ", "深证成指"),
                                     ("chinext", "0.399006", "399006.SZ", "创业板指"),
                                     ("star50", "1.000688", "000688.SS", "科创50")):
        times, closes, source = fetch_index_60m_series(secid, ticker)
        state = macd_state.top_state(closes, times=times)
        state["name"] = name
        state["source"] = source
        result["index_macd_60m"][key] = state
        print(f"   {name}: {state['label']}（{state['bars']} 根 60min, {source}）")
        time.sleep(0.3)

    print("2. Concept boards by change...")
    all_by_change = fetch_concept_boards("f3", 200)
    result["all_boards_by_change"] = all_by_change[:60]
    time.sleep(0.4)

    print("3. Concept boards by capital flow...")
    result["board_capital_flows"] = fetch_concept_boards("f62", 100)
    time.sleep(0.4)

    ai_boards = filter_ai(all_by_change)
    result["ai_boards"] = ai_boards
    print(f"4. AI boards: {len(ai_boards)} found")
    for b in ai_boards[:12]:
        print(f"   {b.get('f14','?')}: {b.get('f3','?')}%  flow={b.get('f62','?')}")

    print("5. AI board constituents (top 8)...")
    def _safe_float(v, default=0):
        try: return float(v)
        except (ValueError, TypeError): return default
    top_ai = sorted(ai_boards, key=lambda x: _safe_float(x.get("f3", 0) or 0), reverse=True)[:8]
    result["board_stocks"] = []
    result["board_laggards"] = []
    for b in top_ai:
        bk, nm = b.get("f12", ""), b.get("f14", "")
        if bk:
            print(f"   {nm} ({bk})...")
            result["board_stocks"].append(fetch_board_stocks(bk, nm))
            time.sleep(0.4)
            # 跌幅榜：没有它，"跌但主力净流入"这类背离永远检测不到
            result["board_laggards"].append(fetch_board_stocks(bk, nm, top=10, ascending=True))
            time.sleep(0.4)

    print("6. Capital flow top30...")
    result["capital_flow_top30"] = fetch_capital_flow_top30()
    print(f"   {len(result['capital_flow_top30'])} stocks")
    time.sleep(0.4)

    print("7. Watchlist K-lines...")
    watchlist = [
        ("0.300308", "中际旭创"), ("0.300502", "新易盛"), ("0.300394", "天孚通信"),
        ("1.601138", "工业富联"), ("1.603019", "中科曙光"), ("1.688256", "寒武纪"),
        ("1.688041", "海光信息"), ("1.601869", "长飞光纤"), ("1.600487", "亨通光电"),
        ("0.002230", "科大讯飞"),
    ]
    result["watchlist_klines"] = []
    for secid, name in watchlist:
        kl = fetch_stock_kline(secid, name)
        result["watchlist_klines"].append(kl)
        print(f"   {name}: {len(kl['klines'])} bars ({kl.get('klines_source')})")
        time.sleep(0.25)

    # Compute technical indicators for watchlist
    print("7b. Watchlist technicals...")
    flow_lookup = {}
    for s in result["capital_flow_top30"]:
        cd = s.get("f12", "")
        fl = s.get("f62")
        if cd and fl is not None:
            flow_lookup[cd] = float(fl) if fl != "-" else 0

    result["watchlist_technicals"] = []
    for kl in result["watchlist_klines"]:
        secid = kl.get("secid", "")
        code = secid.split(".")[-1] if "." in secid else secid
        net_flow = flow_lookup.get(code)
        tech = compute_stock_technical(kl["klines"], net_flow)
        entry = {"name": kl["name"], "secid": secid, "code": code}
        if tech:
            entry.update(tech)
        result["watchlist_technicals"].append(entry)

    # 8–10 是"筹码侧"。三个字段一直声明着但连续多期为空——东财改了列名，
    # 而旧代码把 API 的 success=false 吞成 []。现在状态和日期都要写进快照，
    # 空表必须能和"取数失败"区分开。
    def _report(label, block):
        rows = block.get("rows") or []
        print(f"   [{block.get('status')}] {len(rows)} rows"
              f"{' @ ' + block['trade_date'] if block.get('trade_date') else ''}"
              f"{' — ' + block['note'] if block.get('note') else ''}")

    print("8. Northbound capital...")
    result["northbound"] = fetch_northbound()
    _report("northbound", result["northbound"])
    time.sleep(0.4)

    print("9. Dragon tiger...")
    result["dragon_tiger"] = fetch_dragon_tiger()
    _report("dragon_tiger", result["dragon_tiger"])
    time.sleep(0.4)

    print("10. Margin trading...")
    result["margin_trading"] = fetch_margin_trading()
    _report("margin_trading", result["margin_trading"])

    print("11. Price / capital-flow divergence...")
    result["flow_divergence"] = flow_divergence.analyse(result)
    fd = result["flow_divergence"]
    print(f"   扫描 {fd['scanned']} 只：拉高派发 {len(fd['distribution'])}、"
          f"逆势承接 {len(fd['accumulation'])}"
          f"{'' if fd['accumulation_detectable'] else '（样本无下跌股，后者不可检出）'}")

    # 双源交叉验证只能在这里做：CCR 会话连不上新浪/腾讯，那边的 crosscheck
    # 每期都是 checked_pairs=0。runner 上新浪 718ms、腾讯 957ms，都通。
    print("12. Cross-check against second source (sina/tencent)...")
    second_source.attach_crosscheck(result)

    os.makedirs("stock_report/data", exist_ok=True)
    out = "stock_report/data/morning_latest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== Done! {os.path.getsize(out)//1024}KB saved to {out} ===")

if __name__ == "__main__":
    main()
