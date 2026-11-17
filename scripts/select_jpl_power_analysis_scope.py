"""Select candidate JPL EVSEs for the July-November 2020 Power analysis.

This selection is a screening step, not proof of continuous uptime.
A candidate must have at least one Static observation and non-null Power
measurements in each of the five local calendar months.

Run:
    python scripts/select_jpl_power_analysis_scope.py
    python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 95
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_DIR = ROOT / "data" / "inventory"
MONTHLY_COVERAGE_CANDIDATES = [
    INVENTORY_DIR / "jpl_sensor_coverage_all_static_by_station_month.csv",
    INVENTORY_DIR / "jpl_sensor_coverage_by_station_month.csv",
    INVENTORY_DIR / "jpl_sensor_coverage_by_station_month.csv.gz",
]
START_MONTH = "2020-07"
END_MONTH = "2020-11"
EXPECTED_MONTHS = pd.period_range(START_MONTH, END_MONTH, freq="M").astype(str).tolist()


def find_monthly_coverage_file() -> Path:
    for path in MONTHLY_COVERAGE_CANDIDATES:
        if path.exists():
            return path
    expected = "\n".join(str(path) for path in MONTHLY_COVERAGE_CANDIDATES)
    raise FileNotFoundError(
        "Could not find the full-Static station/month coverage file. Tried:\n" + expected
    )


def select_power_stations(
    monthly: pd.DataFrame,
    min_monthly_power_coverage: float = 99.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"station_id", "month", "total_samples", "power_samples"}
    missing = required - set(monthly.columns)
    if missing:
        raise ValueError(f"Monthly coverage file is missing columns: {sorted(missing)}")

    df = monthly.copy()
    df["station_id"] = df["station_id"].astype("string")
    df["month"] = df["month"].astype(str)
    df = df[df["month"].isin(EXPECTED_MONTHS)].copy()
    for col in ["total_samples", "power_samples"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "power_coverage_pct" not in df:
        df["power_coverage_pct"] = (
            100 * df["power_samples"] / df["total_samples"].replace(0, pd.NA)
        )
    else:
        df["power_coverage_pct"] = pd.to_numeric(
            df["power_coverage_pct"], errors="coerce"
        )

    all_station_ids = sorted(monthly["station_id"].dropna().astype(str).unique().tolist())
    rows = []
    for station_id in all_station_ids:
        group = df[df["station_id"].eq(station_id)]
        month_power = group.groupby("month")["power_samples"].sum().to_dict()
        month_coverage = group.groupby("month")["power_coverage_pct"].min().to_dict()
        active_months = sum(float(v) > 0 for v in group.groupby("month")["total_samples"].sum().values)
        months_with_power = sum(float(month_power.get(month, 0)) > 0 for month in EXPECTED_MONTHS)
        min_month_coverage = min(
            [float(month_coverage.get(month, 0) or 0) for month in EXPECTED_MONTHS]
        )
        total_samples = int(group["total_samples"].sum())
        power_samples = int(group["power_samples"].sum())
        rows.append({
            "station_id": station_id,
            "active_months": active_months,
            "months_with_power": months_with_power,
            "total_samples": total_samples,
            "power_samples": power_samples,
            "power_coverage_pct": 100 * power_samples / total_samples if total_samples else 0,
            "minimum_monthly_power_coverage_pct": min_month_coverage,
            "eligible": (
                active_months == len(EXPECTED_MONTHS)
                and months_with_power == len(EXPECTED_MONTHS)
                and min_month_coverage >= min_monthly_power_coverage
            ),
        })

    all_stations = pd.DataFrame(rows)
    eligible = all_stations[all_stations["eligible"]].sort_values(
        ["power_samples", "power_coverage_pct"], ascending=[False, False]
    )
    excluded = all_stations[~all_stations["eligible"]].copy()
    excluded["exclusion_reason"] = excluded.apply(
        lambda row: (
            "NOT_ALL_FIVE_MONTHS_ACTIVE"
            if row["active_months"] < len(EXPECTED_MONTHS)
            else "POWER_MISSING_IN_ONE_OR_MORE_MONTHS"
            if row["months_with_power"] < len(EXPECTED_MONTHS)
            else "MONTHLY_POWER_COVERAGE_BELOW_THRESHOLD"
        ),
        axis=1,
    )
    return eligible, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-monthly-power-coverage", type=float, default=99.0)
    args = parser.parse_args()
    if not 0 <= args.min_monthly_power_coverage <= 100:
        raise ValueError("Coverage threshold must be between 0 and 100.")

    source = find_monthly_coverage_file()
    monthly = pd.read_csv(source, dtype={"station_id": "string", "month": "string"})
    eligible, excluded = select_power_stations(
        monthly, args.min_monthly_power_coverage
    )

    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    eligible.to_csv(INVENTORY_DIR / "jpl_power_analysis_stations.csv", index=False)
    excluded.to_csv(INVENTORY_DIR / "jpl_power_analysis_station_exclusions.csv", index=False)

    summary = {
        "source_file": str(source),
        "window_start_month": START_MONTH,
        "window_end_month": END_MONTH,
        "expected_months": EXPECTED_MONTHS,
        "historical_station_ids_in_source": int(monthly["station_id"].nunique()),
        "stations_with_any_observation_in_window": int(
            monthly.loc[monthly["month"].isin(EXPECTED_MONTHS), "station_id"].nunique()
        ),
        "eligible_station_count": len(eligible),
        "excluded_station_count": len(excluded),
        "min_monthly_power_coverage_pct": args.min_monthly_power_coverage,
        "eligible_station_ids": eligible["station_id"].astype(str).tolist(),
    }
    (INVENTORY_DIR / "jpl_power_analysis_scope_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("===== JPL POWER ANALYSIS SCOPE =====")
    print(f"Historical station IDs in source: {summary['historical_station_ids_in_source']}")
    print(f"Stations with observations in Jul-Nov 2020: {summary['stations_with_any_observation_in_window']}")
    print(f"Eligible station IDs: {len(eligible)}")
    print(f"Excluded station IDs: {len(excluded)}")
    print(f"Minimum monthly Power coverage threshold: {args.min_monthly_power_coverage:.2f}%")
    print("\nEligible stations:")
    print(eligible.to_string(index=False))
    print("\nExclusion reasons:")
    if not excluded.empty:
        print(excluded["exclusion_reason"].value_counts().to_string())
    print(f"\nOutput directory: {INVENTORY_DIR}")


if (args := None) is None:
    pass


if __name__ == "__main__":
    main()
