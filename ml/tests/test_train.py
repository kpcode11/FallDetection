import json
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR))
import server  # noqa: E402
import train  # noqa: E402


def recording_text(label: int, rows: int = 750) -> str:
    samples = np.full((rows, 9), 0.0)
    samples[:, 6:9] = 591  # approximately 1g magnitude after conversion
    if label:
        samples[160:260, 6:9] = 80
        samples[260:360, 6:9] = 2800
    return "\n".join(";".join(str(int(value)) for value in row) + ";" for row in samples)


class SisFallTrainingTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> None:
        for subject in (1, 2):
            for activity, label in (("D01", 0), ("F01", 1)):
                (root / f"{activity}_SA{subject:02d}_R01.txt").write_text(recording_text(label), encoding="utf-8")

    def test_filename_and_scaling(self):
        info = train.parse_recording_name(Path("F03_SA12_R04.txt"))
        self.assertEqual((info.activity, info.subject, info.trial, info.label), ("F03", 12, 4, 1))
        elderly = train.parse_recording_name(Path("D05_SE03_R02.txt"))
        self.assertEqual((elderly.activity, elderly.subject, elderly.trial, elderly.label), ("D05", 103, 2, 0))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "D01_SA01_R01.txt"
            path.write_text("0;0;0;0;0;0;1024;-1024;512;\n", encoding="utf-8")
            values = train.parse_sisfall_recording(train.parse_recording_name(path))
        np.testing.assert_allclose(values, [[1.0, -1.0, 0.5]])

    def test_original_comma_delimited_row_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "D01_SA01_R01.txt"
            path.write_text("0,0,0,0,0,0,1024,-1024,512;\n", encoding="utf-8")
            values = train.parse_sisfall_recording(train.parse_recording_name(path))
        np.testing.assert_allclose(values, [[1.0, -1.0, 0.5]])

    def test_decimate_and_sma(self):
        native = np.arange(40, dtype=float).reshape(40, 1) * np.ones((1, 3))
        np.testing.assert_array_equal(train.decimate_to_device_rate(native).shape, (2, 3))
        window = np.column_stack([np.ones(train.WINDOW_SIZE), np.ones(train.WINDOW_SIZE), np.zeros(train.WINDOW_SIZE)])
        features = train.extract_features(window)
        self.assertEqual(len(features), len(train.FEATURE_NAMES))
        self.assertAlmostEqual(features[5], 2.0, places=5)
        self.assertGreater(abs(features[0] - features[5]), 0.2)

    def test_missing_data_fails_and_windows_do_not_cross_recordings(self):
        with self.assertRaises(train.DatasetError):
            train.build_dataset(Path("does-not-exist"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_fixture(root)
            dataset = train.build_dataset(root)
        # 750 native samples -> 38 at 10 Hz -> one 30-sample window per recording.
        self.assertEqual(len(dataset.features), 4)
        self.assertEqual({item["start_sample"] for item in dataset.provenance}, {0})
        self.assertTrue(all("_" in item["recording"] for item in dataset.provenance))

    def test_training_writes_metadata_and_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_fixture(root)
            model_path, artifacts = root / "model.joblib", root / "artifacts"
            result = train.train_and_evaluate(root, model_path, artifacts, estimators=5)
            bundle, payload = joblib.load(model_path), json.loads((artifacts / "evaluation.json").read_text(encoding="utf-8"))
        self.assertIn("model", bundle)
        self.assertEqual(bundle["metadata"]["feature_names"], train.FEATURE_NAMES)
        self.assertEqual(bundle["metadata"]["sample_rate_hz"], 10.0)
        self.assertEqual(bundle["metadata"]["window_size_samples"], 30)
        self.assertEqual(payload["evaluation"]["folds"], 2)
        self.assertEqual(result["dataset"].summary["source"], "SisFall")

    def test_synthetic_is_explicit_and_valid(self):
        dataset = train.build_synthetic_dataset()
        self.assertEqual(dataset.summary["source"], "synthetic (explicit smoke-test mode)")
        self.assertEqual(set(dataset.labels), {0, 1})

    def test_mqtt_window_must_match_trained_size(self):
        ok = np.ones((train.WINDOW_SIZE, 3))
        np.testing.assert_array_equal(server.validate_sensor_window(ok).shape, (30, 3))
        with self.assertRaises(ValueError):
            server.validate_sensor_window(np.ones((29, 3)))


if __name__ == "__main__":
    unittest.main()
