#!/usr/bin/env python3
"""统一时间表示。

项目里曾经混用三种写法：`2026-08-10 06:21:40 UTC`（无时区后缀）、裸 naive
`datetime.utcnow()`、以及本地时间字符串。跨机器或夏令时环境下无法判断新鲜度，
`stale_seconds` 一旦算错，"实时/非实时"的判定就跟着错。

本模块只提供两种合法输出：
  - UTC 时刻      -> `2026-08-10T06:21:40.956545Z`   （utc_iso）
  - 北京时间时刻  -> `2026-08-10T14:21:39+08:00`      （bjt_iso）

两者都带时区，`parse_iso` 可以无歧义读回来。旧格式由 `parse_iso` 兼容读取，
但**不再产生**。
"""
from datetime import datetime, time, timedelta, timezone

BJT = timezone(timedelta(hours=8))

# 历史遗留格式，只读不写
_LEGACY_FORMATS = (
    '%Y-%m-%d %H:%M:%S UTC',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
)


def now_utc():
    """带时区的当前 UTC 时间（不要用已废弃的 datetime.utcnow()）。"""
    return datetime.now(timezone.utc)


def now_bjt():
    return datetime.now(BJT)


def utc_iso(moment=None):
    """`2026-08-10T06:21:40.956545Z`。"""
    moment = moment or now_utc()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def bjt_iso(moment=None):
    """`2026-08-10T14:21:39+08:00`。"""
    moment = moment or now_bjt()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BJT)
    return moment.astimezone(BJT).isoformat()


def parse_iso(value):
    """读回任意历史格式；无法解析返回 None。

    无时区后缀的旧值一律按 UTC 解释——这正是旧格式的本意，也是唯一不会让
    新鲜度凭空多出 8 小时的读法。
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in _LEGACY_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def age_seconds(value, now=None):
    """`value` 距今多少秒；无法解析返回 None。负值截断为 0（时钟漂移）。"""
    parsed = parse_iso(value)
    if parsed is None:
        return None
    reference = now or now_utc()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (reference - parsed).total_seconds())


# A 股交易时段（北京时间）。用于回答一个具体问题：**此刻市场最新能给出的
# 数据是什么时候的**——收盘后是当日 15:00，盘中就是此刻。
TRADING_SESSIONS = ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0)))
SESSION_OPEN, SESSION_CLOSE = time(9, 30), time(15, 0)


def market_open_at(moment=None):
    moment = moment or now_bjt()
    if moment.weekday() >= 5:
        return False
    clock = moment.timetz().replace(tzinfo=None)
    return any(start <= clock <= end for start, end in TRADING_SESSIONS)


def last_market_tick(moment=None):
    """市场此刻最新能给出的数据时点。

    盘中 -> 就是此刻；收盘后 -> 当日 15:00；开盘前或周末 -> 上一交易日 15:00。
    有了它才能区分"数据旧"和"市场本来就没有更新的数据了"——收盘价属于后者，
    称其为最新价并不算错。
    """
    moment = moment or now_bjt()
    if market_open_at(moment):
        return moment
    day = moment.date()
    clock = moment.timetz().replace(tzinfo=None)
    # 午休（11:30–13:00）算作"最新数据 = 上午收盘 11:30"
    if moment.weekday() < 5 and TRADING_SESSIONS[0][1] < clock < TRADING_SESSIONS[1][0]:
        return datetime.combine(day, TRADING_SESSIONS[0][1], tzinfo=BJT)
    if moment.weekday() < 5 and clock > SESSION_CLOSE:
        return datetime.combine(day, SESSION_CLOSE, tzinfo=BJT)
    day -= timedelta(days=1)          # 开盘前或周末：回到上一交易日收盘
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, SESSION_CLOSE, tzinfo=BJT)


def seconds_behind_market(as_of, moment=None):
    """数据落后于"市场最新可得"多少秒。收盘价在收盘后应当接近 0。"""
    parsed = parse_iso(as_of)
    if parsed is None:
        return None
    return max(0.0, (last_market_tick(moment) - parsed).total_seconds())


def trading_date_bjt(mode, moment=None):
    """按模式推算期望的行情日期（跳过周末）。

    morning 取最近一个已完成交易日（昨天往前），afternoon 取当天。
    """
    moment = moment or now_bjt()
    day = moment.date()
    if mode == 'morning':
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime('%Y-%m-%d')
