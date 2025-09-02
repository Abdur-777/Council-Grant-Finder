"""
Wyndham Grant & Tender Radar — Weekly Digest (v1)

Generates a HTML email with:
- New this week (based on `last_seen`)
- Closing soon (<= DIGEST_CLOSING_DAYS)

Reads from: grants.json OR data/grants.json OR *.jsonl
Config (optional): config/wyndham.yml

ENV (set in Render cron or locally):
  DIGEST_TO="a@b.com,c@d.com"
  DIGEST_FROM="no-reply@yourapp"
  SMTP_HOST="smtp.gmail.com"
  SMTP_PORT="587"
  SMTP_USER="username"              # optional
  SMTP_PASS="password"              # optional (use app password if Gmail)
  DIGEST_CLOSING_DAYS="14"          # default 14
  DIGEST_LIMIT="25"                 # max items per section
  DIGEST_SUBJECT_PREFIX="[Wyndham]"
  DIGEST_LGA="Wyndham"              # extra filter; if empty, no LGA filter
  DIGEST_ONLY_WYNDHAM="0"           # "1" -> only items mentioning Wyndham/LGA
Flags:
  --send  : actually send via SMTP (otherwise print preview)
  --data  : path to grants json/jsonl (optional)
"""

from __future__ import annotations
import os, json, argparse, pathlib, datetime as dt, re, html, smtplib
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText

try:
    import yaml  # optional
except Exception:
    yaml = None

# -------------------- Helpers --------------------
def _parse_iso_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s.replace("/", "-"))
    except Exception:
        # try datetime flavor
        try:
            return dt.datetime.fromisoformat(s.replace("Z","").replace("/", "-")).date()
        except Exception:
            return None

def load_config() -> Dict[str, Any]:
    cfg = {
        "council": "Wyndham City Council",
        "lga": os.getenv("DIGEST_LGA", "Wyndham"),
        "closing_window_days": int(os.getenv("DIGEST_CLOSING_DAYS", "14")),
    }
    p = pathlib.Path("config/wyndham.yml")
    if p.exists() and yaml is not None:
        try:
            y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            cfg.update({k: y.get(k, cfg.get(k)) for k in ["council","lga","closing_window_days"]})
        except Exception:
            pass
    return cfg

def find_data_file(preferred: Optional[str] = None) -> Optional[pathlib.Path]:
    candidates = [preferred] if preferred else []
    candidates += ["grants.json", "data/grants.json", "grants.jsonl", "data/grants.jsonl"]
    for c in candidates:
        if not c: 
            continue
        p = pathlib.Path(c)
        if p.exists():
            return p
    return None

def load_items(path: pathlib.Path) -> List[Dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        rows = json.loads(path.read_text(encoding="utf-8"))
    # normalize
    for r in rows:
        r.setdefault("title","")
        r.setdefault("description","")
        r.setdefault("jurisdiction", None)
        r.setdefault("lga", None)
        r.setdefault("type", None)
        r.setdefault("url", None)
        r["_close_dt"] = _parse_iso_date(r.get("close_date"))
        r["_last_seen_dt"] = _parse_iso_date(r.get("last_seen"))
        r["_days_to_close"] = (r["_close_dt"] - dt.date.today()).days if r["_close_dt"] else None
    return rows

def mentions_wyndham(r: Dict[str, Any], lga_name: str) -> bool:
    txt = f"{r.get('title','')} {r.get('description','')} {r.get('agency','')}".lower()
    return (r.get("lga") == lga_name) or (lga_name.lower() in txt) or ("wyndham" in txt)

def filter_scope(rows: List[Dict[str, Any]], lga_name: str, only_wyndham: bool) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        # Prefer VIC + Commonwealth first, but keep others unless strict flag is set
        j = (r.get("jurisdiction") or "").upper()
        keep = j in {"VIC","COMMONWEALTH"} or not j
        if only_wyndham:
            keep = mentions_wyndham(r, lga_name)
        if keep:
            out.append(r)
    return out

def new_this_week(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    today = dt.date.today()
    for r in rows:
        d = r.get("_last_seen_dt")
        if d and (today - d).days <= 7:
            out.append(r)
    # Sort newest first (by last_seen)
    return sorted(out, key=lambda x: x.get("_last_seen_dt") or dt.date(1970,1,1), reverse=True)

def closing_soon(rows: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        dd = r.get("_days_to_close")
        if dd is not None and 0 <= dd <= days:
            out.append(r)
    return sorted(out, key=lambda x: (x.get("_days_to_close") is None, x.get("_days_to_close", 9999)))

def esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""

def render_list(rows: List[Dict[str, Any]], max_items: int) -> str:
    rows = rows[:max_items]
    lis = []
    for r in rows:
        title = esc(r.get("title","Untitled"))
        url = esc(r.get("url",""))
        close = esc(r.get("close_date","?"))
        juris = esc(r.get("jurisdiction",""))
        typ = esc(r.get("type",""))
        lis.append(f"<li><a href='{url}'>{title}</a> — <i>{typ or 'opportunity'}</i>, {juris or '—'} — close {close}</li>")
    return "<ul>" + "\n".join(lis) + "</ul>"

def build_html(council: str, new_rows: List[Dict[str, Any]], closing_rows: List[Dict[str, Any]], limit:int) -> str:
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; }}
      .h {{ margin: 0 0 4px 0; }}
      .sub {{ color:#444; margin: 0 0 16px 0; }}
      .sec h3 {{ margin: 20px 0 6px 0; }}
      ul {{ margin-top: 6px; }}
      li {{ margin-bottom: 6px; line-height: 1.3; }}
      .muted {{ color:#6b7280; font-size: 12px; }}
    </style>
  </head>
  <body>
    <h2 class="h">{esc(council)} — Grants & Tenders Weekly Digest</h2>
    <p class="sub">Auto-generated summary of new and closing opportunities.</p>

    <div class="sec">
      <h3>New this week</h3>
      {render_list(new_rows, limit) if new_rows else "<p class='muted'>No new items detected this week.</p>"}
    </div>

    <div class="sec">
      <h3>Closing soon</h3>
      {render_list(closing_rows, limit) if closing_rows else "<p class='muted'>No items closing in the selected window.</p>"}
    </div>

    <p class="muted">Check details at the source link before applying. This pilot aggregates public listings; dates/amounts may change.</p>
  </body>
</html>
"""

def send_email(html_body: str, subject: str, to_list: List[str], from_addr: str,
               host: str, port: int, user: Optional[str], pw: Optional[str]) -> None:
    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_list)
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        if user:
            server.login(user, pw or "")
        server.sendmail(from_addr, to_list, msg.as_string())

# -------------------- Main --------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Actually send the email via SMTP.")
    parser.add_argument("--data", type=str, default=None, help="Path to grants.json/jsonl")
    args = parser.parse_args()

    cfg = load_config()
    data_path = find_data_file(args.d_
