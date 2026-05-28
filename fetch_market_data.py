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

def fetch_index_kline(secid, name, days=25):
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": days,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    klines = data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []
    return {"name": name, "secid": secid, "klines": klines}

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

def fetch_board_stocks(bk_code, board_name, top=25):
    data = safe_get("https://push2delay.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": top, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": f"b:{bk_code}+f:!50",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f22,f23,f62,f184,f66,f84"
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

def fetch_stock_kline(secid, name, days=25):
    data = safe_get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": days,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    })
    klines = data["data"]["klines"] if data and data.get("data") and data["data"].get("klines") else []
    return {"name": name, "secid": secid, "klines": klines}

def fetch_northbound():
    data = safe_get("https://datacenter-web.eastmoney.com/api/data/v1/get", {
        "reportName": "RPT_MUTUAL_QUOTA",
        "columns": "TRADE_DATE,MUTUAL_TYPE,MUTUAL_TYPE_NAME,QUOTA_BALANCE,QUOTA_USED,NET_BUY_AMT,BUY_AMT,SELL_AMT",
        "filter": '(MUTUAL_TYPE+in+("001","003"))',
        "pageNumber": 1, "pageSize": 20,
        "sortTypes": -1, "sortColumns": "TRADE_DATE", "client": "WEB"
    })
    return data["result"]["data"] if data and data.get("result") and data["result"].get("data") else []

def fetch_dragon_tiger():
    week_ago = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    data = safe_get("https://datacenter-web.eastmoney.com/api/data/v1/get", {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME,CLOSE_PRICE,CHANGE_RATE,TRADE_DATE,EXPLANATION,OPERATEDEPT_NAME,BUY_AMT,SELL_AMT,NET_BUY_AMT,RANK,OPERATEDEPT_TYPE",
        "filter": f"(TRADE_DATE>='{week_ago}')",
        "pageNumber": 1, "pageSize": 100,
        "sortTypes": -1, "sortColumns": "TRADE_DATE,NET_BUY_AMT", "client": "WEB"
    })
    return data["result"]["data"] if data and data.get("result") and data["result"].get("data") else []

def fetch_margin_trading():
    data = safe_get("https://datacenter-web.eastmoney.com/api/data/v1/get", {
        "reportName": "RPTA_WEB_RZRQ_GGMX",
        "columns": "SECUCODE,SECURITY_NAME,RZYE,RZMRE,RZCHE,RQYE,RQMCL,RZRQYE,CHANGE_RATE",
        "pageNumber": 1, "pageSize": 200,
        "sortTypes": -1, "sortColumns": "RZYE", "client": "WEB"
    })
    return data["result"]["data"] if data and data.get("result") and data["result"].get("data") else []

def main():
    print(f"=== Morning fetch started {datetime.now().isoformat()} ===")
    result = {
        "fetch_time": datetime.now().isoformat(),
        "fetch_date": datetime.now().strftime("%Y-%m-%d"),
        "report_type": "morning"
    }

    print("1. Index K-lines...")
    result["indices"] = {
        "shanghai": fetch_index_kline("1.000001", "上证指数"),
        "shenzhen": fetch_index_kline("0.399001", "深证成指"),
        "chinext":  fetch_index_kline("0.399006", "创业板指"),
        "star50":   fetch_index_kline("1.000688", "科创50"),
    }
    for k, v in result["indices"].items():
        print(f"   {v['name']}: {len(v['klines'])} bars")
    time.sleep(0.5)

    print("1b. Index technicals...")
    result["index_technicals"] = {}
    for k, v in result["indices"].items():
        tech = compute_stock_technical(v["klines"])
        if tech:
            result["index_technicals"][k] = tech
            print(f"   {v[chr(39)+chr(110)+chr(97)+chr(109)+chr(101)+chr(39)]}: {tech[chr(39)+chr(109)+chr(97)+chr(95)+chr(116)+chr(114)+chr(101)+chr(110)+chr(100)+chr(39)]}")

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
    top_ai = sorted(ai_boards, key=lambda x: float(x.get("f3", 0) or 0), reverse=True)[:8]
    result["board_stocks"] = []
    for b in top_ai:
        bk, nm = b.get("f12", ""), b.get("f14", "")
        if bk:
            print(f"   {nm} ({bk})...")
            result["board_stocks"].append(fetch_board_stocks(bk, nm))
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
        print(f"   {name}: {len(kl['klines'])} bars")
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

        print("8. Northbound capital...")
    result["northbound"] = fetch_northbound()
    print(f"   {len(result['northbound'])} records")
    time.sleep(0.4)

    print("9. Dragon tiger...")
    result["dragon_tiger"] = fetch_dragon_tiger()
    print(f"   {len(result['dragon_tiger'])} records")
    time.sleep(0.4)

    print("10. Margin trading...")
    result["margin_trading"] = fetch_margin_trading()
    print(f"   {len(result['margin_trading'])} records")

    os.makedirs("stock_report/data", exist_ok=True)
    out = "stock_report/data/morning_latest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== Done! {os.path.getsize(out)//1024}KB saved to {out} ===")

if __name__ == "__main__":
    main()
