"""Align JPL API charging-session intervals with Static electrical samples by EVSE-hour.

The output is descriptive: API intervals are split into UTC-hour overlap buckets,
while Static samples are grouped by their actual UTC timestamps. Missing samples
are never treated as zero. This is an audit/export step and does not mutate the
warehouse or source data.

Run:
    python scripts/audit_jpl_api_static_hourly_alignment.py
    python scripts/audit_jpl_api_static_hourly_alignment.py --start-month 2020-07 --end-month 2020-11
    python scripts/audit_jpl_api_static_hourly_alignment.py --chunksize 250000
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_config import (  # noqa: E402
    CLEAN_SESSIONS_FILE,
    CLEAN_STATIC_FILE,
    SESSION_MAPPING_FILE,
)

TIMEZONE = "America/Los_Angeles"
OUTPUT_DIR = ROOT / "data" / "analytics" / "jpl_api_static_alignment"
STATIC_COLUMNS = [
    "station_id",
    "session_id",
    "timestamp",
    "power_kw",
    "charging_current_a",
    "voltage_v",
]


def as_utc_timestamp(value) -> pd.Timestamp:
    """Convert a timestamp-like value to an aware UTC Timestamp."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def split_interval_into_utc_hours(
    start,
    end,
    window_start=None,
    window_end=None,
) -> list[tuple[pd.Timestamp, float]]:
    """Return UTC-hour buckets and overlap minutes for [start, end).

    Optional window bounds clip the session to the requested analysis period.
    UTC buckets deliberately avoid ambiguity during daylight-saving transitions.
    """
    if pd.isna(start) or pd.isna(end):
        return []
    start_utc = as_utc_timestamp(start)
    end_utc = as_utc_timestamp(end)
    if window_start is not None:
        start_utc = max(start_utc, as_utc_timestamp(window_start))
    if window_end is not None:
        end_utc = min(end_utc, as_utc_timestamp(window_end))
    if end_utc <= start_utc:
        return []

    result = []
    hour = start_utc.floor("h")
    while hour < end_utc:
        overlap_start = max(start_utc, hour)
        overlap_end = min(end_utc, hour + pd.Timedelta(hours=1))
        overlap_minutes = (overlap_end - overlap_start).total_seconds() / 60.0
        if overlap_minutes > 0:
            result.append((hour, overlap_minutes))
        hour += pd.Timedelta(hours=1)
    return result


def load_mapping() -> tuple[dict[str, str], dict[str, str]]:
    mapping = pd.read_csv(SESSION_MAPPING_FILE, dtype=str).fillna("")
    required = {"static_session_id", "api_session_id", "match_status"}
    missing = required - set(mapping.columns)
    if missing:
        raise ValueError(f"Session mapping is missing columns: {sorted(missing)}")

    nonempty_static = mapping.loc[mapping["static_session_id"].ne("")]
    if nonempty_static["static_session_id"].duplicated().any():
        raise ValueError("Static session IDs are not unique in the mapping.")

    nonempty_api = mapping.loc[mapping["api_session_id"].ne("")]
    if nonempty_api["api_session_id"].duplicated().any():
        raise ValueError("API session IDs are not unique in the mapping.")

    static_to_api = {
        row.static_session_id: row.api_session_id
        for row in mapping.loc[
            mapping["match_status"].eq("MATCHED")
        ][["static_session_id", "api_session_id"]].itertuples(index=False)
    }
    static_status = {
        row.static_session_id: row.match_status
        for row in nonempty_static[
            ["static_session_id", "match_status"]
        ].itertuples(index=False)
    }
    api_status = {
        row.api_session_id: row.match_status
        for row in nonempty_api[
            ["api_session_id", "match_status"]
        ].itertuples(index=False)
    }
    return static_to_api, {**static_status, **{f"API::{k}": v for k, v in api_status.items()}}


def build_api_hourly_index(
    api_file: Path,
    api_status: dict[str, str],
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
) -> tuple[dict, dict]:
    api = pd.read_csv(
        api_file,
        usecols=["station_id", "session_id", "connection_time", "disconnect_time"],
        dtype={"station_id": "string", "session_id": "string"},
    )
    api["connection_time"] = pd.to_datetime(
        api["connection_time"], utc=True, errors="coerce"
    )
    api["disconnect_time"] = pd.to_datetime(
        api["disconnect_time"], utc=True, errors="coerce"
    )

    hourly = defaultdict(lambda: {
        "api_session_ids": set(),
        "matched_api_session_ids": set(),
        "api_only_session_ids": set(),
        "unmapped_api_session_ids": set(),
        "api_session_minutes_sum": 0.0,
    })
    sessions_in_window = set()
    invalid_intervals = 0

    for row in api.itertuples(index=False):
        if pd.isna(row.station_id) or pd.isna(row.session_id):
            continue
        if pd.isna(row.connection_time) or pd.isna(row.disconnect_time):
            invalid_intervals += 1
            continue

        overlaps = split_interval_into_utc_hours(
            row.connection_time,
            row.disconnect_time,
            start_utc,
            end_utc,
        )
        if not overlaps:
            continue

        session_id = str(row.session_id)
        station_id = str(row.station_id)
        sessions_in_window.add(session_id)
        status = api_status.get(session_id, "UNMAPPED_API")

        for utc_hour, overlap_minutes in overlaps:
            bucket = hourly[(station_id, utc_hour)]
            bucket["api_session_ids"].add(session_id)
            bucket["api_session_minutes_sum"] += overlap_minutes
            if status == "MATCHED":
                bucket["matched_api_session_ids"].add(session_id)
            elif status == "API_ONLY":
                bucket["api_only_session_ids"].add(session_id)
            else:
                bucket["unmapped_api_session_ids"].add(session_id)

    return hourly, {
        "api_sessions_overlapping_window": len(sessions_in_window),
        "api_sessions_with_invalid_or_missing_intervals": invalid_intervals,
    }


def scan_static_measurements(
    static_file: Path,
    static_to_api: dict[str, str],
    static_status: dict[str, str],
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
    chunksize: int,
) -> tuple[dict, dict]:
    hourly = defaultdict(lambda: {
        "total_samples": 0,
        "power_samples": 0,
        "power_sum_kw": 0.0,
        "power_max_kw": None,
        "current_samples": 0,
        "current_sum_a": 0.0,
        "voltage_samples": 0,
        "static_session_ids": set(),
        "matched_api_session_ids_with_samples": set(),
        "static_only_session_ids": set(),
        "unmapped_static_session_ids": set(),
    })

    scanned_rows = 0
    rows_in_window = 0
    invalid_timestamps = 0

    for chunk in pd.read_csv(
        static_file,
        usecols=STATIC_COLUMNS,
        dtype={"station_id": "string", "session_id": "string"},
        chunksize=chunksize,
        low_memory=False,
    ):
        scanned_rows += len(chunk)
        chunk["timestamp"] = pd.to_datetime(
            chunk["timestamp"], utc=True, errors="coerce"
        )
        invalid_timestamps += int(chunk["timestamp"].isna().sum())
        chunk = chunk.dropna(subset=["timestamp", "station_id", "session_id"])
        chunk = chunk.loc[
            chunk["timestamp"].ge(start_utc)
            & chunk["timestamp"].lt(end_utc)
        ].copy()
        if chunk.empty:
            continue

        rows_in_window += len(chunk)
        chunk["power_kw"] = pd.to_numeric(chunk["power_kw"], errors="coerce")
        chunk["charging_current_a"] = pd.to_numeric(
            chunk["charging_current_a"], errors="coerce"
        )
        chunk["voltage_v"] = pd.to_numeric(chunk["voltage_v"], errors="coerce")
        chunk["utc_hour"] = chunk["timestamp"].dt.floor("h")

        grouped = chunk.groupby(
            ["station_id", "utc_hour"], observed=True
        ).agg(
            total_samples=("timestamp", "size"),
            power_samples=("power_kw", "count"),
            power_sum_kw=("power_kw", "sum"),
            power_max_kw=("power_kw", "max"),
            current_samples=("charging_current_a", "count"),
            current_sum_a=("charging_current_a", "sum"),
            voltage_samples=("voltage_v", "count"),
        )

        for (station_id, utc_hour), row in grouped.iterrows():
            bucket = hourly[(str(station_id), utc_hour)]
            bucket["total_samples"] += int(row["total_samples"])
            bucket["power_samples"] += int(row["power_samples"])
            bucket["power_sum_kw"] += float(row["power_sum_kw"])
            bucket["current_samples"] += int(row["current_samples"])
            bucket["current_sum_a"] += float(row["current_sum_a"])
            bucket["voltage_samples"] += int(row["voltage_samples"])
            if pd.notna(row["power_max_kw"]):
                current_max = bucket["power_max_kw"]
                bucket["power_max_kw"] = (
                    float(row["power_max_kw"])
                    if current_max is None
                    else max(current_max, float(row["power_max_kw"]))
                )

        # Track distinct session IDs in each station-hour, across chunk boundaries.
        distinct_sessions = chunk[
            ["station_id", "utc_hour", "session_id"]
        ].drop_duplicates()
        for row in distinct_sessions.itertuples(index=False):
            station_id = str(row.station_id)
            session_id = str(row.session_id)
            bucket = hourly[(station_id, row.utc_hour)]
            bucket["static_session_ids"].add(session_id)
            api_id = static_to_api.get(session_id)
            if api_id:
                bucket["matched_api_session_ids_with_samples"].add(api_id)
            elif static_status.get(session_id) == "STATIC_ONLY":
                bucket["static_only_session_ids"].add(session_id)
            else:
                bucket["unmapped_static_session_ids"].add(session_id)

        if scanned_rows % (chunksize * 5) < chunksize:
            print(
                f"Scanned {scanned_rows:,} Static rows; "
                f"rows in window={rows_in_window:,}; "
                f"station-hour buckets={len(hourly):,}",
                flush=True,
            )

    return hourly, {
        "static_rows_scanned": scanned_rows,
        "static_rows_in_window": rows_in_window,
        "invalid_static_timestamps": invalid_timestamps,
    }


def build_alignment_frame(api_hourly: dict, static_hourly: dict) -> pd.DataFrame:
    rows = []
    keys = set(api_hourly) | set(static_hourly)
    for station_id, utc_hour in sorted(keys, key=lambda item: (item[0], item[1])):
        api = api_hourly.get((station_id, utc_hour), {})
        static = static_hourly.get((station_id, utc_hour), {})

        api_ids = api.get("api_session_ids", set())
        api_matched_ids = api.get("matched_api_session_ids", set())
        static_matched_ids = static.get("matched_api_session_ids_with_samples", set())
        static_only_ids = static.get("static_only_session_ids", set())
        static_session_ids = static.get("static_session_ids", set())

        total_samples = int(static.get("total_samples", 0))
        power_samples = int(static.get("power_samples", 0))
        current_samples = int(static.get("current_samples", 0))
        voltage_samples = int(static.get("voltage_samples", 0))
        power_sum = float(static.get("power_sum_kw", 0.0))
        current_sum = float(static.get("current_sum_a", 0.0))
        local = utc_hour.tz_convert(TIMEZONE)

        rows.append({
            "station_id": station_id,
            "utc_hour_start": utc_hour.isoformat(),
            "local_date": local.strftime("%Y-%m-%d"),
            "local_month": local.strftime("%Y-%m"),
            "local_hour": int(local.hour),
            "utc_offset": local.strftime("%z"),
            "api_sessions_overlapping_hour": len(api_ids),
            "api_sessions_matched_to_static": len(api_matched_ids),
            "api_sessions_api_only": len(api.get("api_only_session_ids", set())),
            "api_sessions_unmapped": len(api.get("unmapped_api_session_ids", set())),
            "api_session_minutes_sum": float(api.get("api_session_minutes_sum", 0.0)),
            "static_sessions_with_samples": len(static_session_ids),
            "static_matched_api_sessions_with_samples": len(static_matched_ids),
            "static_only_sessions_with_samples": len(static_only_ids),
            "unmapped_static_sessions_with_samples": len(
                static.get("unmapped_static_session_ids", set())
            ),
            "matched_api_sessions_without_static_sample_this_hour": len(
                api_matched_ids - static_matched_ids
            ),
            "static_total_samples": total_samples,
            "static_power_samples": power_samples,
            "static_power_sample_coverage_pct": (
                100.0 * power_samples / total_samples if total_samples else None
            ),
            "static_mean_sample_power_kw": (
                power_sum / power_samples if power_samples else None
            ),
            "static_max_sample_power_kw": static.get("power_max_kw"),
            "static_voltage_samples": voltage_samples,
            "static_current_samples": current_samples,
            "static_mean_sample_current_a": (
                current_sum / current_samples if current_samples else None
            ),
            "has_api_session_overlap": bool(api_ids),
            "has_static_measurements": bool(static_session_ids),
        })

    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> dict:
    for file_path in [CLEAN_SESSIONS_FILE, CLEAN_STATIC_FILE, SESSION_MAPPING_FILE]:
        if not file_path.exists():
            raise FileNotFoundError(
                f"Required input not found: {file_path}. Run the JPL transform pipeline first."
            )

    start_local = pd.Timestamp(f"{args.start_month}-01 00:00:00", tz=TIMEZONE)
    next_month = (pd.Period(args.end_month, freq="M") + 1).strftime("%Y-%m")
    end_local = pd.Timestamp(f"{next_month}-01 00:00:00", tz=TIMEZONE)
    if end_local <= start_local:
        raise ValueError("--end-month must be the same as or after --start-month.")
    start_utc = start_local.tz_convert("UTC")
    end_utc = end_local.tz_convert("UTC")

    static_to_api, statuses = load_mapping()
    static_status = {key: value for key, value in statuses.items() if not key.startswith("API::")}
    api_status = {key[5:]: value for key, value in statuses.items() if key.startswith("API::")}

    print("===== JPL API / STATIC HOURLY ALIGNMENT =====")
    print(f"Window (local): {args.start_month} to {args.end_month}")
    print(f"Timezone: {TIMEZONE}")
    print("API sessions: expanding connection/disconnection intervals into UTC hours")

    api_hourly, api_summary = build_api_hourly_index(
        CLEAN_SESSIONS_FILE, api_status, start_utc, end_utc
    )
    static_hourly, static_summary = scan_static_measurements(
        CLEAN_STATIC_FILE,
        static_to_api,
        static_status,
        start_utc,
        end_utc,
        args.chunksize,
    )
    frame = build_alignment_frame(api_hourly, static_hourly)
    if frame.empty:
        raise RuntimeError("No API or Static station-hour records found in the selected window.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hourly_path = OUTPUT_DIR / "jpl_api_static_station_hour_alignment.csv"
    frame.to_csv(hourly_path, index=False)

    summary = {
        "window_start_local": start_local.isoformat(),
        "window_end_local_exclusive": end_local.isoformat(),
        "timezone": TIMEZONE,
        **api_summary,
        **static_summary,
        "station_hour_rows": len(frame),
        "stations_in_alignment": int(frame["station_id"].nunique()),
        "api_matched_session_hour_pairs": int(
            frame["api_sessions_matched_to_static"].sum()
        ),
        "api_only_session_hour_pairs": int(frame["api_sessions_api_only"].sum()),
        "static_session_hour_pairs_with_samples": int(
            frame["static_sessions_with_samples"].sum()
        ),
        "static_only_session_hour_pairs": int(
            frame["static_only_sessions_with_samples"].sum()
        ),
        "static_power_samples": int(frame["static_power_samples"].sum()),
        "static_total_samples": int(frame["static_total_samples"].sum()),
        "static_power_sample_coverage_pct": float(
            100.0 * frame["static_power_samples"].sum()
            / frame["static_total_samples"].sum()
        ) if frame["static_total_samples"].sum() else None,
        "output": str(hourly_path),
        "interpretation_warning": (
            "API session minutes are summed session-minutes within each hour, not unique occupied minutes. "
            "Static mean Power is the mean of observed samples for one station-hour. "
            "Static samples are session-scoped, not continuous EVSE telemetry. "
            "Do not sum station-hour means and label the result total JPL facility demand."
        ),
    }
    (OUTPUT_DIR / "jpl_api_static_alignment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n===== ALIGNMENT RESULT =====")
    print(f"API sessions overlapping window: {summary['api_sessions_overlapping_window']:,}")
    print(f"Static rows in window: {summary['static_rows_in_window']:,}")
    print(f"Stations in alignment: {summary['stations_in_alignment']:,}")
    print(f"Station-hour rows: {summary['station_hour_rows']:,}")
    power_coverage = summary["static_power_sample_coverage_pct"]
    print(
        "Static Power sample coverage: "
        + (f"{power_coverage:.3f}%" if power_coverage is not None else "N/A")
    )
    print(f"Output: {OUTPUT_DIR}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", default="2020-07", help="First local month, YYYY-MM.")
    parser.add_argument("--end-month", default="2020-11", help="Last local month, YYYY-MM inclusive.")
    parser.add_argument("--chunksize", type=int, default=500_000)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
