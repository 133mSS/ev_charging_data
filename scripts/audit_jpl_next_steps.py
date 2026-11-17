"""Read-only diagnostics for JPL API completeness, near-miss session IDs and time coverage.

Run from the project root:
    python scripts/audit_jpl_next_steps.py

Copy this file into the project's scripts/ directory first.
It does not modify source data or call the full extraction endpoint.
It makes one lightweight API request (max_results=1) to read the current _meta.total.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_config import (  # noqa: E402
    RAW_API_FILE,
    CLEAN_SESSIONS_FILE,
    SESSION_MAPPING_FILE,
    SESSION_QUALITY_FILE,
    SITE_ID,
)

BASE_URL = "https://ev.caltech.edu/api/v1/"

API_ID_RE = re.compile(r"^(?P<station>.+)_(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)$")
STATIC_ID_RE = re.compile(r"^(?P<station>.+)-(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d+)$")


def parse_api_id(value: object) -> tuple[str | None, pd.Timestamp | pd.NaT]:
    s = str(value or "")
    m = API_ID_RE.match(s)
    if not m:
        return None, pd.NaT
    return m.group("station").replace("_", "-"), pd.to_datetime(m.group("ts"), errors="coerce")


def parse_static_id(value: object) -> tuple[str | None, pd.Timestamp | pd.NaT]:
    s = str(value or "")
    m = STATIC_ID_RE.match(s)
    if not m:
        return None, pd.NaT
    ts = pd.to_datetime(m.group("ts"), format="%Y-%m-%dT%H-%M-%S-%f", errors="coerce")
    return m.group("station"), ts


def check_live_api_total() -> None:
    load_dotenv(ROOT / ".env")
    token = os.getenv("ACN_API_TOKEN", "").strip()
    print("\n===== 1. LIVE API TOTAL (ONE LIGHTWEIGHT REQUEST) =====")
    if not token:
        print("API token not found in .env; skipped live _meta.total check.")
        return
    url = urljoin(BASE_URL, f"sessions/{SITE_ID}?max_results=1")
    try:
        response = requests.get(url, auth=(token, ""), timeout=(15, 45), headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        meta = payload.get("_meta", {})
        print(f"Current API _meta.total: {meta.get('total', 'NOT RETURNED')}")
        print(f"Returned items in this check: {len(payload.get('_items', []))}")
        print("This is a count check only; no session snapshot was downloaded.")
    except Exception as exc:
        print(f"Could not verify live API total: {type(exc).__name__}: {exc}")


def inspect_api_snapshot() -> pd.DataFrame:
    print("\n===== 2. LOCAL API SNAPSHOT INTEGRITY =====")
    if not RAW_API_FILE.exists():
        raise FileNotFoundError(RAW_API_FILE)
    data = json.loads(RAW_API_FILE.read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    ids = df.get("sessionID", pd.Series(dtype="object"))
    unique = ids.nunique(dropna=True)
    print(f"JSON records: {len(df):,}")
    print(f"Non-null sessionID: {ids.notna().sum():,}")
    print(f"Unique sessionID: {unique:,}")
    print(f"Duplicate sessionID rows: {ids.notna().sum() - unique:,}")
    missing = int(ids.isna().sum())
    print(f"Missing sessionID: {missing:,}")
    if "siteID" in df:
        print(f"Payload siteID values: {sorted(df['siteID'].dropna().astype(str).unique().tolist())}")
    return df


def near_miss_audit() -> None:
    print("\n===== 3. NEAR-MISS MATCH AUDIT (UNMATCHED ONLY, SAME STATION) =====")
    mapping = pd.read_csv(SESSION_MAPPING_FILE, dtype=str).fillna("")
    api_only = mapping.loc[mapping.match_status.eq("API_ONLY"), "api_session_id"]
    static_only = mapping.loc[mapping.match_status.eq("STATIC_ONLY"), "static_session_id"]

    api_rows = []
    for value in api_only:
        station, ts = parse_api_id(value)
        if station and pd.notna(ts):
            api_rows.append((station, ts, value))
    static_rows = []
    for value in static_only:
        station, ts = parse_static_id(value)
        if station and pd.notna(ts):
            static_rows.append((station, ts, value))

    a = pd.DataFrame(api_rows, columns=["station_id", "ts", "api_session_id"])
    s = pd.DataFrame(static_rows, columns=["station_id", "ts", "static_session_id"])
    print(f"Parsable API_ONLY IDs: {len(a):,}/{len(api_only):,}")
    print(f"Parsable STATIC_ONLY IDs: {len(s):,}/{len(static_only):,}")
    if a.empty or s.empty:
        print("Not enough parsable unmatched IDs to calculate nearest candidates.")
        return

    nearest_parts = []
    for station in sorted(set(a.station_id) & set(s.station_id)):
        aa = a.loc[a.station_id.eq(station)].sort_values("ts").rename(columns={"ts": "api_ts"})
        ss = s.loc[s.station_id.eq(station)].sort_values("ts").rename(columns={"ts": "static_ts"})
        if aa.empty or ss.empty:
            continue
        merged = pd.merge_asof(
            ss,
            aa,
            left_on="static_ts",
            right_on="api_ts",
            direction="nearest",
            tolerance=None,
            suffixes=("_static", "_api"),
        )
        merged["abs_diff_seconds"] = (merged["api_ts"] - merged["static_ts"]).abs().dt.total_seconds()
        merged["signed_diff_seconds"] = (merged["api_ts"] - merged["static_ts"]).dt.total_seconds()
        nearest_parts.append(merged)

    if not nearest_parts:
        print("No shared station IDs among unmatched records.")
        return
    nearest = pd.concat(nearest_parts, ignore_index=True)
    valid = nearest.dropna(subset=["abs_diff_seconds"]).copy()
    if valid.empty:
        print("No nearest candidates found.")
        return

    print(f"STATIC_ONLY rows with a same-station API_ONLY candidate: {len(valid):,}")
    for seconds in [1, 2, 5, 10, 30, 60, 300, 3600, 8 * 3600, 24 * 3600]:
        count = int(valid.abs_diff_seconds.le(seconds).sum())
        print(f"Nearest candidate within {seconds:>6,} sec: {count:>5,} ({100*count/len(s):.2f}% of parsable STATIC_ONLY)")

    # Distinct candidate usage indicates potential many-to-one fuzzy matches.
    close = valid.loc[valid.abs_diff_seconds.le(5)].copy()
    candidate_counts = close.api_session_id.value_counts()
    reused = int(candidate_counts.gt(1).sum())
    print(f"API_ONLY candidates reused by >1 STATIC_ONLY within 5 sec: {reused:,}")
    print("Closest 20 candidate pairs (inspection only; NOT accepted as matches):")
    cols = ["station_id_static", "static_session_id", "api_session_id", "abs_diff_seconds", "signed_diff_seconds"]
    print(valid.sort_values("abs_diff_seconds")[cols].head(20).to_string(index=False))
    print("IMPORTANT: Do not fuzzy-join automatically. Confirm unique one-to-one IDs and source timestamp semantics first.")


def inspect_time_coverage() -> None:
    print("\n===== 4. SESSION-BOUNDARY MEASUREMENT COVERAGE =====")
    q = pd.read_csv(SESSION_QUALITY_FILE)
    for c in ["start_abs_diff_seconds", "end_abs_diff_seconds"]:
        q[c] = pd.to_numeric(q[c], errors="coerce")
    start = q.start_abs_diff_seconds
    end = q.end_abs_diff_seconds
    print(f"Matched sessions audited: {len(q):,}")
    print(f"Start measurement begins >60 sec from API connection: {int(start.gt(60).sum()):,}")
    print(f"End measurement ends >60 sec from API disconnect: {int(end.gt(60).sum()):,}")
    print(f"Both boundaries differ >60 sec: {int((start.gt(60) & end.gt(60)).sum()):,}")
    print(f"Start >1 hour: {int(start.gt(3600).sum()):,}")
    print(f"End >1 hour: {int(end.gt(3600).sum()):,}")
    print("Interpretation: these compare first/last observed Static samples with API session boundaries.")
    print("A late first sample may mean partial telemetry coverage; it does not by itself invalidate the exact session-ID match.")


def main() -> None:
    check_live_api_total()
    inspect_api_snapshot()
    near_miss_audit()
    inspect_time_coverage()
    print("\n===== DIAGNOSTICS COMPLETED (READ-ONLY) =====")


if __name__ == "__main__":
    main()
