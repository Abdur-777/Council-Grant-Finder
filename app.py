# Wyndham Grant & Tender Radar — Streamlit app (v1)
# - Reads normalized items from grants.json / grants.jsonl
# - Council Mode presets for Wyndham (VIC + Commonwealth; community & business)
# - Two smart lists: "New this week" and "Closing soon"
# - Filters: type, jurisdiction, audience, discipline, amount, text search, Wyndham-only
# - Exports: CSV + JSON (PDF optional if reportlab is installed)

import os, io, json, re, pathlib, datetime as dt
from typing import List, Dict, Any, Optional

import pandas as pd
import streamlit as st

try:
    import yaml
except Exception:
    yaml = None  # optional

# -----------------------------
# Page setup & simple theming
# -----------------------------
st.set_page_config(
    page_title="Wyndham Grant & Tender Radar",
    page_icon="🗂️",
    layout="wide"
)

# minimal CSS polish
st.markdown(
    """
    <style>
    .app-title { font-size: 1.8rem; font-weight: 700; margin-bottom: 0.2rem; }
    .app-sub { color: #555; margin-bottom: 1rem; }
    .metric-badge { display:inline-block; padding:6px 10px; border-radius:999px; background:#eef5ff; margin-right:8px; font-size:0.9rem; }
    .small-muted { color:#6b7280; font-size:0.85rem; }
    .stTabs [role="tablist"] button { padding-top: 8px; padding-bottom: 8px; }
    .sticky { position: sticky; top: 0; background: white; z-index: 5; padding-top: 0.2rem; }
    </style>
    """,
    unsafe_allow_html=True
)

# -----------------------------
# Config (YAML optional)
# -----------------------------
DEFAULT_CONFIG = {
    "council": "Wyndham City Council",
    "lga": "Wyndham",
    "audience_defaults": ["community", "business", "nonprofit"],
    "jurisdictions": ["VIC", "Commonwealth"],
    "closing_window_days": 14,
    "default_tabs": ["New this week", "Closing soon"],
}

def load_config() -> Dict[str, Any]:
    cfg_path = pathlib.Path("config/wyndham.yml")
    if cfg_path.exists() and yaml is not None:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            return {**DEFAULT_CONFIG, **loaded}
        except Exception:
            pass
    return DEFAULT_CONFIG

CONFIG = load_config()
CLOSING_DAYS_DEFAULT = int(CONFIG.get("closing_window_days", 14))

# -----------------------------
# Data loading
# -----------------------------
def _ensure_fields(r: Dict[str, Any]) -> Dict[str, Any]:
    r.setdefault("id", None)
    r.setdefault("source", None)
    r.setdefault("type", None)           # "grant" | "tender"
    r.setdefault("url", None)
    r.setdefault("title", "")
    r.setdefault("description", "")
    r.setdefault("agency", None)
    r.setdefault("jurisdiction", None)   # VIC/NSW/Commonwealth etc
    r.setdefault("lga", None)            # Wyndham etc
    r.setdefault("audience", [])         # ["community","business","students","nonprofit","research"]
    r.setdefault("discipline", [])       # ["health","engineering","arts",...]
    r.setdefault("open_date", None)
    r.setdefault("close_date", None)     # YYYY-MM-DD
    r.setdefault("status", None)
    r.setdefault("amount_min", None)
    r.setdefault("amount_max", None)
    r.setdefault("last_seen", None)
    return r

def _parse_iso_date(s: Optional[str]) -> Optional[dt.date]:
    if not s: return None
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        # Try alternative formats loosely (e.g., "2025/01/31")
        s2 = s.replace("/", "-")
        try:
            return dt.date.fromisoformat(s2)
        except Exception:
            return None

def read_items(path_preference: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Looks for 'grants.json' (list) or 'grants.jsonl' (one JSON per line).
    """
    candidates = [path_preference] if path_preference else []
    candidates += ["grants.json", "data/grants.json", "grants.jsonl", "data/grants.jsonl"]

    for p in candidates:
        if not p: 
            continue
        fp = pathlib.Path(p)
        if fp.exists():
            try:
                if fp.suffix == ".jsonl":
                    with open(fp, "r", encoding="utf-8") as f:
                        data = [json.loads(line) for line in f if line.strip()]
                else:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                items = [_ensure_fields(dict(x)) for x in data]
                # derive helpers
                for r in items:
                    r["_close_dt"] = _parse_iso_date(r.get("close_date"))
                    r["_open_dt"]  = _parse_iso_date(r.get("open_date"))
                    # days to close
                    if r["_close_dt"]:
                        r["_days_to_close"] = (r["_close_dt"] - dt.date.today()).days
                    else:
                        r["_days_to_close"] = None
                return items
            except Exception as e:
                st.error(f"Failed to parse {p}: {e}")
                return []
    return []

ITEMS = read_items()

# -----------------------------
# Helper: filtering & search
# -----------------------------
def unique_flat(list_of_lists: List[List[str]]) -> List[str]:
    s = set()
    for li in list_of_lists:
        if isinstance(li, list):
            for x in li:
                if x: s.add(str(x))
    return sorted(s)

def text_match(hay: str, q: str) -> bool:
    hay = (hay or "").lower()
    for term in re.split(r"\s+", q.strip().lower()):
        if term and term not in hay:
            return False
    return True

def apply_filters(
    rows: List[Dict[str, Any]],
    *,
    f_types: List[str],
    f_juris: List[str],
    f_aud: List[str],
    f_disc: List[str],
    f_amount_min: Optional[float],
    f_amount_max: Optional[float],
    f_text: str,
    f_wyndham_only: bool
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        # type
        if f_types and r.get("type") not in f_types:
            continue
        # jurisdiction
        if f_juris and r.get("jurisdiction") and r["jurisdiction"] not in f_juris:
            continue
        # audience
        if f_aud:
            aud_list = r.get("audience") or []
            if not any(a in aud_list for a in f_aud):
                continue
        # discipline
        if f_disc:
            disc_list = r.get("discipline") or []
            if not any(d in disc_list for d in f_disc):
                continue
        # amount
        mn, mx = r.get("amount_min"), r.get("amount_max")
        # keep items when amount unknown unless explicitly outside bounds
        if f_amount_min is not None and mx is not None and mx < f_amount_min:
            continue
        if f_amount_max is not None and mn is not None and mn > f_amount_max:
            continue
        # Wyndham-only flag (in LGA or text)
        if f_wyndham_only:
            txt = f"{r.get('title','')} {r.get('description','')} {r.get('agency','')}".lower()
            if (r.get("lga") != CONFIG.get("lga")) and ("wyndham" not in txt):
                continue
        # text search
        if f_text and not (text_match(r.get("title",""), f_text) or text_match(r.get("description",""), f_text)):
            continue
        out.append(r)
    return out

def new_this_week(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    today = dt.date.today()
    for r in rows:
        ls = r.get("last_seen")
        if not ls:
            continue
        try:
            # allow both date and datetime strings
            if "T" in ls or " " in ls:
                d = dt.datetime.fromisoformat(ls.replace("Z","")).date()
            else:
                d = dt.date.fromisoformat(ls)
            if (today - d).days <= 7:
                out.append(r)
        except Exception:
            # if parsing fails, skip
            pass
    return out

def closing_soon(rows: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        d = r.get("_days_to_close")
        if d is not None and 0 <= d <= days:
            out.append(r)
    return sorted(out, key=lambda x: x["_days_to_close"])

# -----------------------------
# Sidebar filters
# -----------------------------
with st.sidebar:
    st.header("Filters")

    # Types present
    types_present = sorted({r.get("type") for r in ITEMS if r.get("type")})
    f_types = st.multiselect(
        "Type",
        options=types_present or ["grant", "tender"],
        default=types_present or ["grant", "tender"]
    )

    # Jurisdictions
    juris_present = sorted({j for j in (r.get("jurisdiction") for r in ITEMS) if j})
    default_juris = [j for j in CONFIG.get("jurisdictions", []) if j in juris_present] or juris_present
    f_juris = st.multiselect(
        "Jurisdiction",
        options=juris_present,
        default=default_juris
    )

    # Audience
    aud_present = unique_flat([r.get("audience") for r in ITEMS])
    default_aud = [a for a in CONFIG.get("audience_defaults", []) if a in aud_present] or aud_present
    f_aud = st.multiselect(
        "Audience",
        options=aud_present,
        default=default_aud
    )

    # Discipline
    disc_present = unique_flat([r.get("discipline") for r in ITEMS])
    f_disc = st.multiselect("Discipline", options=disc_present, default=[])

    # Amount slider (based on known amounts)
    known_mins = [r["amount_min"] for r in ITEMS if isinstance(r.get("amount_min"), (int, float))]
    known_maxs = [r["amount_max"] for r in ITEMS if isinstance(r.get("amount_max"), (int, float))]
    g_min = min(known_mins) if known_mins else 0.0
    g_max = max(known_maxs) if known_maxs else 1000000.0
    f_amount_min, f_amount_max = st.slider(
        "Amount range (AUD)",
        min_value=float(g_min),
        max_value=float(g_max),
        value=(float(g_min), float(g_max)),
        step=1000.0
    )

    f_text = st.text_input("Text search (title/description)", value="")
    f_wyndham_only = st.toggle(f"Only items mentioning {CONFIG.get('lga','Wyndham')} (LGA/text)", value=False)

    st.divider()
    closing_days = st.slider("Closing window (days)", min_value=1, max_value=60, value=CLOSING_DAYS_DEFAULT, step=1)
    st.caption("Used in the “Closing soon” tab.")

# -----------------------------
# Header & metrics
# -----------------------------
st.markdown(f"<div class='app-title'>🗂️ {CONFIG.get('council','Wyndham')} — Grant & Tender Radar</div>", unsafe_allow_html=True)
st.markdown(f"<div class='app-sub small-muted'>Prefiltered for VIC & Commonwealth. Toggle filters in the sidebar.</div>", unsafe_allow_html=True)

total_count = len(ITEMS)
vic_comm_count = len([r for r in ITEMS if r.get("jurisdiction") in {"VIC", "Commonwealth"}])
st.markdown(
    f"<div class='sticky'>"
    f"<span class='metric-badge'>Total: {total_count}</span>"
    f"<span class='metric-badge'>VIC/Commonwealth: {vic_comm_count}</span>"
    f"</div>",
    unsafe_allow_html=True
)

# Apply sidebar filters to working set
FILTERED = apply_filters(
    ITEMS,
    f_types=f_types,
    f_juris=f_juris,
    f_aud=f_aud,
    f_disc=f_disc,
    f_amount_min=f_amount_min,
    f_amount_max=f_amount_max,
    f_text=f_text,
    f_wyndham_only=f_wyndham_only
)

# -----------------------------
# Utilities: display & export
# -----------------------------
DISPLAY_COLS = ["title", "type", "jurisdiction", "audience", "discipline", "close_date", "amount_min", "amount_max", "agency", "url"]

def to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    def norm_list(v):
        if isinstance(v, list): 
            return ", ".join(str(x) for x in v)
        return v
    data = []
    for r in rows:
        rec = {}
        for c in DISPLAY_COLS:
            rec[c] = norm_list(r.get(c))
        data.append(rec)
    return pd.DataFrame(data)

def export_buttons(rows: List[Dict[str, Any]], basename: str):
    df = to_df(rows)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(f"⬇️ Export CSV — {basename}", csv, file_name=f"{basename.lower().replace(' ','_')}.csv", mime="text/csv")
    # JSON export (original rows subset)
    json_bytes = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(f"⬇️ Export JSON — {basename}", json_bytes, file_name=f"{basename.lower().replace(' ','_')}.json", mime="application/json")

def show_table(rows: List[Dict[str, Any]]):
    df = to_df(rows)
    # nicer column labels
    rename = {
        "title": "Title",
        "type": "Type",
        "jurisdiction": "Jurisdiction",
        "audience": "Audience",
        "discipline": "Discipline",
        "close_date": "Closes",
        "amount_min": "Min (A$)",
        "amount_max": "Max (A$)",
        "agency": "Agency",
        "url": "URL",
    }
    df = df.rename(columns=rename)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn("URL"),
            "Min (A$)": st.column_config.NumberColumn(format="%.0f"),
            "Max (A$)": st.column_config.NumberColumn(format="%.0f"),
            "Closes": st.column_config.TextColumn(),
        }
    )

# -----------------------------
# Tabs: New this week / Closing soon / All
# -----------------------------
tab_labels = CONFIG.get("default_tabs", ["New this week", "Closing soon"])
tab_labels = list(dict.fromkeys(tab_labels + ["All"]))  # ensure "All" exists and unique

tabs = st.tabs(tab_labels)

# New this week
if "New this week" in tab_labels:
    with tabs[tab_labels.index("New this week")]:
        rows = new_this_week(FILTERED)
        st.subheader("New this week")
        st.caption(f"{len(rows)} opportunities detected by last_seen ≤ 7 days.")
        show_table(rows)
        export_buttons(rows, "wyndham_new_this_week")

# Closing soon
if "Closing soon" in tab_labels:
    with tabs[tab_labels.index("Closing soon")]:
        rows = closing_soon(FILTERED, closing_days)
        st.subheader(f"Closing in ≤ {closing_days} days")
        st.caption(f"{len(rows)} opportunities")
        show_table(rows)
        export_buttons(rows, "wyndham_closing_soon")

# All (filtered)
with tabs[tab_labels.index("All")]:
    st.subheader("All (after filters)")
    st.caption(f"{len(FILTERED)} of {len(ITEMS)}")
    show_table(FILTERED)
    export_buttons(FILTERED, "wyndham_all_filtered")

# -----------------------------
# Footer
# -----------------------------
st.markdown("---")
st.markdown(
    f"<span class='small-muted'>Data: public grant/tender listings. "
    f"This pilot surfaces opportunities for {CONFIG.get('council','Wyndham')} with simple rules. "
    f"Always verify details at the source link before applying.</span>",
    unsafe_allow_html=True
)
