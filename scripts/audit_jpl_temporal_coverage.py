"""Audit temporal coverage of full, cleaned JPL Static measurements.

This reads the complete cleaned Static file (not the API-matched subset), filters
the selected high-Power EVSE candidates, and writes compact hourly coverage
tables. It never fills missing Power values with zero.

Default analysis window: July-November 2020, America/Los_Angeles.

Run:
    python scripts/audit_jpl_temporal_coverage.py
    python scripts/audit_jpl_temporal_coverage.py --chunksize 250000
    python scripts/audit_jpl_temporal_coverage.py --all-stations

Outputs are written to data/analytics/jpl_power_temporal/.
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

from project_config import CLEAN_STATIC_FILE  # noqa: E402

TIMEZONE = "America/Los_Angeles"
INVENTORY_DIR = ROOT / "data" / "inventory"
SCOPE_FILE = INVENTORY_DIR / "jpl_power_analysis_stations.csv"
OUTPUT_DIR = ROOT / "data" / "analytics" / "jpl_power_temporal"

INPUT_COLUMNS = [
    "station_id",
    "timestamp",
    "power_kw",
    "voltage_v",
    "charging_current_a",
]


def expected_hours_in_local_month(month: str) -> int:
    """Elapsed UTC hours in a local calendar month, including DST transitions."""
    start = pd.Timestamp(f"{month}-01 00:00:00", tz=TIMEZONE)
    next_month = (pd.Period(month, freq="M") + 1).strftime("%Y-%m")
    end = pd.Timestamp(f"{next_month}-01 00:00:00", tz=TIMEZONE)
    return int((end.tz_convert("UTC") - start.tz_convert("UTC")).total_seconds() // 3600)


def load_selected_stations(include_all: bool) -> list[str]:
    if include_all:
        return []
    if not SCOPE_FILE.exists():
        raise FileNotFoundError(
            f"Power scope file not found: {SCOPE_FILE}. "
            "Run scripts/select_jpl_power_analysis_scope.py first, "
            "or pass --all-stations."
        )
    df = pd.read_csv(SCOPE_FILE, usecols=["station_id"], dtype={"station_id": "string"})
    stations = sorted(df["station_id"].dropna().astype(str).unique().tolist())
    if not stations:
        raise RuntimeError(f"No station IDs found in {SCOPE_FILE}.")
    return stations


def build_hourly_records(
    accumulator: dict,
) -> pd.DataFrame:
    columns = [
        "station_id",
        "utc_hour_start",
        "local_month",
        "local_date",
        "local_hour",
        "utc_offset",
        "total_samples",
        "power_samples",
        "power_sum_kw",
        "positive_power_samples",
        "power_max_kw",
        "voltage_samples",
        "current_samples",
        "positive_current_samples",
        "current_sum_a",
    ]
    rows = []
    for (station_id, utc_hour), values in accumulator.items():
        (
            local_month,
            local_date,
            local_hour,
            utc_offset,
            total_samples,
            power_samples,
            power_sum,
            positive_power,
            power_max,
            voltage_samples,
            current_samples,
            positive_current,
            current_sum,
        ) = values
        rows.append([
            station_id, utc_hour, local_month, local_date, local_hour, utc_offset,
            total_samples, power_samples, power_sum, positive_power, power_max,
            voltage_samples, current_samples, positive_current, current_sum,
        ])
    result = pd.DataFrame(rows, columns=columns)
    if result.empty:
        return result
    result["avg_power_kw"] = result["power_sum_kw"] / result["power_samples"].replace(0, pd.NA)
    result["avg_current_a"] = result["current_sum_a"] / result["current_samples"].replace(0, pd.NA)
    result["power_sample_coverage_pct"] = (
        100.0 * result["power_samples"] / result["total_samples"]
    )
    result["positive_power_pct"] = (
        100.0 * result["positive_power_samples"] / result["power_samples"].replace(0, pd.NA)
    )
    result["positive_current_pct"] = (
        100.0 * result["positive_current_samples"] / result["current_samples"].replace(0, pd.NA)
    )
    return result.sort_values(["station_id", "utc_hour_start"]).reset_index(drop=True)


def build_station_month_summary(hourly: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "station_id", "month", "observed_calendar_hours", "expected_calendar_hours",
        "calendar_hour_observation_pct", "hours_with_power", "power_hour_presence_pct",
        "calendar_hour_power_presence_pct", "total_samples", "power_samples",
        "power_sample_coverage_pct", "positive_power_samples", "positive_power_pct",
        "avg_samples_per_observed_hour", "median_samples_per_observed_hour",
        "avg_power_kw_sample_weighted", "avg_observed_hour_power_kw",
        "p95_observed_hour_power_kw", "max_observed_hour_power_kw",
    ]
    if hourly.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for (station_id, month), group in hourly.groupby(["station_id", "local_month"], sort=True):
        observed_hours = len(group)
        expected_hours = expected_hours_in_local_month(month)
        hours_with_power = int(group["power_samples"].gt(0).sum())
        total_samples = int(group["total_samples"].sum())
        power_samples = int(group["power_samples"].sum())
        positive_power = int(group["positive_power_samples"].sum())
        weighted_power = (
            float(group["power_sum_kw"].sum() / power_samples)
            if power_samples else None
        )
        observed_hour_means = group["avg_power_kw"].dropna()
        rows.append({
            "station_id": station_id,
            "month": month,
            "observed_calendar_hours": observed_hours,
            "expected_calendar_hours": expected_hours,
            "calendar_hour_observation_pct": 100.0 * observed_hours / expected_hours if expected_hours else None,
            "hours_with_power": hours_with_power,
            "power_hour_presence_pct": 100.0 * hours_with_power / observed_hours if observed_hours else None,
            "calendar_hour_power_presence_pct": 100.0 * hours_with_power / expected_hours if expected_hours else None,
            "total_samples": total_samples,
            "power_samples": power_samples,
            "power_sample_coverage_pct": 100.0 * power_samples / total_samples if total_samples else None,
            "positive_power_samples": positive_power,
            "positive_power_pct": 100.0 * positive_power / power_samples if power_samples else None,
            "avg_samples_per_observed_hour": float(group["total_samples"].mean()),
            "median_samples_per_observed_hour": float(group["total_samples"].median()),
            "avg_power_kw_sample_weighted": weighted_power,
            "avg_observed_hour_power_kw": float(observed_hour_means.mean()) if not observed_hour_means.empty else None,
            "p95_observed_hour_power_kw": float(observed_hour_means.quantile(0.95)) if not observed_hour_means.empty else None,
            "max_observed_hour_power_kw": float(observed_hour_means.max()) if not observed_hour_means.empty else None,
        })
    return pd.DataFrame(rows, columns=columns)


def build_station_hour_of_day_profile(hourly: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "station_id", "local_hour", "observed_calendar_hours",
        "distinct_local_dates", "total_samples", "power_samples",
        "power_sample_coverage_pct", "avg_observed_hour_power_kw",
        "p95_observed_hour_power_kw", "avg_samples_per_observed_hour",
    ]
    if hourly.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (station_id, local_hour), group in hourly.groupby(["station_id", "local_hour"], sort=True):
        means = group["avg_power_kw"].dropna()
        total_samples = int(group["total_samples"].sum())
        power_samples = int(group["power_samples"].sum())
        rows.append({
            "station_id": station_id,
            "local_hour": int(local_hour),
            "observed_calendar_hours": len(group),
            "distinct_local_dates": int(group["local_date"].nunique()),
            "total_samples": total_samples,
            "power_samples": power_samples,
            "power_sample_coverage_pct": 100.0 * power_samples / total_samples if total_samples else None,
            "avg_observed_hour_power_kw": float(means.mean()) if not means.empty else None,
            "p95_observed_hour_power_kw": float(means.quantile(0.95)) if not means.empty else None,
            "avg_samples_per_observed_hour": float(group["total_samples"].mean()),
        })
    return pd.DataFrame(rows, columns=columns)


def build_site_hourly_observed_load(hourly: pd.DataFrame, selected_station_count: int) -> pd.DataFrame:
    columns = [
        "utc_hour_start", "local_date", "local_hour", "utc_offset",
        "stations_with_any_samples", "stations_with_power",
        "selected_station_count", "selected_station_power_coverage_pct",
        "observed_power_sum_kw", "power_samples", "total_samples",
        "all_selected_stations_have_power",
    ]
    if hourly.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for utc_hour, group in hourly.groupby("utc_hour_start", sort=True):
        with_power = group.loc[group["power_samples"].gt(0)]
        stations_with_power = int(with_power["station_id"].nunique())
        stations_with_samples = int(group["station_id"].nunique())
        first = group.iloc[0]
        rows.append({
            "utc_hour_start": utc_hour,
            "local_date": first["local_date"],
            "local_hour": int(first["local_hour"]),
            "utc_offset": first["utc_offset"],
            "stations_with_any_samples": stations_with_samples,
            "stations_with_power": stations_with_power,
            "selected_station_count": selected_station_count,
            "selected_station_power_coverage_pct": 100.0 * stations_with_power / selected_station_count if selected_station_count else None,
            # This is a sum over observed stations only; missing stations are not zero-filled.
            "observed_power_sum_kw": float(with_power["avg_power_kw"].sum()) if not with_power.empty else None,
            "power_samples": int(group["power_samples"].sum()),
            "total_samples": int(group["total_samples"].sum()),
            "all_selected_stations_have_power": stations_with_power == selected_station_count,
        })
    return pd.DataFrame(rows, columns=columns)


def run(args: argparse.Namespace) -> dict:
    if not CLEAN_STATIC_FILE.exists():
        raise FileNotFoundError(
            f"Clean full Static file not found: {CLEAN_STATIC_FILE}. "
            "Run clean_static.py first; do not use the matched-only file for this audit."
        )

    selected_stations = load_selected_stations(args.all_stations)
    selected_set = set(selected_stations)
    start_local = pd.Timestamp(f"{args.start_month}-01 00:00:00", tz=TIMEZONE)
    next_month = (pd.Period(args.end_month, freq="M") + 1).strftime("%Y-%m")
    end_local = pd.Timestamp(f"{next_month}-01 00:00:00", tz=TIMEZONE)
    if end_local <= start_local:
        raise ValueError("--end-month must be the same as or after --start-month.")

    # Keyed by station and absolute UTC hour. UTC keys preserve both occurrences
    # of the repeated local hour when daylight-saving time ends.
    accumulator = {}
    scanned_rows = 0
    selected_period_rows = 0
    invalid_timestamps = 0

    print("===== JPL TEMPORAL COVERAGE AUDIT =====")
    print(f"Input: {CLEAN_STATIC_FILE}")
    print(f"Window (local): {args.start_month} to {args.end_month}")
    print(f"Timezone: {TIMEZONE}")
    print(f"Stations: {'ALL' if args.all_stations else len(selected_stations)}")

    for chunk in pd.read_csv(
        CLEAN_STATIC_FILE,
        usecols=INPUT_COLUMNS,
        dtype={"station_id": "string"},
        chunksize=args.chunksize,
        low_memory=False,
    ):
        scanned_rows += len(chunk)
        chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], utc=True, errors="coerce")
        invalid_timestamps += int(chunk["timestamp"].isna().sum())
        chunk = chunk.dropna(subset=["timestamp", "station_id"])
        if not args.all_stations:
            chunk = chunk[chunk["station_id"].isin(selected_set)]
        if chunk.empty:
            continue

        local_ts = chunk["timestamp"].dt.tz_convert(TIMEZONE)
        mask = local_ts.ge(start_local) & local_ts.lt(end_local)
        chunk = chunk.loc[mask].copy()
        if chunk.empty:
            continue

        selected_period_rows += len(chunk)
        chunk["power_kw"] = pd.to_numeric(chunk["power_kw"], errors="coerce")
        chunk["voltage_v"] = pd.to_numeric(chunk["voltage_v"], errors="coerce")
        chunk["charging_current_a"] = pd.to_numeric(chunk["charging_current_a"], errors="coerce")
        chunk["utc_hour"] = chunk["timestamp"].dt.floor("h")

        grouped = chunk.groupby(["station_id", "utc_hour"], observed=True).agg(
            total_samples=("timestamp", "size"),
            power_samples=("power_kw", "count"),
            power_sum_kw=("power_kw", "sum"),
            positive_power_samples=("power_kw", lambda x: x.gt(0).sum()),
            power_max_kw=("power_kw", "max"),
            voltage_samples=("voltage_v", "count"),
            current_samples=("charging_current_a", "count"),
            positive_current_samples=("charging_current_a", lambda x: x.gt(0).sum()),
            current_sum_a=("charging_current_a", "sum"),
        ).reset_index()

        for row in grouped.itertuples(index=False):
            station_id = str(row.station_id)
            utc_hour = row.utc_hour
            local_hour = utc_hour.tz_convert(TIMEZONE)
            key = (station_id, utc_hour.isoformat())
            values = [
                local_hour.strftime("%Y-%m"),
                local_hour.strftime("%Y-%m-%d"),
                int(local_hour.hour),
                local_hour.strftime("%z"),
                int(row.total_samples),
                int(row.power_samples),
                float(row.power_sum_kw) if row.power_samples else 0.0,
                int(row.positive_power_samples),
                float(row.power_max_kw) if row.power_samples else None,
                int(row.voltage_samples),
                int(row.current_samples),
                int(row.positive_current_samples),
                float(row.current_sum_a) if row.current_samples else 0.0,
            ]
            if key not in accumulator:
                accumulator[key] = values
            else:
                old = accumulator[key]
                for index in [4, 5, 7, 9, 10, 11]:
                    old[index] += values[index]
                old[6] += values[6]
                old[12] += values[12]
                if values[8] is not None:
                    old[8] = values[8] if old[8] is None else max(old[8], values[8])

        if scanned_rows % (args.chunksize * 5) < args.chunksize:
            print(
                f"Scanned {scanned_rows:,} rows; selected-window rows={selected_period_rows:,}; "
                f"station-hour buckets={len(accumulator):,}",
                flush=True,
            )

    hourly = build_hourly_records(accumulator)
    if hourly.empty:
        raise RuntimeError("No Static measurements found for the selected stations and time window.")

    selected_count = len(selected_stations) if selected_stations else int(hourly["station_id"].nunique())
    station_month = build_station_month_summary(hourly)
    station_hour_profile = build_station_hour_of_day_profile(hourly)
    site_hourly = build_site_hourly_observed_load(hourly, selected_count)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(OUTPUT_DIR / "jpl_station_hourly_temporal_coverage.csv", index=False)
    station_month.to_csv(OUTPUT_DIR / "jpl_station_month_temporal_coverage.csv", index=False)
    station_hour_profile.to_csv(OUTPUT_DIR / "jpl_station_hour_of_day_profile.csv", index=False)
    site_hourly.to_csv(OUTPUT_DIR / "jpl_site_hourly_observed_load.csv", index=False)

    summary = {
        "input_file": str(CLEAN_STATIC_FILE),
        "timezone": TIMEZONE,
        "start_month": args.start_month,
        "end_month": args.end_month,
        "selected_station_count": selected_count,
        "selected_station_ids": selected_stations or sorted(hourly["station_id"].unique().tolist()),
        "scanned_rows": scanned_rows,
        "selected_window_rows": selected_period_rows,
        "invalid_timestamps": invalid_timestamps,
        "station_hour_buckets": len(hourly),
        "site_hour_buckets": len(site_hourly),
        "months_present": sorted(station_month["month"].unique().tolist()),
        "power_samples": int(hourly["power_samples"].sum()),
        "total_samples": int(hourly["total_samples"].sum()),
        "power_sample_coverage_pct": float(
            100 * hourly["power_samples"].sum() / hourly["total_samples"].sum()
        ),
        "hours_with_all_selected_stations_power": int(
            site_hourly["all_selected_stations_have_power"].sum()
        ),
        "outputs": [
            "jpl_station_hourly_temporal_coverage.csv",
            "jpl_station_month_temporal_coverage.csv",
            "jpl_station_hour_of_day_profile.csv",
            "jpl_site_hourly_observed_load.csv",
        ],
        "interpretation_warning": (
            "Observed calendar-hour coverage is presence of at least one Static sample, "
            "not EVSE uptime. observed_power_sum_kw sums only stations with Power samples; "
            "missing stations are not treated as zero."
        ),
    }
    (OUTPUT_DIR / "jpl_temporal_coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n===== TEMPORAL COVERAGE RESULT =====")
    print(f"Rows scanned: {scanned_rows:,}")
    print(f"Rows in selected period: {selected_period_rows:,}")
    print(f"Station-hour buckets: {len(hourly):,}")
    print(f"Power coverage in selected records: {summary['power_sample_coverage_pct']:.3f}%")
    print(f"Hours with all selected stations having Power: {summary['hours_with_all_selected_stations_power']:,}")
    print(f"Output directory: {OUTPUT_DIR}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", default="2020-07", help="First local month, YYYY-MM.")
    parser.add_argument("--end-month", default="2020-11", help="Last local month inclusive, YYYY-MM.")
    parser.add_argument("--chunksize", type=int, default=500_000)
    parser.add_argument("--all-stations", action="store_true", help="Audit every station in the cleaned Static file.")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
