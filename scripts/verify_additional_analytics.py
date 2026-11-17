"""Recompute the added dashboard insights from the cleaned, real ACN-Data files.

Run after the transform stage:
    python scripts/verify_additional_analytics.py

This script does not generate or mutate source data. It only reads the two cleaned
CSV files and prints reproducible checks for the additional analyses.
"""
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import CLEAN_SESSIONS_FILE as SESSIONS_FILE, CLEAN_USER_INPUTS_FILE as USER_INPUTS_FILE


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = [str(path) for path in (SESSIONS_FILE, USER_INPUTS_FILE) if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Thiếu dữ liệu đã làm sạch. Hãy chạy `python run_pipeline.py --stage transform` trước:\n"
            + "\n".join(missing)
        )

    sessions = pd.read_csv(SESSIONS_FILE)
    requests = pd.read_csv(USER_INPUTS_FILE)

    for column in ("connection_time", "disconnect_time", "done_charging_time"):
        sessions[column] = pd.to_datetime(sessions[column], utc=True, errors="coerce")
    requests["modified_at"] = pd.to_datetime(
        requests["modified_at"], utc=True, errors="coerce"
    )
    return sessions, requests


def summarize_post_charge(sessions: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    valid = sessions.dropna(
        subset=["connection_time", "disconnect_time", "done_charging_time"]
    ).copy()
    valid = valid[
        valid["done_charging_time"].ge(valid["connection_time"])
        & valid["done_charging_time"].le(valid["disconnect_time"])
    ].copy()
    valid["post_charge_connection_minutes"] = (
        (valid["disconnect_time"] - valid["done_charging_time"])
        .dt.total_seconds()
        .div(60.0)
        .round(3)
    )

    values = valid["post_charge_connection_minutes"]
    summary = {
        "valid_sessions": int(len(valid)),
        "coverage_pct": float(100.0 * len(valid) / len(sessions)) if len(sessions) else 0.0,
        "median_minutes": float(values.median()) if len(values) else None,
        "mean_minutes": float(values.mean()) if len(values) else None,
        "over_30_minutes_pct": float(100.0 * values.gt(30).mean()) if len(values) else None,
        "over_60_minutes_pct": float(100.0 * values.gt(60).mean()) if len(values) else None,
    }
    by_station = (
        valid.groupby("station_id")["post_charge_connection_minutes"]
        .agg(session_count="count", median_minutes="median", p75_minutes=lambda x: x.quantile(0.75))
        .sort_values("median_minutes", ascending=False)
    )
    return by_station, summary


def summarize_station_usage(sessions: pd.DataFrame) -> pd.DataFrame:
    # Match warehouse.fact_charging_sessions NUMERIC(10,3) precision.
    sessions = sessions.copy()
    sessions["energy_kwh"] = sessions["energy_kwh"].round(3)
    result = (
        sessions.groupby("station_id")
        .agg(
            session_count=("session_id", "count"),
            total_energy_kwh=("energy_kwh", "sum"),
            avg_energy_per_session_kwh=("energy_kwh", "mean"),
        )
        .sort_values("total_energy_kwh", ascending=False)
    )
    result["energy_share_pct"] = (
        100.0 * result["total_energy_kwh"] / result["total_energy_kwh"].sum()
    )
    return result


def latest_requests_vs_delivery(
    sessions: pd.DataFrame, requests: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    latest = (
        requests.dropna(subset=["session_id", "modified_at", "kwh_requested"])
        .sort_values(["session_id", "modified_at", "input_id"])
        .drop_duplicates("session_id", keep="last")
    )
    joined = latest.merge(
        sessions[["session_id", "station_id", "energy_kwh"]],
        on="session_id",
        how="inner",
        validate="one_to_one",
    )
    joined = joined[joined["kwh_requested"].gt(0)].copy()
    # Match warehouse.fact_charging_sessions NUMERIC(10,3) precision.
    joined["energy_kwh"] = joined["energy_kwh"].round(3)
    joined["delivered_vs_requested_pct"] = (
        100.0 * joined["energy_kwh"] / joined["kwh_requested"]
    )
    joined["energy_gap_kwh"] = joined["energy_kwh"] - joined["kwh_requested"]

    ratio = joined["delivered_vs_requested_pct"]
    summary = {
        "sessions_with_requests": int(len(joined)),
        "coverage_pct": float(100.0 * len(joined) / len(sessions)) if len(sessions) else 0.0,
        "requested_kwh_sum": float(joined["kwh_requested"].sum()),
        "delivered_kwh_sum": float(joined["energy_kwh"].sum()),
        "aggregate_delivered_vs_requested_pct": float(
            100.0 * joined["energy_kwh"].sum() / joined["kwh_requested"].sum()
        ) if joined["kwh_requested"].sum() else None,
        "median_session_ratio_pct": float(ratio.median()) if len(ratio) else None,
        "mean_session_ratio_pct": float(ratio.mean()) if len(ratio) else None,
        "below_50_pct": float(100.0 * ratio.lt(50).mean()) if len(ratio) else None,
        "from_50_to_below_90_pct": float(
            100.0 * (ratio.ge(50) & ratio.lt(90)).mean()
        ) if len(ratio) else None,
        "at_least_90_pct": float(100.0 * ratio.ge(90).mean()) if len(ratio) else None,
    }
    return joined, summary


def main() -> None:
    sessions, requests = load_inputs()
    station_rank = summarize_station_usage(sessions)
    station_post, post_summary = summarize_post_charge(sessions)
    request_rows, request_summary = latest_requests_vs_delivery(sessions, requests)

    print("===== DATASET COUNTS =====")
    print(f"Charging sessions: {len(sessions):,}")
    print(f"User input rows: {len(requests):,}")
    print(f"Sessions with user inputs: {requests['session_id'].nunique():,}")

    print("\n===== STATION RANKING =====")
    print(station_rank.round(2).to_string())
    top_energy = station_rank.iloc[0]
    top_sessions = station_rank.loc[station_rank["session_count"].idxmax()]
    print(
        f"\nTop energy station: {station_rank.index[0]} "
        f"({top_energy['total_energy_kwh']:,.3f} kWh; {top_energy['energy_share_pct']:.2f}%)"
    )
    print(
        f"Top session-count station: {station_rank['session_count'].idxmax()} "
        f"({int(top_sessions['session_count']):,} sessions)"
    )

    print("\n===== POST-CHARGE CONNECTION INTERVAL =====")
    for key, value in post_summary.items():
        print(f"{key}: {value}")
    print("\nBy station:")
    print(station_post.round(2).to_string())

    print("\n===== LATEST USER REQUEST VS SESSION ENERGY =====")
    for key, value in request_summary.items():
        print(f"{key}: {value}")
    print("\nBy station (median ratio):")
    print(
        request_rows.groupby("station_id")["delivered_vs_requested_pct"]
        .agg(session_count="count", median_ratio_pct="median")
        .sort_values("median_ratio_pct")
        .round(2)
        .to_string()
    )

    print("\nVerification completed. No source data was modified or generated.")


if __name__ == "__main__":
    main()
