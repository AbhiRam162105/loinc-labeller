#!/usr/bin/env python3
"""
Streamlit labelling tool for candidates_diagnosis*.json.

An external labeller:
  1. enters their email (once),
  2. reviews each test + the claude/gpt/gemini picks (NO candidates table),
  3. records the correct LOINC code/label,
  4. clicks "Done & next" — the row is written to a local CSV immediately.

Run:
    streamlit run diagnosis_labeller.py
    # or:
    streamlit run diagnosis_labeller.py -- --json "/path/file.json" --csv /path/out.csv
"""
import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# All storage is LOCAL: resolved next to this script so it works wherever it runs.
APP_DIR = Path(__file__).resolve().parent
# slim data file (test + picks + long names of picked codes) committed with the app;
# falls back to the full candidates JSON if the slim file isn't present.
JSON_CANDIDATES = ["diagnosis_data_slim.json", "candidates_diagnosis (3).json"]


def _default_json() -> Path:
    """Prefer a data file next to the app; fall back to the full Downloads JSON."""
    for nm in JSON_CANDIDATES:
        local = APP_DIR / nm
        if local.exists():
            return local
    legacy = Path("/home/ryan-reid/Downloads") / "candidates_diagnosis (3).json"
    return legacy if legacy.exists() else APP_DIR / JSON_CANDIDATES[0]


DEFAULT_JSON = _default_json()
# CSV always written to local storage beside the app (override with --csv).
DEFAULT_CSV = APP_DIR / "diagnosis_labels.csv"

MODELS = ["claude", "gpt", "gemini"]
# written to correct_loinc when the labeller can't pin a single code
AMBIGUOUS = "ambiguous_multiple"
AMBIGUOUS_LABEL = ("Not enough information to determine a unique LOINC code "
                   "(there are multiple possible options)")
CSV_FIELDS = ["test_name", "correct_loinc", "correct_label", "labeller_email",
              "claude_pick", "gpt_pick", "gemini_pick", "timestamp"]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(DEFAULT_JSON))
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    args, _ = ap.parse_known_args(sys.argv[1:])
    return args


def is_none(v) -> bool:
    return v is None or (isinstance(v, str)
                         and v.strip().lower() in ("", "none", "null", "n/a", "na"))


def classify(picks: dict):
    vals = [picks.get(m) for m in MODELS]
    any_none = any(is_none(v) for v in vals)
    unanimous = (len({(v.strip() if isinstance(v, str) else v) for v in vals}) == 1
                 and not any_none)
    return (not unanimous) or any_none, unanimous, any_none


@st.cache_data(show_spinner="Loading JSON…")
def load(path: str):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    names = list(data.keys())
    meta = {}
    for name in names:
        flagged, unanimous, any_none = classify(data[name].get("picks", {}))
        meta[name] = {"flagged": flagged, "unanimous": unanimous, "any_none": any_none}
    return data, names, meta


def code_to_name(entry: dict) -> dict:
    # slim data carries pick_names directly; full data has a candidates list
    if entry.get("candidates"):
        return {c.get("loinc_code"): c.get("long_name", "")
                for c in entry["candidates"]}
    return entry.get("pick_names", {})


# ---------------------------------------------------------------- CSV backend
def read_labels(csv_path: str) -> dict:
    """Return {test_name: row dict}. Read fresh each run so progress is live."""
    p = Path(csv_path)
    if not p.exists():
        return {}
    out = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["test_name"]] = row
    return out


def write_label(csv_path: str, row: dict):
    """Insert/replace the row for this test_name and persist immediately."""
    labels = read_labels(csv_path)
    labels[row["test_name"]] = row
    p = Path(csv_path)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in labels.values():
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    tmp.replace(p)  # atomic


# ------------------------------------------------------- Google Sheets backend
def gsheet_configured() -> bool:
    try:
        return ("gcp_service_account" in st.secrets
                and bool(st.secrets.get("gsheet_url") or st.secrets.get("gsheet_id")))
    except Exception:
        return False


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@st.cache_resource(show_spinner="Connecting to Google Sheet…")
def _gsheet():
    """Authorise via the service account in secrets, return (worksheet, sheet_url)."""
    import gspread
    from google.oauth2.service_account import Credentials

    info = dict(st.secrets["gcp_service_account"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    gc = gspread.authorize(creds)

    ref = st.secrets.get("gsheet_url") or st.secrets.get("gsheet_id")
    sh = gc.open_by_url(ref) if str(ref).startswith("http") else gc.open_by_key(ref)
    try:
        ws = sh.worksheet("labels")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("labels", rows=2000, cols=len(CSV_FIELDS))
    if ws.row_values(1) != CSV_FIELDS:
        ws.update([CSV_FIELDS], "A1", value_input_option="USER_ENTERED")
    return ws, sh.url


def gsheet_load() -> tuple[dict, dict]:
    """Return (labels {name: row}, rownum {name: sheet_row})."""
    ws, _ = _gsheet()
    labels, rownum = {}, {}
    for i, r in enumerate(ws.get_all_records(), start=2):  # data starts at row 2
        name = r.get("test_name")
        if name:
            labels[name] = {k: ("" if r.get(k) is None else str(r.get(k)))
                            for k in CSV_FIELDS}
            rownum[name] = i
    return labels, rownum


def gsheet_write(rownum: dict, row: dict):
    """Upsert the row by test_name and sync to the sheet immediately."""
    ws, _ = _gsheet()
    values = [row.get(k, "") for k in CSV_FIELDS]
    name = row["test_name"]
    if name in rownum:
        r = rownum[name]
        rng = f"A{r}:{_col_letter(len(CSV_FIELDS))}{r}"
        ws.update([values], rng, value_input_option="USER_ENTERED")
    else:
        ws.append_row(values, value_input_option="USER_ENTERED",
                      table_range="A1")
        rownum[name] = len(rownum) + 2


# ------------------------------------------------------- unified dispatch
def load_labels(args) -> dict:
    """All saved labels. Google Sheet if configured, else local CSV."""
    if gsheet_configured():
        if "gs_cache" not in st.session_state:
            cache, rownum = gsheet_load()
            st.session_state.gs_cache = cache
            st.session_state.gs_rownum = rownum
        return st.session_state.gs_cache
    return read_labels(args.csv)


def save_label(args, row: dict):
    """Persist one label immediately (sync after every change)."""
    if gsheet_configured():
        gsheet_write(st.session_state.gs_rownum, row)
        st.session_state.gs_cache[row["test_name"]] = {
            k: row.get(k, "") for k in CSV_FIELDS}
    else:
        write_label(args.csv, row)


def main():
    args = parse_args()
    st.set_page_config(page_title="LOINC Labeller", layout="wide")

    if not Path(args.json).exists():
        st.error(f"JSON not found: {args.json}")
        st.stop()

    data, all_names, meta = load(args.json)

    # ---------------- sidebar: identity + filter ----------------
    st.sidebar.title("🏷️ LOINC Labeller")
    email = st.sidebar.text_input("Your email *", value=st.session_state.get("email", ""),
                                  placeholder="labeller@example.com")
    st.session_state.email = email
    if not email or "@" not in email:
        st.sidebar.warning("Enter your email to start labelling.")

    # storage status + link to the live Google Sheet
    if gsheet_configured():
        try:
            _, sheet_url = _gsheet()
            st.sidebar.success("Storage: Google Sheet — synced on every save")
            st.sidebar.markdown(f"[📄 Open Google Sheet]({sheet_url})")
        except Exception as e:
            st.sidebar.error(f"Google Sheet error: {e}")
            st.stop()
    else:
        st.sidebar.info("Storage: local CSV (set secrets to use Google Sheet)")

    st.sidebar.divider()

    view = st.sidebar.radio(
        "Tests to label",
        ["Disagreement OR none", "Has a `none` pick", "Disagreement only (no none)",
         "Unanimous", "All"],
        index=0,
    )

    def keep(name):
        m = meta[name]
        if view == "Disagreement OR none":
            return m["flagged"]
        if view == "Has a `none` pick":
            return m["any_none"]
        if view == "Disagreement only (no none)":
            return m["flagged"] and not m["any_none"]
        if view == "Unanimous":
            return m["unanimous"]
        return True

    names = [a for a in all_names if keep(a)]

    labels = load_labels(args)                # Google Sheet if configured, else CSV
    done_set = set(labels.keys())
    n_done_view = sum(1 for a in names if a in done_set)

    only_unlabelled = st.sidebar.checkbox("Hide already-labelled", False)
    if only_unlabelled:
        names = [a for a in names if a not in done_set]

    query = st.sidebar.text_input("Search test name", "")
    if query:
        names = [a for a in names if query.lower() in a.lower()]

    if not names:
        st.success("🎉 Nothing left to label in this view.")
        st.stop()

    n = len(names)
    st.sidebar.progress(n_done_view / max(1, len([a for a in all_names if keep(a)])))
    st.sidebar.caption(f"Labelled in view: **{n_done_view:,}** · "
                       f"showing **{n:,}** · total saved: **{len(done_set):,}**")

    if labels:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in labels.values():
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
        st.sidebar.download_button("⬇ Download labels CSV", buf.getvalue().encode("utf-8"),
                                   file_name="diagnosis_labels.csv", mime="text/csv")

    # ---------------- nav ----------------
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    st.session_state.idx = min(st.session_state.idx, n - 1)

    sel = st.sidebar.selectbox(
        "Jump to test", names,
        index=st.session_state.idx,
        format_func=lambda a: ("✅ " if a in done_set else "• ") + a,
    )
    if names.index(sel) != st.session_state.idx:
        st.session_state.idx = names.index(sel)
        st.session_state.cur_test = None  # force field reset

    c1, c2, c3 = st.columns([1, 1, 6])
    with c1:
        if st.button("◀ Prev", use_container_width=True):
            st.session_state.idx = (st.session_state.idx - 1) % n
            st.session_state.cur_test = None
            st.rerun()
    with c2:
        if st.button("Skip ▶", use_container_width=True):
            st.session_state.idx = (st.session_state.idx + 1) % n
            st.session_state.cur_test = None
            st.rerun()

    idx = st.session_state.idx
    name = names[idx]
    entry = data[name]
    picks = entry.get("picks", {})
    lut = code_to_name(entry)

    # reset input fields when the current test changes
    if st.session_state.get("cur_test") != name:
        st.session_state.cur_test = name
        prev = labels.get(name, {})
        prev_code = prev.get("correct_loinc", "")
        is_ambiguous = (prev_code == AMBIGUOUS)
        # reset the ambiguous checkbox for every new item (unchecked unless this
        # item was previously saved as ambiguous)
        st.session_state.ambiguous_flag = is_ambiguous
        st.session_state.correct_code = "" if is_ambiguous else prev_code
        st.session_state.correct_label = prev.get("correct_label", "")

    with c3:
        tag = "✅ already labelled" if name in done_set else "🆕 unlabelled"
        st.markdown(f"**{idx + 1} / {n}** · {tag}")

    # ---------------- main: test + picks (NO candidates table) ----------------
    st.header(name)
    t = entry.get("test", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("Units", t.get("units") or "—")
    m2.metric("System", t.get("system") or "—")
    m3.metric("Disagreement", "yes" if meta[name]["flagged"] else "no")

    st.subheader("Model picks (reference)")
    cols = st.columns(3)
    for col, mdl in zip(cols, MODELS):
        v = picks.get(mdl)
        with col:
            if is_none(v):
                col.markdown(f"**{mdl}**\n\n🚫 _none_")
            else:
                col.markdown(f"**{mdl}**\n\n`{v}`")
                if lut.get(v):
                    col.caption(lut[v])
            # quick-fill button
            if not is_none(v):
                if col.button(f"Use {mdl}'s code", key=f"use_{mdl}",
                              use_container_width=True):
                    st.session_state.correct_code = v
                    st.session_state.correct_label = lut.get(v, "")
                    st.rerun()

    st.divider()
    st.subheader("✏️ Correct label")
    ambiguous = st.checkbox(f"❓ {AMBIGUOUS_LABEL}", key="ambiguous_flag")
    lc, rc = st.columns(2)
    with lc:
        code = st.text_input("Correct LOINC code", key="correct_code",
                             disabled=ambiguous,
                             placeholder="e.g. 22310-7")
    with rc:
        st.text_input("Correct label / long name (optional)", key="correct_label",
                      disabled=ambiguous, placeholder="human-readable name")

    final_code = AMBIGUOUS if ambiguous else st.session_state.correct_code.strip()

    can_save = bool(email and "@" in email) and bool(final_code)
    b1, b2 = st.columns([1, 5])
    with b1:
        done = st.button("✅ Done & next", type="primary", use_container_width=True,
                         disabled=not can_save)
    if not email or "@" not in email:
        b2.caption("⬅ enter a valid email in the sidebar first")
    elif not final_code:
        b2.caption("⬅ enter a LOINC code, or tick the 'not enough information' box")

    if done:
        row = {
            "test_name": name,
            "correct_loinc": final_code,
            "correct_label": "" if ambiguous else st.session_state.correct_label.strip(),
            "labeller_email": email.strip(),
            "claude_pick": picks.get("claude"),
            "gpt_pick": picks.get("gpt"),
            "gemini_pick": picks.get("gemini"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        save_label(args, row)                    # synced immediately
        st.toast(f"Saved “{name}” → {final_code}", icon="✅")
        st.session_state.idx = (idx + 1) % n
        st.session_state.cur_test = None
        st.rerun()


if __name__ == "__main__":
    main()
