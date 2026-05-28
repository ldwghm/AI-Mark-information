#!/usr/bin/env python3
"""
fetch_market_data_pm.py
Pre-fetches real-time A-share AI sector data for afternoon report (午报)
Runs on GitHub Actions at 13:50 CST (5:50 UTC Monday-Friday)
Saves to: stock_report/data/afternoon_latest.json
"""
import requests, json, os, time
from datetime import datetime, timedelta
from technical_indicators import compute_stock_technical

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.eastmoney.com/"
}

def safe_get(url, params=None, timeout=20):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  WARN {url[:70]}: {e}")
        return None

def safe_text(url, extra_headers=None, timeout=15):
    try:
        h = HEADERS.copy()
        if extra_headers:
            h.update(extra_headers)
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  WARN text {url[:60]}: {e}")
        return ""

SINA_CODES_MAP = {
    "sh000001": "上证指数", "sz399001": "深证成指",
    "sz399006": "创业板指", "sh000688": "科创50"
}
WATCHLIST_MAP = {
    "sz300308": "中际旭创", "sz300502": "新易盛", "sz300394": "天孚通信",
    "sh601138": "工业富联", "sh603019": "中科曙光", "sh688256": "寒武纪",
    "sh688041": "海光信息", "sh601869": "长飞光纤", "sh600487": "亨通光电",
    "sz002230": "科大讯飞"
}

def parse_sina_quote(text, code_map):
    result = {}
    for line in (text or "").strip().split("\n"):
        if not line or '"' not in line:
            continue
        raw_code = ""
        for c in code_map:
            if c in line:
                raw_code = c
                break
        if not raw_code:
            continue
        data_str = line.split('"')[1] if '"' in line else ""
        if not data_str:
            continue
        parts = data_str.split(",")
        if len(parts) < 9:
            continue
        result[raw_code] = {
            "name": code_map[raw_code],
            "yesterday_close": parts[2],
            "open": parts[1],
            "current": parts[3],
            "high": parts[4],
            "low": parts[5],
            "volume": parts[8],
            "amount": parts[9] if len(parts) > 9 else "",
            "time": parts[31] if len(parts) > 31 else ""
        }
    return result

def fetch_realtime_indices():
    codes = ",".join(SINA_CODES_MAP.keys())
    text = safe_text(f"https://hq.sinajs.cn/list={codes}",
                     {"Referer": "https://finance.sina.com.cn"})
    return parse_sina_quote(text, SINA_CODES_MAP)

def fetch_realtime_watchlist():
    codes = ",".join(WATCHLIST_MAP.keys())
    text = safe_text(f"https://hq.sinajs.cn/list={codes}",
                     {"Referer": "https://finance.sina.com.cn"})
    result_dict = parse_sina_quote(text, WATCHLIST_MAP)
    return list(result_dict.values())

def fetch_realtime_boards(fid="f3", pz=200):
    data = safe_get("https://push2.eastmoney.com/api/qt/clist/get", {
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

def fetch_realtime_board_stocks(bk_code, board_name, top=20):
    data = safe_get("https://push2.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": top, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": f"b:{bk_code}+f:!50",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f12,f14,f15,f16,f17,f18,f20,f62,f184,f66,f84"
    })
    stocks = data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []
    return {"board_name": board_name, "bk_code": bk_code, "stocks": stocks}

def fetch_index_5day_kline():
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": "1.000001", "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": 6,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    return data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []

def fetch_realtime_capital_flow_top30():
    data = safe_get("https://push2.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": 30, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f62",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f6,f7,f8,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
    })
    return data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []


def fetch_stock_kline(secid, name, days=25):
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": days,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    klines = data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []
    return {"name": name, "secid": secid, "klines": klines}

def main():
    print(f"=== Afternoon fetch started {datetime.now().isoformat()} ===")
    result = {
        "fetch_time": datetime.now().isoformat(),
        "fetch_date": datetime.now().strftime("%Y-%m-%d"),
        "report_type": "afternoon",
        "is_friday": datetime.now().weekday() == 4
    }

    print("1. Real-time index quotes (Sina)...")
    result["realtime_indices"] = fetch_realtime_indices()
    print(f"   {len(result['realtime_indices'])} indices")

    print("2. 5-day kline (volume basis)...")
    result["index_5day_kline"] = fetch_index_5day_kline()
    print(f"   {len(result['index_5day_kline'])} bars")
    time.sleep(0.4)

    print("3. Real-time boards by change...")
    all_by_change = fetch_realtime_boards("f3", 200)
    result["all_boards_rt"] = all_by_change[:60]
    time.sleep(0.4)

    print("4. Real-time boards by capital flow...")
    result["board_capital_flows_rt"] = fetch_realtime_boards("f62", 100)
    time.sleep(0.4)

    ai_boards = filter_ai(all_by_change)
    result["ai_boards_rt"] = ai_boards
    print(f"5. AI boards: {len(ai_boards)}")
    for b in ai_boards[:10]:
        print(f"   {b.get('f14','?')}: {b.get('f3','?')}%  flow={b.get('f62','?')}")

    print("6. AI board constituents (top 6)...")
    top_ai = sorted(ai_boards, key=lambda x: float(x.get("f3", 0) or 0), reverse=True)[:6]
    result["board_stocks_rt"] = []
    for b in top_ai:
        bk, nm = b.get("f12", ""), b.get("f14", "")
        if bk:
            print(f"   {nm} ({bk})...")
            result["board_stocks_rt"].append(fetch_realtime_board_stocks(bk, nm))
            time.sleep(0.4)

    print("7. Real-time watchlist (Sina)...")
    result["watchlist_rt"] = fetch_realtime_watchlist()
    print(f"   {len(result['watchlist_rt'])} stocks")

    print("8. Real-time capital flow top30...")
    result["capital_flow_top30_rt"] = fetch_realtime_capital_flow_top30()
    print(f"   {len(result['capital_flow_top30_rt'])} stocks")

    # Fetch watchlist K-lines for technicals
    print("9. Watchlist K-lines (for technicals)...")
    WATCHLIST_SECIDS = [
        ("0.300308", "中际旭创"), ("0.300502", "新易盛"), ("0.300394", "天孚通信"),
        ("1.601138", "工业富联"), ("1.603019", "中科曙光"), ("1.688256", "寒武纪"),
        ("1.688041", "海光信息"), ("1.601869", "长飞光纤"), ("1.600487", "亨通光电"),
        ("0.002230", "科大讯飞"),
    ]
    result["watchlist_klines"] = []
    for secid, name in WATCHLIST_SECIDS:
        kl = fetch_stock_kline(secid, name)
        result["watchlist_klines"].append(kl)
        time.sleep(0.25)

    # Compute technical indicators
    print("10. Watchlist technicals...")
    flow_lookup = {}
    for s in result["capital_flow_top30_rt"]:
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

    os.makedirs("stock_report/data", exist_ok=True)
    out = "stock_report/data/afternoon_latest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== Done! {os.path.getsize(out)//1024}KB saved to {out} ===")
    print(f"is_friday={result['is_friday']}, ai_boards={len(ai_boards)}")

if __name__ == "__main__":
    main()
