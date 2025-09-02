import os, json, datetime as dt, smtplib
from email.mime.text import MIMEText

TO = os.getenv("DIGEST_TO","").split(",")          # "funding@...,business@..."
FROM = os.getenv("DIGEST_FROM","no-reply@yourapp")
SMTP_HOST = os.getenv("SMTP_HOST","")
SMTP_PORT = int(os.getenv("SMTP_PORT","587"))
SMTP_USER = os.getenv("SMTP_USER","")
SMTP_PASS = os.getenv("SMTP_PASS","")
WINDOW_DAYS = int(os.getenv("DIGEST_CLOSING_DAYS","14"))

def closing_html(rows):
    lis = []
    for r in rows:
        lis.append(f"<li><b>{r['title']}</b> — close {r.get('close_date','?')} — <a href='{r['url']}'>link</a></li>")
    return "<ul>"+"".join(lis)+"</ul>"

def main():
    data = json.load(open("grants.json"))
    today = dt.date.today()
    closing = []
    newweek = []
    for r in data:
        # closing soon
        cd = r.get("close_date")
        if cd:
            try:
                d = dt.date.fromisoformat(cd)
                delta = (d - today).days
                if 0 <= delta <= WINDOW_DAYS:
                    closing.append(r)
            except Exception:
                pass
        # new this week
        try:
            seen = dt.datetime.fromisoformat(r.get("last_seen","").replace("Z","")).date()
            if (today - seen).days <= 7:
                newweek.append(r)
        except Exception:
            pass

    html = f"""
    <h3>Wyndham Grant & Tender Radar</h3>
    <p><b>New this week:</b> {len(newweek)}</p>
    {closing_html(newweek[:20])}
    <p><b>Closing in ≤{WINDOW_DAYS} days:</b> {len(closing)}</p>
    {closing_html(closing[:20])}
    <p>Full list: yourappurl/wyndham</p>
    """
    if not TO or not SMTP_HOST:
        print("DIGEST preview:", html); return

    msg = MIMEText(html, "html")
    msg["Subject"] = "Wyndham – Grants & Tenders Weekly Digest"
    msg["From"] = FROM
    msg["To"] = ", ".join(TO)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        if SMTP_USER: server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM, TO, msg.as_string())

if __name__ == "__main__":
    main()
