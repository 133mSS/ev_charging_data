import unittest

import pandas as pd

from scripts.verify_additional_analytics import (
    latest_requests_vs_delivery,
    summarize_post_charge,
    summarize_station_usage,
)


class TestJPLResearchAnalytics(unittest.TestCase):
    def test_q2_station_usage_ranking_uses_session_and_energy_measures(self):
        sessions = pd.DataFrame([
            {"session_id": "S1", "station_id": "EVSE_A", "energy_kwh": 5.0},
            {"session_id": "S2", "station_id": "EVSE_A", "energy_kwh": 3.0},
            {"session_id": "S3", "station_id": "EVSE_B", "energy_kwh": 10.0},
        ])

        result = summarize_station_usage(sessions)

        self.assertEqual(result.index[0], "EVSE_B")
        self.assertEqual(int(result.loc["EVSE_A", "session_count"]), 2)
        self.assertAlmostEqual(result.loc["EVSE_A", "total_energy_kwh"], 8.0)
        self.assertAlmostEqual(result["energy_share_pct"].sum(), 100.0)

    def test_q3_post_charge_interval_excludes_invalid_time_order(self):
        sessions = pd.DataFrame([
            {
                "session_id": "S1",
                "station_id": "EVSE_A",
                "connection_time": "2020-07-01T08:00:00Z",
                "done_charging_time": "2020-07-01T09:00:00Z",
                "disconnect_time": "2020-07-01T10:00:00Z",
                "energy_kwh": 6.0,
            },
            {
                "session_id": "S2",
                "station_id": "EVSE_A",
                "connection_time": "2020-07-01T08:00:00Z",
                "done_charging_time": "2020-07-01T11:00:00Z",
                "disconnect_time": "2020-07-01T10:00:00Z",
                "energy_kwh": 6.0,
            },
            {
                "session_id": "S3",
                "station_id": "EVSE_B",
                "connection_time": "2020-07-01T08:00:00Z",
                "done_charging_time": None,
                "disconnect_time": "2020-07-01T10:00:00Z",
                "energy_kwh": 2.0,
            },
        ])
        for col in ["connection_time", "done_charging_time", "disconnect_time"]:
            sessions[col] = pd.to_datetime(sessions[col], utc=True, errors="coerce")

        by_station, summary = summarize_post_charge(sessions)

        self.assertEqual(summary["valid_sessions"], 1)
        self.assertEqual(summary["median_minutes"], 60.0)
        self.assertEqual(int(by_station.loc["EVSE_A", "session_count"]), 1)

    def test_q4_uses_latest_input_event_not_previous_valid_request(self):
        sessions = pd.DataFrame([
            {"session_id": "S1", "station_id": "EVSE_A", "energy_kwh": 6.0},
            {"session_id": "S2", "station_id": "EVSE_B", "energy_kwh": 5.0},
        ])
        requests = pd.DataFrame([
            {
                "session_id": "S1", "input_id": 1,
                "modified_at": "2020-07-01T08:00:00Z", "kwh_requested": 4.0,
            },
            {
                "session_id": "S1", "input_id": 2,
                "modified_at": "2020-07-01T09:00:00Z", "kwh_requested": None,
            },
            {
                "session_id": "S2", "input_id": 1,
                "modified_at": "2020-07-01T08:00:00Z", "kwh_requested": 5.0,
            },
            {
                "session_id": "S2", "input_id": 2,
                "modified_at": "2020-07-01T10:00:00Z", "kwh_requested": 8.5,
            },
        ])
        requests["modified_at"] = pd.to_datetime(
            requests["modified_at"], utc=True, errors="coerce"
        )

        result, summary = latest_requests_vs_delivery(sessions, requests)

        self.assertEqual(summary["sessions_with_requests"], 1)
        self.assertEqual(result["session_id"].tolist(), ["S2"])
        self.assertAlmostEqual(result.iloc[0]["kwh_requested"], 8.5)
        self.assertAlmostEqual(
            result.iloc[0]["delivered_vs_requested_pct"],
            100.0 * 5.0 / 8.5,
        )


if __name__ == "__main__":
    unittest.main()
