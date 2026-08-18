"""60 分钟 MACD 顶部钝化 / 顶部结构 / 钝化消失。

**为什么写成代码而不是交给模型**：分析层现在拿到的只有最后一根的
`macd` / `macd_signal` / `macd_hist` 三个标量，它**看不到序列**——任何
"顶背离""动能衰减"的描述都是从三个数字里想象出来的。而这三种状态的判定
本身是纯机械的，能算就不该猜。

**这套术语不是标准定义。** swing high 怎么认、比哪两个峰、用收盘还是最高价、
什么级别，全都是自定的。把它代码化的意义是**把主观固定下来、让它可回测**，
不是让它变客观。所以所有参数显式、默认值写在这里、并随判定结果一起输出。

判定（顺序即优先级）：

    取最近两个 swing high  A（较早）、B（较晚）
    price[B] > price[A] 且 DIF[B] < DIF[A]        → 钝化 blunting
      └ B 之后 DIF 重新超过 DIF[A]                 → 钝化消失 cleared
      └ B 之后 DIF 由升转降                        → 顶部结构 structure

价格与 DIF 都取**收盘价序列**：MACD 本身由收盘价算出，用最高价找峰、用
收盘价算 DIF 会让"价格新高"和"DIF 新高"不是同一件事的两面。

只做顶部。底背离是对称的，但没实现就是没实现，不要在报告里假装有。
"""

SPAN = 3          # swing high 的左右确认根数
FAST, SLOW, SIGNAL = 12, 26, 9

INSUFFICIENT = 'insufficient'
NONE = 'none'
BLUNTING = 'blunting'
STRUCTURE = 'structure'
CLEARED = 'cleared'

LABEL = {
    INSUFFICIENT: '数据不足',
    NONE: '无顶背离',
    BLUNTING: '顶部钝化',
    STRUCTURE: '顶部结构形成',
    CLEARED: '钝化消失',
}

# 三者不是一回事，报告里必须带上这句，否则"钝化"会被读成"见顶"
MEANING = {
    NONE: '最近两个高点未出现价格与动能背离',
    BLUNTING: '价格创新高而 DIF 未创新高，是预警，不等于顶部已确认',
    STRUCTURE: '钝化之后 DIF 掉头向下，调整概率上升',
    CLEARED: '价格与 DIF 同步创新高，原背离条件已不成立',
}


def calc_ema(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def macd_series(closes, fast=FAST, slow=SLOW, signal=SIGNAL):
    """返回与 closes 等长的 (dif, dea)；dea 前段不足处为 None。

    对齐方式刻意与 technical_indicators.calc_macd 一致（DEA 从 dif[slow-1:]
    起算），否则同一份数据在日线卡片和这里会给出两个不同的 DEA。
    """
    if len(closes) < 2:
        return [], []
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    tail = dif[slow - 1:] if len(dif) >= slow else dif
    dea_tail = calc_ema(tail, signal)
    dea = [None] * (len(dif) - len(dea_tail)) + dea_tail
    return dif, dea


def swing_highs(values, span=SPAN):
    """局部高点的下标。

    要求左右各 span 根都确认，所以最后 span 根内的高点**不算**——峰还没被
    确认就拿来比，等于用未来数据。这条是故意的：宁可晚一根，不要假峰。
    """
    out = []
    n = len(values)
    for i in range(span, n - span):
        v = values[i]
        if all(v > values[j] for j in range(i - span, i)) and \
           all(v >= values[j] for j in range(i + 1, i + span + 1)):
            out.append(i)
    return out


def top_state(closes, times=None, span=SPAN, fast=FAST, slow=SLOW, signal=SIGNAL,
              dif=None, min_bars=None):
    """顶部钝化状态机。closes 为按时间升序的收盘价。

    `dif` 只为测试预留：用真实收盘价反推出"DIF 恰好等于 32 然后 30"的序列
    很别扭，而三种状态的分界正需要精确的 DIF 值来钉住。生产路径不要传。
    `min_bars` 同理，仅用于用短序列驱动状态判定。
    """
    floor = min_bars if min_bars is not None else slow + signal + 2 * span + 2
    result = {
        'state': INSUFFICIENT,
        'label': LABEL[INSUFFICIENT],
        'params': {'span': span, 'fast': fast, 'slow': slow, 'signal': signal},
        'bars': len(closes or []),
    }
    if not closes or len(closes) < floor:
        result['reason'] = f'需要至少 {floor} 根，实际 {len(closes or [])} 根'
        return result

    if dif is None:
        dif, _dea = macd_series(closes, fast, slow, signal)
        settled = slow
    else:
        settled = 0
    # DIF 前 slow 根尚未稳定，落在这一段里的峰不参与比较
    peaks = [i for i in swing_highs(closes, span) if i >= settled]
    if len(peaks) < 2:
        result.update(state=NONE, label=LABEL[NONE], meaning=MEANING[NONE],
                      reason=f'可用 swing high 仅 {len(peaks)} 个')
        return result

    a, b = peaks[-2], peaks[-1]

    def stamp(i):
        return {'index': i, 'price': round(closes[i], 4), 'dif': round(dif[i], 4),
                'time': (times[i] if times and i < len(times) else None)}

    result['peak_prev'] = stamp(a)
    result['peak_last'] = stamp(b)
    result['bars_since_last_peak'] = len(closes) - 1 - b

    if not (closes[b] > closes[a] and dif[b] < dif[a]):
        result.update(state=NONE, label=LABEL[NONE], meaning=MEANING[NONE])
        return result

    after = dif[b + 1:]
    if after and max(after) > dif[a]:
        result.update(state=CLEARED, label=LABEL[CLEARED], meaning=MEANING[CLEARED],
                      dif_peak_after=round(max(after), 4))
        return result

    # 结构：B 之后 DIF 已经由升转降。只看最后一根方向，不等死叉——
    # 死叉往往比"掉头"晚好几根，等到那时预警已经没有价值。
    if len(dif) - 1 > b and dif[-1] < dif[-2]:
        result.update(state=STRUCTURE, label=LABEL[STRUCTURE], meaning=MEANING[STRUCTURE],
                      dif_now=round(dif[-1], 4), dif_prev=round(dif[-2], 4))
        return result

    result.update(state=BLUNTING, label=LABEL[BLUNTING], meaning=MEANING[BLUNTING],
                  dif_now=round(dif[-1], 4))
    return result


def parse_60m(klines):
    """东财 klt=60 的行：`日期 时间,开,收,高,低,量,额,...`。"""
    times, closes = [], []
    for line in klines or []:
        parts = str(line).split(',')
        if len(parts) < 3:
            continue
        try:
            closes.append(float(parts[2]))
        except ValueError:
            continue
        times.append(parts[0])
    return times, closes


# A 股 11:30—13:00 休市，Yahoo 仍按 UTC 整点切出一根 11:30 桶。2026-08-18 实测
# 上证该桶平均成交量 3974 万，邻近桶 5 亿—13 亿，是午休切片。留着它等于每天
# 往序列里塞一根几乎不动的价，系统性地压低 DIF。
LUNCH_BUCKET = '11:30'


def parse_yf_60m(frame, drop_lunch=True):
    """yfinance `interval='60m'` 的 DataFrame → (times, closes)。

    单 ticker 下载时 yfinance 返回 MultiIndex 列（('Close','000001.SS')），
    `frame['Close']` 拿到的是 DataFrame 不是 Series，`float()` 会炸。

    ⚠️ **这不是国内看盘软件那个「60 分钟」。** A 股标准 60 分钟是 4 根/交易日
    （10:30／11:30／14:00／15:00），Yahoo 是 UTC 整点网格，剔掉午休切片后
    仍有 5 根/交易日（09:30／10:30／12:30／13:30／14:30）。同名不同物：
    同一段行情两边算出的 DIF 不可直接比较，读数也不会和国内软件对上。
    所以状态里必须带 `source`，报告里必须写明。
    """
    if frame is None or len(frame) == 0:
        return [], []
    col = frame['Close']
    if hasattr(col, 'columns'):          # MultiIndex：取第一列
        col = col.iloc[:, 0]
    times, closes = [], []
    for stamp, value in col.items():
        label = str(stamp)[:16]
        if drop_lunch and label[11:16] == LUNCH_BUCKET:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price != price:               # NaN
            continue
        closes.append(price)
        times.append(label)
    return times, closes


def analyse(series_by_name, span=SPAN):
    """{名称: klines} → {名称: 状态}。用于指数一组一起算。"""
    out = {}
    for name, klines in (series_by_name or {}).items():
        times, closes = parse_60m(klines)
        out[name] = top_state(closes, times=times, span=span)
    return out
