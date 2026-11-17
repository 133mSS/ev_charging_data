import unittest

import pandas as pd

from scripts.audit_jpl_temporal_coverage import (
    expected_hours_in_local_month,
    build_site_hourly_observed_load,
)
from scripts.select_jpl_power_analysis_scope import select_power_stations, EXPECTED_MONTHS


class TestJPLTemporalCoverage(unittest.TestCase):
    def test_expected_hours_accounts_for_daylight_saving(self):
        # November 2020 in Los Angeles includes the fall-back DST hour.
        self.assertEqual(expected_hours_in_local_month("2020-11"), 721)
        self.assertEqual(expected_hours_in_local_month("2020-07"), 744)

    def test_power_scope_requires_all_months_and_monthly_coverage(self):
        rows = []
        for station in ["EVSE_A", "EVSE_B"]:
            for month in EXPECTED_MONTHS:
                rows.append({
                    "station_id": station,
                    "month": month,
                    "total_samples": 1000,
                    "power_samples": 1000 if station == "EVSE_A" else (0 if month == "2020-09" else 1000),
                    "power_coverage_pct": 100 if station == "EVSE_A" else (0 if month == "2020-09" else 100),
                })
        eligible, excluded = select_power_stations(pd.DataFrame(rows), 99.0)
        self.assertEqual(eligible["station_id"].tolist(), ["EVSE_A"])
        self.assertEqual(excluded["station_id"].tolist(), ["EVSE_B"])

    def test_power_scope_rejects_month_below_coverage_threshold(self):
        rows = []
        for month in EXPECTED_MONTHS:
            rows.append({
                "station_id": "EVSE_A",
                "month": month,
                "total_samples": 1000,
                "power_samples": 980,
                "power_coverage_pct": 98.0,
            })
        eligible, excluded = select_power_stations(pd.DataFrame(rows), 99.0)
        self.assertTrue(eligible.empty)
        self.assertEqual(len(excluded), 1)

    def test_site_hourly_grid_includes_hours_without_observations(self):
        hourly = pd.DataFrame([{
            "station_id": "EVSE_A",
            "utc_hour_start": pd.Timestamp("2020-07-01T07:00:00Z"),
            "local_date": "2020-07-01",
            "local_hour": 0,
            "utc_offset": "-0700",
            "power_samples": 10,
            "avg_power_kw": 7.5,
            "total_samples": 10,
        }])
        start_local = pd.Timestamp("2020-07-01 00:00:00", tz="America/Los_Angeles")
        end_local = pd.Timestamp("2020-07-01 02:00:00", tz="America/Los_Angeles")

        site = build_site_hourly_observed_load(
            hourly, 2, start_local, end_local
        )

        self.assertEqual(len(site), 2)
        self.assertEqual(site.iloc[0]["stations_with_power"], 1)
        self.assertEqual(site.iloc[0]["selected_station_power_coverage_pct"], 50.0)
        self.assertEqual(site.iloc[0]["sum_station_hour_mean_power_kw"], 7.5)
        self.assertTrue(site.iloc[0]["site_hour_has_any_observation"])
        self.assertEqual(site.iloc[1]["stations_with_power"], 0)
        self.assertEqual(site.iloc[1]["selected_station_power_coverage_pct"], 0.0)
        self.assertFalse(site.iloc[1]["site_hour_has_any_observation"])
        self.assertTrue(pd.isna(site.iloc[1]["sum_station_hour_mean_power_kw"]))


if __name__ == "__main__":
    unittest.main()
