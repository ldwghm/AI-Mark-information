import requests, os, sys
from datetime import datetime

RESEND_API_KEY = os.environ["RESEND_API_KEY"]
RECIPIENT = "1654155512@qq.com"

def main():
    html_path = os.path.join(os.path.dirname(__file__), "daily_english", "latest.html")
    if not os.path.exists(html_path):
        print(f"ERROR: {html_path} not found")
        sys.exit(1)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    if len(html.strip()) < 100:
        print("ERROR: HTML content too short")
        sys.exit(1)

    today = datetime.utcnow().strftime("%Y-%m-%d")

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "from": "English Practice <onboarding@resend.dev>",
            "to": [RECIPIENT],
            "subject": f"📚 每日英语练习 · {today}",
            "html": html,
        },
        timeout=15
    )
    result = resp.json()
    if "id" in result:
        print(f"Email sent! ID: {result['id']}")
    else:
        print(f"Email failed: {result}")
        sys.exit(1)

if __name__ == "__main__":
    main()
