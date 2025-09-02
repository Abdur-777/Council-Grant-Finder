import json, datetime as dt, pathlib

SEED = [
  # Replace titles/urls with the exact Wyndham/VIC/Commonwealth pages you want visible
  {"title":"Wyndham Community Grants (example)", "url":"https://www.wyndham.vic.gov.au/..."},
  {"title":"Business Victoria – Grants (example)", "url":"https://business.vic.gov.au/..."},
  {"title":"GrantConnect – Current Opportunities (example)", "url":"https://www.grants.gov.au/go/list"},
  {"title":"Business.gov.au – Grants & Programs (example)", "url":"https://business.gov.au/grants-and-programs"},
]

def make_record(t,u, juris=None):
    juris = juris or ("VIC" if ".vic.gov.au" in u else "Commonwealth" if "grants.gov.au" in u or "business.gov.au" in u else None)
    return {
        "id": f"seed-{abs(hash((t,u)))%10**8}",
        "source": "seed",
        "type": "grant",
        "url": u,
        "title": t,
        "description": "",
        "agency": None,
        "jurisdiction": juris,
        "lga": "Wyndham" if "wyndham.vic.gov.au" in u else None,
        "audience": ["community"] if "wyndham.vic.gov.au" in u else ["business"],
        "discipline": [],
        "open_date": None,
        "close_date": None,
        "status": "open",
        "amount_min": None,
        "amount_max": None,
        "last_seen": dt.date.today().isoformat()
    }

def load(path):
    p = pathlib.Path(path)
    if not p.exists(): return []
    return json.loads(p.read_text(encoding="utf-8"))

def save(path, rows):
    pathlib.Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    cur = load("grants.json")
    ids = {r.get("id") for r in cur}
    new = [make_record(s["title"], s["url"]) for s in SEED]
    out = cur + [r for r in new if r["id"] not in ids]
    save("grants.json", out)
    print(f"Added {len(out)-len(cur)} seed records. Total now {len(out)}.")

if __name__ == "__main__":
    main()
