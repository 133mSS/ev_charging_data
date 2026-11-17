from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import CLEAN_STATIC_FILE as STATIC_FILE, CLEAN_SESSIONS_FILE as API_FILE, SESSION_MAPPING_FILE as MAPPING_FILE, SESSION_QUALITY_FILE as OUTPUT_FILE



# Ngưỡng phân loại chênh lệch năng lượng (kWh) giữa API và static:
# |static_max_energy_kwh - api_energy_kwh|.
ENERGY_QUALITY_BINS = [
    (0.001, "HIGH_CONFIDENCE"),  # <= 0.001 kWh
    (0.5, "REVIEW_SMALL"),       # <= 0.5 kWh
    (1.0, "REVIEW_MEDIUM"),      # <= 1 kWh
    (5.0, "REVIEW_LARGE"),       # <= 5 kWh
]
ENERGY_QUALITY_FALLBACK = "MAJOR_OUTLIER"  # > 5 kWh


def classify_energy_quality(abs_diff_kwh: float) -> str:
    """Gán nhãn chất lượng năng lượng cho một session đã ghép."""
    if pd.isna(abs_diff_kwh):
        return "NO_ENERGY_DATA"

    for upper_bound, label in ENERGY_QUALITY_BINS:
        if abs_diff_kwh <= upper_bound:
            return label

    return ENERGY_QUALITY_FALLBACK


def main() -> None:
    print("===== STATIC / API METRICS AUDIT & ENERGY QUALITY =====")

    mapping = pd.read_csv(MAPPING_FILE, dtype=str)

    matched = mapping.loc[
        mapping["match_status"].eq("MATCHED"),
        ["station_id", "static_session_id", "api_session_id"],
    ].copy()

    matched_ids = set(matched["static_session_id"])

    # Đọc API session metadata.
    api = pd.read_csv(
        API_FILE,
        usecols=[
            "station_id",
            "session_id",
            "connection_time",
            "disconnect_time",
            "energy_kwh",
        ],
        dtype={
            "station_id": str,
            "session_id": str,
        },
    )

    api = api.rename(columns={
        "station_id": "api_station_id",
        "session_id": "api_session_id",
        "connection_time": "api_connection_time",
        "disconnect_time": "api_disconnect_time",
        "energy_kwh": "api_energy_kwh",
    })

    api["api_connection_time"] = pd.to_datetime(
        api["api_connection_time"], utc=True, errors="coerce"
    )
    api["api_disconnect_time"] = pd.to_datetime(
        api["api_disconnect_time"], utc=True, errors="coerce"
    )
    api["api_energy_kwh"] = pd.to_numeric(
        api["api_energy_kwh"], errors="coerce"
    )

    # Tổng hợp static theo từng session bằng chunks.
    partial_stats = []
    partial_last_energy = []
    row_offset = 0

    columns = [
        "station_id",
        "session_id",
        "timestamp",
        "voltage_v",
        "power_kw",
        "charging_state",
        "energy_delivered_kwh",
    ]

    for chunk in pd.read_csv(
        STATIC_FILE,
        usecols=columns,
        chunksize=500_000,
    ):
        chunk["_source_row"] = range(
            row_offset, row_offset + len(chunk)
        )
        row_offset += len(chunk)

        chunk = chunk[
            chunk["session_id"].isin(matched_ids)
        ].copy()

        if chunk.empty:
            continue

        chunk["timestamp"] = pd.to_datetime(
            chunk["timestamp"], utc=True, errors="coerce"
        )

        for col in [
            "voltage_v",
            "power_kw",
            "energy_delivered_kwh",
        ]:
            chunk[col] = pd.to_numeric(
                chunk[col], errors="coerce"
            )

        grouped = chunk.groupby("session_id").agg(
            sample_count=("timestamp", "size"),
            static_first_ts=("timestamp", "min"),
            static_last_ts=("timestamp", "max"),
            voltage_present=("voltage_v", "count"),
            static_max_energy_kwh=("energy_delivered_kwh", "max"),
            power_present=("power_kw", "count"),
            state_present=("charging_state", "count"),
            
        ).reset_index()
        
        partial_stats.append(grouped)
        
        # Lấy giá trị energy cuối cùng theo timestamp,
        # không lấy MAX vì điều đó có thể che khuất diễn biến.
        energy_rows = chunk.dropna(
            subset=["timestamp", "energy_delivered_kwh"]
        ).sort_values(
            ["session_id", "timestamp", "_source_row"]
        )

        if not energy_rows.empty:
            last = energy_rows.groupby(
                "session_id", as_index=False
            ).tail(1)

            partial_last_energy.append(
                last[
                    [
                        "session_id",
                        "timestamp",
                        "energy_delivered_kwh",
                        "_source_row",
                    ]
                ].rename(columns={
                    "session_id": "static_session_id",
                    "timestamp": "static_last_energy_ts",
                    "energy_delivered_kwh": "static_last_energy_kwh",
                    "_source_row": "last_energy_source_row",
                })
            )

    if not partial_stats:
        raise RuntimeError("No matched static measurements found.")

    stats = pd.concat(
        partial_stats, ignore_index=True
    ).groupby("session_id").agg(
        sample_count=("sample_count", "sum"),
        static_first_ts=("static_first_ts", "min"),
        static_max_energy_kwh=("static_max_energy_kwh", "max"),
        static_last_ts=("static_last_ts", "max"),
        voltage_present=("voltage_present", "sum"),
        power_present=("power_present", "sum"),
        state_present=("state_present", "sum"),
    ).reset_index()

    if partial_last_energy:
        last_energy = pd.concat(
            partial_last_energy, ignore_index=True
        )

        last_energy = last_energy.sort_values(
            [
                "static_session_id",
                "static_last_energy_ts",
                "last_energy_source_row",
            ]
        ).drop_duplicates(
            "static_session_id", keep="last"
        )
    else:
        last_energy = pd.DataFrame(
            columns=[
                "static_session_id",
                "static_last_energy_ts",
                "static_last_energy_kwh",
                "last_energy_source_row",
            ]
        )

    audit = matched.merge(
        stats,
        left_on="static_session_id",
        right_on="session_id",
        how="left",
        validate="one_to_one",
    ).drop(columns=["session_id"])

    audit = audit.merge(
        last_energy,
        on="static_session_id",
        how="left",
        validate="one_to_one",
    )

    audit = audit.merge(
        api,
        on="api_session_id",
        how="left",
        validate="one_to_one",
    )

    audit["station_id_matches"] = (
        audit["station_id"] == audit["api_station_id"]
    )

    audit["start_abs_diff_seconds"] = (
        audit["static_first_ts"]
        - audit["api_connection_time"]
    ).dt.total_seconds().abs()

    audit["end_abs_diff_seconds"] = (
        audit["static_last_ts"]
        - audit["api_disconnect_time"]
    ).dt.total_seconds().abs()

    audit["energy_abs_diff_kwh"] = (
        audit["static_max_energy_kwh"]
        - audit["api_energy_kwh"]
    ).abs()

    audit["energy_quality"] = audit["energy_abs_diff_kwh"].map(
        classify_energy_quality
    )

    audit["energy_diff_pct"] = (
        100.0
        * audit["energy_abs_diff_kwh"]
        / audit["api_energy_kwh"]
    )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit.to_csv(OUTPUT_FILE, index=False)

    # Báo cáo tổng hợp.
    print("Matched sessions audited:", len(audit))
    print(
        "Station ID matches:",
        int(audit["station_id_matches"].sum()),
    )

    total_samples = audit["sample_count"].sum()

    print(
        "Voltage coverage (%):",
        round(
            100 * audit["voltage_present"].sum() / total_samples,
            3,
        ),
    )
    print(
        "Power coverage (%):",
        round(
            100 * audit["power_present"].sum() / total_samples,
            3,
        ),
    )
    print(
        "Charging-state coverage (%):",
        round(
            100 * audit["state_present"].sum() / total_samples,
            3,
        ),
    )

    def print_delta_summary(label, column):
        values = audit[column].dropna()

        if values.empty:
            print(f"{label}: no comparable values")
            return

        print(f"\n{label}")
        print("Comparable sessions:", len(values))
        print("Median absolute difference:", round(values.median(), 3))
        print("P95 absolute difference:", round(values.quantile(0.95), 3))
        print("Maximum absolute difference:", round(values.max(), 3))

    print_delta_summary(
        "Start-time difference (seconds)",
        "start_abs_diff_seconds",
    )

    print_delta_summary(
        "End-time difference (seconds)",
        "end_abs_diff_seconds",
    )

    print_delta_summary(
        "Energy difference (kWh)",
        "energy_abs_diff_kwh",
    )

    print("\nEnergy quality labels:")
    print(audit["energy_quality"].value_counts().to_string())

    print("\nQuality report:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
