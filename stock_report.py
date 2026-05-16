import requests
import os
import base64
import json
from datetime import datetime

# read_and_send mode - reads HTML from repo and sends via Resend
RESEND_API_KEY = os.environ['RESEND_API_KEY']
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = 'ldwghm/AI-Mark-information'

def main():
    # Read HTML from repo (latest deep analysis report)
    resp = requests.get(
        f'https://api.github.com/repos/{REPO}/contents/stock_report/morning_latest.html',
        headers={
            'Authorization': f'Bearer {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3.raw'
        },
        timeout=15
    )
    if resp.status_code != 200:
        print(f'Failed to read HTML: {resp.status_code} - {resp.text[:200]}')
        return
    html_content = resp.text

    date_str = datetime.now().strftime('%Y-%m-%d')

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
    print(f'Send result: {result.status_code} - {result.text[:300]}')

if __name__ == '__main__':
    main()
