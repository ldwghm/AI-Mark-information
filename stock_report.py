"""
stock_report.py — Morning report: read pre-fetched JSON + CCR analysis → render HTML → send via Resend.

Workflow:
  1. GitHub Actions fetch_market_data.py → morning_latest.json (market data + technicals)
  2. CCR trigger → morning_analysis.json (AI insights, recommendations)
  3. This script reads both → report_renderer → HTML → Resend API
"""
import requests
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from report_renderer import render_morning_report
from stock_report.report_input import load_json_input
from stock_report.pipeline_state import build_delivery_state

RESEND_API_KEY = os.environ['RESEND_API_KEY']
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = 'ldwghm/AI-Mark-information'


def gh_read_json(path):
    """Read a JSON file from the GitHub repo."""
    if not GITHUB_TOKEN:
        return None
    try:
        r = requests.get(
            f'https://api.github.com/repos/{REPO}/contents/{path}',
            headers={
                'Authorization': f'Bearer {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3.raw'
            },
            timeout=15
        )
        if r.status_code == 200:
            return json.loads(r.text)
        print(f'[gh] {path}: HTTP {r.status_code}')
    except Exception as e:
        print(f'[gh] Error reading {path}: {e}')
    return None


def gh_read_html(path):
    """Fallback: read raw HTML from repo (backwards compatible)."""
    if not GITHUB_TOKEN:
        return None
    try:
        r = requests.get(
            f'https://api.github.com/repos/{REPO}/contents/{path}',
            headers={
                'Authorization': f'Bearer {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3.raw'
            },
            timeout=15
        )
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f'[gh] Error reading HTML {path}: {e}')
    return None


def main():
    date_str = datetime.now().strftime('%Y-%m-%d')

    # Try new flow: JSON data + analysis → render
    market_data = load_json_input(
        os.environ.get('MARKET_DATA_PATH'), gh_read_json,
        'stock_report/data/morning_latest.json'
    )
    analysis = load_json_input(
        os.environ.get('ANALYSIS_PATH'), gh_read_json,
        'stock_report/data/morning_analysis.json'
    )

    if market_data:
        print(f'[main] Market data loaded: {len(market_data)} keys')
        if analysis:
            print(f'[main] Analysis loaded: {len(analysis)} keys')
        else:
            print('[main] No analysis JSON found, rendering data-only report')

        html_content = render_morning_report(market_data, analysis, date_str)
        print(f'[main] Rendered HTML: {len(html_content)} chars')
    else:
        # Fallback: read pre-built HTML (old flow, backwards compatible)
        print('[main] No market JSON, falling back to pre-built HTML')
        html_content = gh_read_html('stock_report/morning_latest.html')
        if not html_content:
            print('[main] No HTML found either, aborting')
            return

    html_path = os.environ.get('REPORT_HTML_PATH')
    if html_path:
        Path(html_path).write_text(html_content, encoding='utf-8')

    result = requests.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {RESEND_API_KEY}'},
        json={
            'from': 'A股早报 <onboarding@resend.dev>',
            'to': ['1654155512@qq.com'],
            'subject': f'A股AI板块深度日报 · {date_str}',
            'html': html_content
        },
        timeout=30
    )
    resp = result.json()
    if 'id' in resp:
        print(f'[main] Email sent! ID: {resp["id"]}')
        receipt_path = os.environ.get('DELIVERY_RECEIPT_PATH')
        if receipt_path:
            receipt = build_delivery_state(
                mode='morning', report_date=date_str, email_id=resp['id'],
                sent_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                verify_exit_code=int(os.environ.get('VERIFY_EXIT_CODE', '0')),
            )
            Path(receipt_path).write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
    else:
        print(f'[main] Email failed: {resp}')
        exit(1)


if __name__ == '__main__':
    main()
