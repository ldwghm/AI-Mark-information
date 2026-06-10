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

# 10-sector / 51-stock universe shared with the CCR afternoon analysis prompt
SECTOR_UNIVERSE = {
    "光通信/CPO/光模块": [("300308", "中际旭创"), ("300502", "新易盛"), ("300394", "天孚通信"),
                          ("002281", "光迅科技"), ("688498", "源杰科技"), ("300620", "光库科技")],
    "光纤光缆": [("601869", "长飞光纤"), ("600487", "亨通光电"), ("600522", "中天科技"), ("600498", "烽火通信")],
    "半导体设备/制造/AI芯片": [("002371", "北方华创"), ("688012", "中微公司"), ("688072", "拓荆科技"),
                               ("688981", "中芯国际"), ("688347", "华虹公司"), ("688256", "寒武纪"), ("688041", "海光信息")],
    "存储": [("603986", "兆易创新"), ("688008", "澜起科技"), ("301308", "江波龙"),
             ("688525", "佰维存储"), ("001309", "德明利")],
    "PCB": [("300476", "胜宏科技"), ("002463", "沪电股份"), ("002916", "深南电路"),
            ("600183", "生益科技"), ("002938", "鹏鼎控股")],
    "玻纤/电子布": [("600176", "中国巨石"), ("002080", "中材科技"), ("603256", "宏和科技"),
                    ("301526", "国际复材"), ("605006", "山东玻纤")],
    "算力租赁/AIDC": [("300442", "润泽科技"), ("300738", "奥飞数据"), ("300857", "协创数据"),
                      ("603629", "利通电子"), ("300383", "光环新网")],
    "液冷": [("002837", "英维克"), ("301018", "申菱环境"), ("300499", "高澜股份"),
             ("300602", "飞荣达"), ("872808", "曙光数创")],
    "高速铜连接": [("002130", "沃尔核材"), ("300913", "兆龙互连"), ("300563", "神宇股份"),
                   ("688800", "瑞可达"), ("605277", "新亚电子")],
    "AI服务器": [("601138", "工业富联"), ("000977", "浪潮信息"), ("603019", "中科曙光"), ("000938", "紫光股份")],
}

HK_WATCH = [("00700", "腾讯"), ("09988", "阿里巴巴"), ("03690", "美团"),
            ("09999", "网易"), ("01024", "快手"), ("00020", "商汤")]
US_WATCH = [("105.NVDA", "NVIDIA"), ("105.MSFT", "Microsoft"), ("105.GOOGL", "Alphabet"),
            ("105.META", "Meta"), ("105.AMD", "AMD"), ("105.AVGO", "博通"),
            ("106.TSM", "台积电"), ("105.SMCI", "SuperMicro"), ("105.PLTR", "Palantir")]

def em_secid(code):
    """Eastmoney secid: market 1 = SH(6/9*), 0 = SZ/BJ."""
    return ("1." if code[0] in "69" else "0.") + code

def fetch_quotes_by_secids(secids):
    """Batch real-time quotes via eastmoney ulist API. Returns {code: fields}."""
    out = {}
    for i in range(0, len(secids), 40):
        data = safe_get("https://push2.eastmoney.com/api/qt/ulist.np/get", {
            "fltt": 2, "invt": 2, "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "secids": ",".join(secids[i:i + 40]),
            "fields": "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f62"
        })
        diff = data["data"]["diff"] if data and data.get("data") and data["data"].get("diff") else []
        for s in diff:
            code = str(s.get("f12", ""))
            if code and s.get("f2") not in (None, "-", 0):
                out[code] = s
        time.sleep(0.3)
    return out

def fetch_sector_watchlist(today_str):
    """Fetch the full 51-stock universe and aggregate per-sector stats."""
    code_sector = {}
    code_name = {}
    secids = []
    for sec, lst in SECTOR_UNIVERSE.items():
        for code, name in lst:
            code_sector[code] = sec
            code_name[code] = name
            secids.append(em_secid(code))

    quotes = fetch_quotes_by_secids(secids)
    watchlist = []
    for code, sec in code_sector.items():
        q = quotes.get(code)
        if not q:
            continue
        watchlist.append({
            "name": code_name[code], "code": code, "sector": sec,
            "current": q.get("f2"), "change_pct": q.get("f3"),
            "high": q.get("f15"), "low": q.get("f16"),
            "open": q.get("f17"), "yesterday_close": q.get("f18"),
            "volume": q.get("f5"), "amount": q.get("f6"),
            "main_net_flow": q.get("f62"), "data_date": today_str,
        })

    sectors = []
    for sec in SECTOR_UNIVERSE:
        rows = [w for w in watchlist if w["sector"] == sec and isinstance(w.get("change_pct"), (int, float))]
        if not rows:
            continue
        chgs = [r["change_pct"] for r in rows]
        leader = max(rows, key=lambda r: r["change_pct"])
        laggard = min(rows, key=lambda r: r["change_pct"])
        flows = [r["main_net_flow"] for r in rows if isinstance(r.get("main_net_flow"), (int, float))]
        sectors.append({
            "sector": sec,
            "avg_chg": round(sum(chgs) / len(chgs), 2),
            "up": len([c for c in chgs if c > 0]),
            "down": len([c for c in chgs if c < 0]),
            "total": len(rows),
            "leader": {"name": leader["name"], "code": leader["code"], "chg_pct": leader["change_pct"]},
            "laggard": {"name": laggard["name"], "code": laggard["code"], "chg_pct": laggard["change_pct"]},
            "total_main_flow": round(sum(flows), 0) if flows else None,
            "stocks": [{"code": r["code"], "name": r["name"], "chg_pct": r["change_pct"]}
                       for r in sorted(rows, key=lambda x: -x["change_pct"])],
        })
    sectors.sort(key=lambda s: -s["avg_chg"])
    return watchlist, sectors

def fetch_hk_us():
    """HK + US AI leaders via eastmoney (works on Actions runners)."""
    hk_secids = ["116." + c for c, n in HK_WATCH]
    hk_names = {c: n for c, n in HK_WATCH}
    hk_quotes = fetch_quotes_by_secids(hk_secids)
    hk = [{"code": c[-4:] + ".HK", "name": hk_names[c],
           "price": q.get("f2"), "chg": q.get("f3"), "src": "eastmoney"}
          for c, q in ((c, hk_quotes.get(c)) for c, n in HK_WATCH) if q]

    us_names = {s.split(".")[1]: n for s, n in US_WATCH}
    us_quotes = fetch_quotes_by_secids([s for s, n in US_WATCH])
    us = [{"code": t, "name": us_names[t], "price": q.get("f2"), "chg": q.get("f3"), "src": "eastmoney"}
          for t, q in ((t, us_quotes.get(t)) for t in us_names) if q]
    return hk, us

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
    # GitHub Actions runners are UTC; report dates in Beijing time
    bjt_now = datetime.utcnow() + timedelta(hours=8)
    today_str = bjt_now.strftime("%Y-%m-%d")
    print(f"=== Afternoon fetch started {datetime.now().isoformat()} (BJT {bjt_now.isoformat()}) ===")
    result = {
        "fetch_time": datetime.now().isoformat(),
        "fetch_date": today_str,
        "expected_data_date": today_str,
        "report_type": "afternoon",
        "is_friday": bjt_now.weekday() == 4
    }

    print("1. Real-time index quotes (Sina)...")
    result["realtime_indices"] = fetch_realtime_indices()
    # Add numeric price/chg fields so the renderer doesn't show +0.00%
    for code, d in result["realtime_indices"].items():
        try:
            cur, prev = float(d["current"]), float(d["yesterday_close"])
            d["price"] = round(cur, 2)
            d["chg"] = round((cur - prev) / prev * 100, 2) if prev else 0.0
            d["change_pct"] = d["chg"]
        except (ValueError, KeyError, ZeroDivisionError):
            pass
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

    print("7. Sector watchlist (51 stocks / 10 sectors, eastmoney)...")
    watchlist, sectors = fetch_sector_watchlist(today_str)
    result["watchlist_rt"] = watchlist
    result["sectors"] = sectors
    print(f"   {len(watchlist)} stocks, {len(sectors)} sectors")
    for s in sectors:
        print(f"   {s['sector']}: {s['avg_chg']:+.2f}% 领涨{s['leader']['name']}")
    if not watchlist:
        print("   WARN eastmoney watchlist empty, falling back to Sina 10-stock list")
        result["watchlist_rt"] = fetch_realtime_watchlist()
        for w in result["watchlist_rt"]:
            try:
                cur, prev = float(w["current"]), float(w["yesterday_close"])
                w["change_pct"] = round((cur - prev) / prev * 100, 2) if prev else 0.0
            except (ValueError, KeyError):
                pass

    print("8. Real-time capital flow top30...")
    result["capital_flow_top30_rt"] = fetch_realtime_capital_flow_top30()
    print(f"   {len(result['capital_flow_top30_rt'])} stocks")

    # Fetch watchlist K-lines for technicals (full sector universe)
    print("9. Watchlist K-lines (for technicals)...")
    WATCHLIST_SECIDS = [(em_secid(code), name)
                        for lst in SECTOR_UNIVERSE.values() for code, name in lst]
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

    rt_lookup = {w["code"]: w for w in result["watchlist_rt"] if w.get("code")}
    result["watchlist_technicals"] = []
    for kl in result["watchlist_klines"]:
        secid = kl.get("secid", "")
        code = secid.split(".")[-1] if "." in secid else secid
        net_flow = flow_lookup.get(code)
        tech = compute_stock_technical(kl["klines"], net_flow)
        entry = {"name": kl["name"], "secid": secid, "code": code}
        rt = rt_lookup.get(code)
        if rt:
            entry["sector"] = rt.get("sector")
        if tech:
            entry.update(tech)
            entry["close"] = tech.get("price")  # renderer reads 'close'
            if rt and isinstance(rt.get("current"), (int, float)):
                entry["close"] = rt["current"]
                entry["chg_pct"] = rt.get("change_pct", tech.get("chg_pct"))
        result["watchlist_technicals"].append(entry)

    print("11. HK/US AI leaders (eastmoney)...")
    hk, us = fetch_hk_us()
    result["hk_stocks"] = hk
    result["us_stocks"] = us
    print(f"   hk={len(hk)} us={len(us)}")

    result["data_freshness"] = {
        "expected_date": today_str,
        "quote_date_mode": today_str if result["watchlist_rt"] else None,
        "stale_quote_count": 0,
        "watchlist_count": len(result["watchlist_rt"]),
        "sectors_count": len(result.get("sectors", [])),
        "hk_count": len(hk), "us_count": len(us),
    }

    os.makedirs("stock_report/data", exist_ok=True)
    out = "stock_report/data/afternoon_latest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== Done! {os.path.getsize(out)//1024}KB saved to {out} ===")
    print(f"is_friday={result['is_friday']}, ai_boards={len(ai_boards)}")

if __name__ == "__main__":
    main()
