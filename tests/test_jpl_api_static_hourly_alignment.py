import unittest

import pandas as pd

from scripts.audit_jpl_api_static_hourly_alignment import (
    build_alignment_frame,
    split_interval_into_utc_hours,
)


class TestJPLAPIStaticHourlyAlignment(unittest.TestCase):
    def test_interval_is_split_at_utc_hour_boundaries(self):
        buckets = split_interval_into_utc_hours(
            "2020-07-01T10:30:00Z",
            "2020-07-01T12:15:00Z",
        )
        self.assertEqual(
            [(hour.isoformat(), round(minutes, 2)) for hour, minutes in buckets],
            [
                ("2020-07-01T10:00:00+00:00", 30.0),
                ("2020-07-01T11:00:00+00:00", 60.0),
                ("2020-07-01T12:00:00+00:00", 15.0),
            ],
        )

    def test_interval_is_clipped_to_analysis_window(self):
        buckets = split_interval_into_utc_hours(
            "2020-07-01T10:15:00Z",
            "2020-07-01T12:45:00Z",
            "2020-07-01T11:00:00Z",
            "2020-07-01T12:00:00Z",
        )
        self.assertEqual(len(buckets), 1)
        self.assertEqual(buckets[0][0].isoformat(), "2020-07-01T11:00:00+00:00")
        self.assertEqual(buckets[0][1], 60.0)

    def test_invalid_or_empty_interval_returns_no_buckets(self):
        self.assertEqual(
            split_interval_into_utc_hours(
                "2020-07-01T12:00:00Z",
                "2020-07-01T12:00:00Z",
            ),
            [],
        )
        self.assertEqual(
            split_interval_into_utc_hours(None, "2020-07-01T12:00:00Z"),
            [],
        )

    def test_alignment_keeps_api_only_and_static_only_evidence_separate(self):
        hour = pd.Timestamp("2020-07-01T10:00:00Z")
        api = {
            ("EVSE_A", hour): {
                "api_session_ids": {"API_MATCHED", "API_ONLY"},
                "matched_api_session_ids": {"API_MATCHED"},
                "api_only_session_ids": {"API_ONLY"},
                "api_session_minutes_sum": 45.0,
            }
        }
        static = {
            ("EVSE_A", hour): {
                "total_samples": 10,
                "power_samples": 10,
                "power_sum_kw": 25.0,
                "power_max_kw": 5.0,
                "current_samples": 10,
                "current_sum_a": 80.0,
                "voltage_samples": 10,
                "static_session_ids": {"STATIC_MATCHED", "STATIC_ONLY"},
                "matched_api_session_ids_with_samples": {"API_MATCHED"},
                "static_only_session_ids": {"STATIC_ONLY"},
                "unmapped_static_session_ids": set(),
            }
        }

        result = build_alignment_frame(api, static)
        row = result.iloc[0]

        self.assertEqual(row["api_sessions_overlapping_hour"], 2)
        self.assertEqual(row["api_sessions_matched_to_static"], 1)
        self.assertEqual(row["api_sessions_api_only"], 1)
        self.assertEqual(row["static_sessions_with_samples"], 2)
        self.assertEqual(row["static_matched_api_sessions_with_samples"], 1)
        self.assertEqual(row["static_only_sessions_with_samples"], 1)
        self.assertEqual(row["static_power_sample_coverage_pct"], 100.0)
        self.assertEqual(row["static_mean_sample_power_kw"], 2.5)


if __name__ == "__main__":
    unittest.main()
