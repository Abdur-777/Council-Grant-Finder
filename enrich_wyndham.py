import json, argparse, pathlib, re, datetime as dt
from urllib.parse import urlparse
from dateutil import parser as dateparse

AUDIENCE_RULES = {
    "community": r"\b(community|club|not[- ]?for[- ]?profit|nfp|volunteer|arts|sport)\b",
    "business": r"\b(business|sme|startup|company|commerciali[sz]ation)\b",
    "students": r"\b(student|scholarship|undergrad|postgrad|hdr|phd)\b",
    "research": r"\b(research|r&d|fellowship|grant round|arc|nhmrc)\b",
}

DISC_RULES = {
    "health": r"\b(health|medical|hospital|clinic|nhmrc)\b",
    "engineering": r"\b(engineer|infrastructure|transport|construction)\b",
    "environment": r"\b(environment|sustainab|recycl|waste|emission|energy)\b",
    "arts": r"\b(arts?|creative|culture)\b",
    "sport": r"\b(sport|recreation)\b",
}

def guess_jurisdiction(netloc: str) -> str | None:
    if "grants.gov.au" in netloc or "business.gov.au" in netloc or "austender" in netloc:
        return "Commonwealth"
    if netloc.endswith(".vic.gov.au") or "business.vic.gov.au" in netloc:
        return "VIC"
    if "wyndham.vic.gov.au" in netloc:
        return "VIC"
    return None

def guess_type(url: str, title_desc: str) -> str:
    if re.search(r"tender|atm|rft|rfq|rfp|contract", url, re.I) or re.search(r"\btender\b", title_desc, re.I):
        return "tender"
    return "grant"

def find_close_date(text: str) -> str | None:
    # look for “close(s|d)” / “deadline”
    m = re.search(r"(close[sd]?|deadline)[^0-9A-Za-z]{0,10}([A-Za-z0-9 ,/\-:]+)", text, re.I)
    if not m:
        return None
    try:
        return dateparse.parse(m.group(2), dayfirst=True).date().isoformat()
    except Exception:
        return None

def mentions_wyndham(text: str) -> bool:
    return "wyndham" in text.lower()

def ensure_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    return [x]

def enrich_record(r: dict, default_lga: str):
    title = (r.get("title") or "").strip()
    desc  = (r.get("description") or "").strip()
    url   = (r.get("url") or "").strip()
    blob  = f"{title} {desc}"

    netloc = urlparse(url).netloc.lower()
    r["type"] = r.get("type") or guess_type(url, blob)
    r["jurisdiction"] = r.get("jurisdiction") or guess_jurisdiction(netloc)

    # LGA
    if not r.get("lga"):
        if "wyndham.vic.gov.au" in netloc or mentions_wyndham(blob):
            r["lga"] = default_lga

    # Audience
    aud = set(ensure_list(r.get("audience")))
    for tag, pat in AUDIENCE_RULES.items():
        if re.search(pat, blob, re.I):
            aud.add(tag)
    r["audience"] = sorted(aud)

    # Discipline
    disc = set(ensure_list(r.get("discipline")))
    for tag, pat in DISC_RULES.items():
        if re.search(pat, blob, re.I):
            disc.add(tag)
    r["discipline"] = sorted(disc)

    # Close date
    if not r.get("close_date"):
        r["close_date"] = find_close_date(blob)

    # last_seen
    if not r.get("last_seen"):
        r["last_seen"] = dt.date.today().isoformat()

    # amounts: leave as-is; many sources don’t publish exact ranges
    return r

def load_any(path: pathlib.Path) -> list[dict]:
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(path.read_text(encoding="utf-8"))

def dump_any(path: pathlib.Path, rows: list[dict]):
    if path.suffix == ".jsonl":
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    else:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default="grants.json", help="Input grants.json or .jsonl")
    ap.add_argument("--out", dest="out_path", default=None, help="Output path (defaults to overwrite input)")
    ap.add_argument("--lga", dest="lga", default="Wyndham", help="Default LGA to tag when relevant")
    args = ap.parse_args()

    ip = pathlib.Path(args.in_path)
    if not ip.exists():
        raise SystemExit(f"Input not found: {ip}")

    rows = load_any(ip)
    out = [enrich_record(dict(r), args.lga) for r in rows]
    op = pathlib.Path(args.out_path) if args.out_path else ip
    dump_any(op, out)
    print(f"Enriched {len(out)} records → {op}")

if __name__ == "__main__":
    main()
