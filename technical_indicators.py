#!/usr/bin/env python3
"""technical_indicators.py - Shared technical indicator calculations"""

def parse_klines(klines):
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            rows.append({
                "date": parts[0], "open": float(parts[1]), "close": float(parts[2]),
                "high": float(parts[3]), "low": float(parts[4]),
                "volume": float(parts[5]), "amount": float(parts[6]),
                "chg_pct": float(parts[8]) if len(parts) > 8 else 0,
            })
        except (ValueError, IndexError):
            continue
    return rows

def calc_ema(values, period):
    if not values: return []
    k = 2.0 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def calc_ma(closes, period):
    if len(closes) < period: return None
    return round(sum(closes[-period:]) / period, 3)

def calc_rsi(closes, period=12):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0: return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)

def calc_macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal: return None, None, None
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = calc_ema(dif[slow-1:], signal) if len(dif) >= slow else calc_ema(dif, signal)
    if not dea: return None, None, None
    return round(dif[-1], 3), round(dea[-1], 3), round((dif[-1] - dea[-1]) * 2, 3)

def calc_volume_ratio(volumes):
    if len(volumes) < 2: return None
    today = volumes[-1]
    avg5 = sum(volumes[-6:-1]) / min(5, len(volumes) - 1)
    return round(today / avg5, 2) if avg5 > 0 else None

def volume_label(vr):
    if vr is None: return "未知"
    if vr > 2.0: return "显著放量"
    if vr > 1.5: return "温和放量"
    if vr >= 0.7: return "正常"
    return "缩量"

def detect_divergence(chg_pct, vr):
    if vr is None or chg_pct is None: return False
    return (chg_pct > 2 and vr < 0.8) or (chg_pct < -2 and vr > 2.0)

def ma_trend_label(price, ma5, ma10, ma20):
    if None in (ma5, ma10, ma20): return "数据不足"
    if ma5 > ma10 > ma20 and price > ma5: return "强势多头"
    if ma5 > ma10 > ma20: return "多头排列"
    if ma5 < ma10 < ma20 and price < ma5: return "强势空头"
    if ma5 < ma10 < ma20: return "空头排列"
    if price > ma20: return "震荡偏多"
    if price < ma20: return "震荡偏空"
    return "震荡"

def macd_status_label(hist, prev_hist=None):
    if hist is None: return "未知"
    if prev_hist is not None:
        if hist > 0 and prev_hist <= 0: return "金叉"
        if hist < 0 and prev_hist >= 0: return "死叉"
    if hist > 0:
        return "多头" if (prev_hist is not None and hist > prev_hist) else "多头减弱"
    return "空头" if (prev_hist is not None and hist < prev_hist) else "空头减弱"

def calculate_score(price, ma5, ma10, ma20, vr, chg_pct, macd_h, rsi, net_flow=None):
    score = 0
    if None not in (ma5, ma10, ma20):
        if ma5 > ma10 > ma20: score += 30
        elif ma5 > ma10 or ma5 > ma20: score += 20
        elif ma5 < ma10 < ma20: score += 0
        else: score += 10
    if ma5 and price:
        dev = abs(price - ma5) / ma5 * 100
        if dev <= 2: score += 20
        elif dev <= 5: score += 12
        elif dev <= 8: score += 5
    if vr is not None:
        if chg_pct is not None and chg_pct > 0:
            if 1.0 <= vr <= 2.5: score += 15
            elif 0.7 <= vr < 1.0: score += 8
            elif vr > 2.5: score += 5
        else:
            if vr < 0.7: score += 10
            elif vr < 1.0: score += 5
    if net_flow is not None and net_flow > 0:
        score += min(20, int(20 * min(1, net_flow / 1e8)))
    if macd_h is not None:
        if macd_h > 0: score += 15
        elif macd_h > -0.1: score += 8
    return min(100, max(0, score))

def score_label(s):
    if s >= 80: return "★★★"
    if s >= 60: return "★★"
    return "★"

def compute_stock_technical(klines_raw, net_flow=None):
    rows = parse_klines(klines_raw)
    if len(rows) < 5: return None
    closes = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    price, chg_pct = closes[-1], rows[-1].get("chg_pct", 0)
    ma5, ma10, ma20 = calc_ma(closes, 5), calc_ma(closes, 10), calc_ma(closes, 20)
    rsi = calc_rsi(closes, 12)
    macd_val, dea_val, hist = calc_macd(closes)
    vr = calc_volume_ratio(volumes)
    prev_hist = None
    if len(closes) > 1: _, _, prev_hist = calc_macd(closes[:-1])
    sc = calculate_score(price, ma5, ma10, ma20, vr, chg_pct, hist, rsi, net_flow)
    recent = rows[-20:] if len(rows) >= 20 else rows
    return {
        "price": price, "chg_pct": chg_pct,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "ma_trend": ma_trend_label(price, ma5, ma10, ma20),
        "rsi_12": rsi,
        "macd": macd_val, "macd_signal": dea_val, "macd_hist": hist,
        "macd_status": macd_status_label(hist, prev_hist),
        "volume_ratio": vr, "volume_label": volume_label(vr),
        "divergence": detect_divergence(chg_pct, vr),
        "support_20d": round(min(r["low"] for r in recent), 2),
        "resistance_20d": round(max(r["high"] for r in recent), 2),
        "score": sc, "score_label": score_label(sc),
    }
