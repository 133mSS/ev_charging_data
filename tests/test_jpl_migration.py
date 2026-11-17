import unittest
from pathlib import Path
import tempfile
import gzip

import pandas as pd

from src.transform.clean_static import extract_station_id, transform_session
from src.transform.audit_static_api_overlap import normalize_static_id
from src.transform.audit_static_api_metrics import classify_energy_quality
from src.transform.clean_api import transform_sessions, transform_user_inputs


class TestJPLFilenameAndMatching(unittest.TestCase):
    def test_extract_station_id_from_jpl_static_filename(self):
        filename = "1-1-178-817-2019-05-25T09-30-00-000000.csv.gz"
        self.assertEqual(extract_station_id(filename), "1-1-178-817")

    def test_normalize_static_id_to_api_style_key(self):
        normalized = normalize_static_id(
            "1-1-178-817",
            "1-1-178-817-2019-05-25T09-30-00-000000",
        )
        self.assertEqual(normalized, "1_1_178_817_2019-05-25 09:30:00.000000")

    def test_invalid_static_id_is_not_matched(self):
        self.assertIsNone(normalize_static_id("1-1-178-817", "bad-session-id"))

    def test_energy_quality_thresholds(self):
        self.assertEqual(classify_energy_quality(0.001), "HIGH_CONFIDENCE")
        self.assertEqual(classify_energy_quality(0.1), "REVIEW_SMALL")
        self.assertEqual(classify_energy_quality(0.8), "REVIEW_MEDIUM")
        self.assertEqual(classify_energy_quality(2.0), "REVIEW_LARGE")
        self.assertEqual(classify_energy_quality(8.0), "MAJOR_OUTLIER")


class TestJPLTransformations(unittest.TestCase):
    def test_has_user_metadata_requires_non_empty_user_inputs(self):
        rows = [
            {"sessionID": "s1", "userID": "u1", "userInputs": []},
            {"sessionID": "s2", "userID": "u2", "userInputs": [{"kWhRequested": 5}]},
        ]
        frame = transform_sessions(rows)
        self.assertEqual(frame["has_user_metadata"].tolist(), [False, True])

    def test_user_input_rows_keep_each_change(self):
        rows = [{
            "sessionID": "s1",
            "userInputs": [
                {"userID": "u1", "kWhRequested": 5, "modifiedAt": "2019-05-25T16:00:00Z"},
                {"userID": "u1", "kWhRequested": 7, "modifiedAt": "2019-05-25T16:05:00Z"},
            ],
        }]
        frame = transform_user_inputs(rows)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["kwh_requested"].tolist(), [5, 7])
        self.assertEqual(frame["input_id"].tolist(), [1, 2])

    def test_static_file_transform_preserves_real_measurements(self):
        csv_text = (
            "timestamp,Charging Current (A),Actual Pilot (A),Voltage (V),Charging State,"
            "Energy Delivered (kWh),Power (kW)\n"
            "2019-05-25T16:00:00Z,16,32,240,Charging,0.1,3.84\n"
            "2019-05-25T16:01:00Z,16,32,240,Charging,0.2,3.84\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "1-1-178-817-2019-05-25T09-30-00-000000.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write(csv_text)
            frame = transform_session(path)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["station_id"].unique().tolist(), ["1-1-178-817"])
        self.assertEqual(frame["power_kw"].tolist(), [3.84, 3.84])
        self.assertTrue(frame["timestamp"].dt.tz is not None)


if __name__ == "__main__":
    unittest.main()
