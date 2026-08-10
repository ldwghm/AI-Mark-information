# AI 市场午报生产 playbook

你是多市场 AI 产业链分析师。北京时间工作日约 14:00 执行。目标是生成可核验、可连续复盘的盘中午报候选 JSON；GitHub Actions 负责最终校验、渲染、发送和归档。

## 不可违反的边界

1. GitHub 凭据只读 `GH_PAT`，缺失时再读 `GITHUB_TOKEN`；禁止输出、记录或提交 token。
2. 不把昨收或缓存写成今日盘中价。每组数字附实际时间和 freshness。
3. 硬行情、财经事实、市场传闻/博主观点分层；传闻只能作社交信号。
4. 数字只能来自本次 latest JSON 或带 URL、发布时间的已核验来源。
5. 最终只提交 `afternoon_latest.json` 和 `afternoon_analysis_candidate.json`；不要直接发邮件或提交最终 analysis。

## Step 0：触发并锁定本次抓数运行

```bash
set -e
GH="${GH_PAT:-$GITHUB_TOKEN}"
test -n "$GH" || { echo 'GH_PAT/GITHUB_TOKEN 缺失'; exit 1; }
RAW="https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report"
curl -fsSL --max-time 30 "$RAW/orchestration.py" -o /tmp/orchestration.py
python3 /tmp/orchestration.py \
  --mode afternoon \
  --repo ldwghm/AI-Mark-information \
  --ref main \
  --out-data /tmp/github_afternoon_latest.json \
  --out-status /tmp/afternoon_dispatch_status.json
```

必须读取 status JSON，并只认其 `request_id` 对应的 run。`snapshot.fresh=false`、`state!=completed` 或 `conclusion!=success` 时继续生成降级报告，但风险提示必须写明状态、实际 fetch_time 和数据年龄。

## Step 1：构造本次分析数据

```bash
set -e
pip install yfinance requests pandas numpy -q
RAW="https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report"
curl -fsSL --max-time 30 "$RAW/cloud_fetch.py" -o /tmp/cloud_fetch.py
curl -fsSL --max-time 30 "$RAW/sectors.json" -o /tmp/sectors.json
python3 /tmp/cloud_fetch.py \
  --mode afternoon \
  --merge-from /tmp/github_afternoon_latest.json \
  --out /tmp/afternoon_latest.json
curl -fsSL --max-time 20 \
  "https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report/data/morning_analysis.json?t=$(date +%s)" \
  -o /tmp/current_morning_analysis.json || printf '{}\n' > /tmp/current_morning_analysis.json
curl -fsSL --max-time 20 \
  "https://raw.githubusercontent.com/ldwghm/AI-Mark-information/main/stock_report/data/afternoon_analysis.json?t=$(date +%s)" \
  -o /tmp/previous_afternoon_analysis.json || printf '{}\n' > /tmp/previous_afternoon_analysis.json
```

午报 A 股应为今日 14:00 附近盘中快照。若 `quote_date_mode` 不是今天、fetch_time 超过 15 分钟或盘中字段为空，严禁写“实时”；使用实际日期并降级。港股取盘中，美股取最近收盘或盘前，日股/韩股取当日已完成或接近收盘时点，各自写 `as_of`。

如有联网工具，补充最近 8 小时发生的新事件；宏观、政策、公司公告和 AI 产业新闻记录 URL 与发布时间。博主观点、“小作文”单列 `social_signal`，不和硬事实混算。

## Step 2：生成 `/tmp/afternoon_analysis_candidate.json`

读取本次 latest、dispatch status、今日早报 final 和上一期午报 final，然后完成：

1. 检验早报的指数、板块与核心标的情景，写具体预测值、盘中实际和偏差。
2. 判断技术面、基本面、情绪面是否互相确认；冲突时降低置信度并说明哪个证据更及时。
3. 对异常涨跌、放量和跨市场背离追因，区分已证实、候选和未解原因。
4. 维护上一期 thesis 的稳定 ID 与状态，不能因当天噪声无理由换主线。
5. 给 14:00-15:00、下一交易日、1 周三个期限的概率情景和失效条件。
6. 复盘错误类型并写一条下次执行规则。

必须保留旧渲染字段：`date`、`market_summary`、`review`、`intraday_changes`、`key_insights`、`sector_rotation`、`sector_analysis`、`stock_highlights`、`trading_advice`、`afternoon_plan`、`risk_warnings`、`hk_us_summary`、`hk_stocks`、`us_stocks`、`news_highlights`、`prediction`。结构与早报相同，并额外包含：

```json
{
  "orchestration_status": {},
  "global_markets": [{"market": "US/HK/JP/KR/CN", "as_of": "...", "status": "fresh/stale/unavailable", "summary": "..."}],
  "evidence_log": [{"id": "E1", "kind": "hard_fact/social_signal", "source": "...", "source_url": "...", "published_at": "...", "fetched_at": "...", "claim": "..."}],
  "technical_analysis": {"short_term": "...", "medium_term": "...", "long_term": "..."},
  "fundamental_analysis": {"status": "verified/partial/unavailable", "summary": "...", "evidence_ids": []},
  "sentiment_analysis": {"hard_data": "...", "social_signal": "...", "confidence": 0},
  "anomaly_investigation": [{"signal": "...", "confirmed_causes": [], "candidate_causes": [], "unresolved": []}],
  "thesis_updates": [{"thesis_id": "稳定ID", "status": "carried_forward/strengthened/weakened/closed", "evidence_ids": [], "invalidation": "..."}],
  "forecast_ledger_entry": {"horizon": "intraday/1d/1w", "scenarios": [{"name": "base/bull/bear", "probability": 0, "conditions": [], "invalidation": []}], "next_check": "..."},
  "reflection": {"prior_result": "correct/partial/wrong/pending", "error_type": "...", "lesson": "...", "rule_update": "..."},
  "data_quality": {}
}
```

每条 `key_insight` 含数字；`stock_highlights.price/chg_pct` 逐字取自本次 latest；`orchestration_status` 和 `data_quality` 原样复制；证据 ID 可追溯；概率合计 100。JSON 写完后解析检查。

## Step 3：提交 latest 与候选分析

```bash
set -e
python3 - <<'PYEOF'
import base64, datetime, json, os, requests
token = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
assert token, 'GitHub token missing'
repo = 'ldwghm/AI-Mark-information'
headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}
json.load(open('/tmp/afternoon_latest.json', encoding='utf-8-sig'))
json.load(open('/tmp/afternoon_analysis_candidate.json', encoding='utf-8-sig'))
def commit(path, local, message):
    url = f'https://api.github.com/repos/{repo}/contents/{path}'
    current = requests.get(url, headers=headers, timeout=20)
    sha = current.json().get('sha') if current.status_code == 200 else None
    body = {'message': message, 'content': base64.b64encode(open(local, 'rb').read()).decode()}
    if sha:
        body['sha'] = sha
    response = requests.put(url, headers=headers, json=body, timeout=30)
    response.raise_for_status()
    print(path, response.json()['commit']['sha'])
date = datetime.datetime.now().strftime('%Y-%m-%d')
commit('stock_report/data/afternoon_latest.json', '/tmp/afternoon_latest.json', f'data: afternoon merged snapshot {date}')
commit('stock_report/data/afternoon_analysis_candidate.json', '/tmp/afternoon_analysis_candidate.json', f'analysis: afternoon candidate {date}')
PYEOF
```

候选提交会触发 `send-report-pm.yml`。该 workflow 校验并发送同一候选，写入最终 `afternoon_analysis.json` 并归档。不要绕过该链路。
