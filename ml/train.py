"""Train and validate the fall classifier on real SisFall recordings."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
from scipy.signal import butter, filtfilt
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = MODULE_DIR.parent / "SisFall_dataset"
DEFAULT_MODEL_OUTPUT = MODULE_DIR / "fall_detection_model.joblib"
DEFAULT_ARTIFACTS_DIR = MODULE_DIR / "artifacts"
# Match FallDetection.ino: 3-second MQTT windows at ~10 Hz (delay(100), WINDOW_SIZE=30).
SISFALL_NATIVE_FS, DECIMATE_FACTOR = 200.0, 20
WINDOW_SIZE, WINDOW_STEP, CUTOFF_FREQ, FS = 30, 15, 2.0, 10.0
FEATURE_NAMES = ["mean_magnitude_g", "std_magnitude_g", "min_magnitude_g", "max_magnitude_g", "range_magnitude_g", "sma_g", "peak_jerk_g_per_sample"]

# SisFall columns 0:3 are ADXL345 acceleration, 3:6 ITG3200 gyro, and 6:9
# MMA8451Q acceleration. Its +/-8g, 14-bit output has 1024 counts per g.
MMA8451Q_COLUMNS, MMA8451Q_G_PER_LSB = (6, 7, 8), 1.0 / 1024.0
FILENAME_RE = re.compile(r"^(?P<activity>[DF]\d{2})_(?P<subject>S[AE]\d{2})_R(?P<trial>\d{2})\.txt$", re.I)


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class RecordingInfo:
    path: Path
    activity: str
    subject: int
    trial: int
    label: int


@dataclass
class WindowDataset:
    features: np.ndarray
    labels: np.ndarray
    groups: np.ndarray
    provenance: list[dict]
    summary: dict


def low_pass_filter(data: np.ndarray, cutoff: float = CUTOFF_FREQ, fs: float = FS, order: int = 4) -> np.ndarray:
    if len(data) <= 3 * (order + 1):
        raise ValueError(f"Signal needs at least {3 * (order + 1) + 1} samples; got {len(data)}.")
    b, a = butter(order, cutoff / (0.5 * fs), btype="low", analog=False)
    return filtfilt(b, a, data)


def extract_features(window_acc: np.ndarray) -> list[float]:
    """Extract the deployed seven features from an N x 3 accelerometer window in g."""
    values = np.asarray(window_acc, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"Expected an N x 3 acceleration window, got {values.shape}.")
    if not np.isfinite(values).all():
        raise ValueError("Acceleration window contains non-finite values.")
    filtered = low_pass_filter(np.sqrt(np.sum(values**2, axis=1)))
    minimum, maximum = float(filtered.min()), float(filtered.max())
    jerk = np.diff(filtered)
    sma = float(np.mean(np.sum(np.abs(values), axis=1)))
    return [float(filtered.mean()), float(filtered.std()), minimum, maximum, maximum - minimum, sma, float(np.abs(jerk).max()) if len(jerk) else 0.0]


def parse_recording_name(path: Path) -> RecordingInfo | None:
    match = FILENAME_RE.match(path.name)
    if not match:
        return None
    activity = match.group("activity").upper()
    subject_code = match.group("subject").upper()
    # SA01 and SE01 share numeric suffixes; offset elderly IDs so LOSO groups stay unique.
    subject_id = int(subject_code[2:]) + (0 if subject_code.startswith("SA") else 100)
    return RecordingInfo(path, activity, subject_id, int(match.group("trial")), int(activity.startswith("F")))


def discover_recordings(data_dir: Path) -> list[RecordingInfo]:
    if not data_dir.is_dir():
        raise DatasetError(f"SisFall dataset directory not found: {data_dir}. Download/extract the original text files there or pass --data-dir. Use --synthetic only for smoke tests.")
    result = [info for path in data_dir.rglob("*.txt") if (info := parse_recording_name(path))]
    if not result:
        raise DatasetError(f"No canonical recordings found under {data_dir}; expected names such as D01_SA01_R01.txt.")
    return sorted(result, key=lambda info: str(info.path))


def parse_sisfall_recording(info: RecordingInfo) -> np.ndarray:
    """Load and convert the MMA8451Q (columns 6--8) to g from one recording."""
    rows = []
    try:
        lines = info.path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DatasetError(f"Could not read {info.path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not (line := line.strip()):
            continue
        # Original SisFall rows are comma-delimited with a trailing semicolon;
        # accept semicolon-delimited repackagings too.
        payload = line.rstrip(";").strip()
        delimiter = "," if "," in payload else ";"
        fields = [item.strip() for item in payload.split(delimiter)]
        if len(fields) < 9:
            raise DatasetError(f"{info.path}:{line_number} has {len(fields)} columns; expected at least 9 SisFall signals.")
        try:
            row = [float(item) for item in fields]
        except ValueError as exc:
            raise DatasetError(f"{info.path}:{line_number} contains a non-numeric value.") from exc
        if not np.isfinite(row).all():
            raise DatasetError(f"{info.path}:{line_number} contains a non-finite value.")
        rows.append(row)
    if not rows:
        raise DatasetError(f"{info.path} contains no numeric samples.")
    return np.asarray(rows, dtype=float)[:, MMA8451Q_COLUMNS] * MMA8451Q_G_PER_LSB


def decimate_to_device_rate(samples: np.ndarray) -> np.ndarray:
    """Keep every DECIMATE_FACTOR-th sample so SisFall 200 Hz matches the ESP32 10 Hz stream."""
    return np.asarray(samples, dtype=float)[::DECIMATE_FACTOR]


def iter_windows(samples: np.ndarray) -> Iterable[tuple[int, np.ndarray]]:
    for start in range(0, len(samples) - WINDOW_SIZE + 1, WINDOW_STEP):
        yield start, samples[start : start + WINDOW_SIZE]


def validate_dataset(dataset: WindowDataset) -> None:
    if not len(dataset.features) or dataset.features.ndim != 2 or dataset.features.shape[1] != len(FEATURE_NAMES):
        raise DatasetError("No valid feature windows were assembled from the dataset.")
    if not np.isfinite(dataset.features).all():
        raise DatasetError("Feature matrix contains non-finite values.")
    if set(dataset.labels) != {0, 1}:
        raise DatasetError("The dataset must contain both ADL and fall windows.")
    if len(np.unique(dataset.groups)) < 2:
        raise DatasetError("Leave-One-Subject-Out validation needs at least two subjects.")


def _summary(source: str, recordings: int, labels: list[int], groups: list[int], skipped: list[dict]) -> dict:
    return {"source": source, "recordings_found": recordings, "windows": len(labels), "skipped_recordings": skipped, "class_window_counts": {"adl": int(sum(x == 0 for x in labels)), "fall": int(sum(x == 1 for x in labels))}, "subject_window_counts": {str(key): value for key, value in sorted(Counter(groups).items())}}


def build_dataset(data_dir: Path) -> WindowDataset:
    recordings = discover_recordings(data_dir)
    features, labels, groups, provenance, skipped = [], [], [], [], []
    for info in recordings:
        samples, windows = decimate_to_device_rate(parse_sisfall_recording(info)), 0
        for start, window in iter_windows(samples):
            features.append(extract_features(window)); labels.append(info.label); groups.append(info.subject)
            provenance.append({"recording": info.path.name, "activity": info.activity, "subject": info.subject, "label": info.label, "start_sample": start})
            windows += 1
        if not windows:
            skipped.append({"recording": info.path.name, "reason": f"too short for {WINDOW_SIZE}-sample window", "samples": len(samples)})
    dataset = WindowDataset(np.asarray(features, dtype=float), np.asarray(labels, dtype=int), np.asarray(groups, dtype=int), provenance, _summary("SisFall", len(recordings), labels, groups, skipped))
    validate_dataset(dataset)
    return dataset


def build_synthetic_dataset() -> WindowDataset:
    """Deterministic, explicitly opt-in data used only for tests/smoke runs."""
    rng = np.random.default_rng(42)
    features, labels, groups, provenance = [], [], [], []
    for subject in range(1, 5):
        for label in (0, 1):
            for trial in range(2):
                window = np.full((WINDOW_SIZE, 3), 1 / np.sqrt(3)) + rng.normal(0, .03, (WINDOW_SIZE, 3))
                if label:
                    window[8:13] = .08 + rng.normal(0, .01, (5, 3))
                    window[13:18] = 2.7 + rng.normal(0, .08, (5, 3))
                features.append(extract_features(window)); labels.append(label); groups.append(subject)
                provenance.append({"recording": f"synthetic_{subject}_{label}_{trial}", "activity": "F01" if label else "D01", "subject": subject, "label": label, "start_sample": 0})
    dataset = WindowDataset(np.asarray(features), np.asarray(labels), np.asarray(groups), provenance, _summary("synthetic (explicit smoke-test mode)", len(provenance), labels, groups, []))
    validate_dataset(dataset)
    return dataset


def evaluate_loso(dataset: WindowDataset, estimators: int) -> dict:
    true, predicted, scores = [], [], []
    for train, test in LeaveOneGroupOut().split(dataset.features, dataset.labels, dataset.groups):
        classifier = RandomForestClassifier(n_estimators=estimators, random_state=42, class_weight="balanced", n_jobs=-1).fit(dataset.features[train], dataset.labels[train])
        true.extend(dataset.labels[test]); predicted.extend(classifier.predict(dataset.features[test]))
        fall_column = int(np.where(classifier.classes_ == 1)[0][0]); scores.extend(classifier.predict_proba(dataset.features[test])[:, fall_column])
    matrix = confusion_matrix(true, predicted, labels=[0, 1]); tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    precision, recall, f1, _ = precision_recall_fscore_support(true, predicted, labels=[1], average=None, zero_division=0)
    try: auc = float(roc_auc_score(true, scores))
    except ValueError: auc = None
    return {"confusion_matrix": {"labels": ["ADL", "Fall"], "values": [[tn, fp], [fn, tp]]}, "counts": {"true_negative": tn, "false_positive": fp, "false_negative": fn, "true_positive": tp, "total": len(true)}, "metrics": {"accuracy": float(accuracy_score(true, predicted)), "fall_precision": float(precision[0]), "fall_recall_sensitivity": float(recall[0]), "fall_f1": float(f1[0]), "specificity": float(tn / (tn + fp)) if tn + fp else None, "roc_auc": auc}, "folds": int(len(np.unique(dataset.groups)))}


def model_metadata(source: str, estimators: int) -> dict:
    return {
        "format_version": 1,
        "dataset_source": source,
        "sample_rate_hz": FS,
        "sisfall_native_rate_hz": SISFALL_NATIVE_FS,
        "decimate_factor": DECIMATE_FACTOR,
        "cutoff_hz": CUTOFF_FREQ,
        "window_size_samples": WINDOW_SIZE,
        "window_step_samples": WINDOW_STEP,
        "feature_names": FEATURE_NAMES,
        "accelerometer": {"sensor": "SisFall MMA8451Q", "columns_zero_indexed": list(MMA8451Q_COLUMNS), "g_per_lsb": MMA8451Q_G_PER_LSB},
        "model": {"type": "RandomForestClassifier", "n_estimators": estimators, "random_state": 42, "class_weight": "balanced"},
    }


def write_artifacts(directory: Path, summary: dict, evaluation: dict, metadata: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    limitation = "SisFall uses performed falls and a waist-mounted sensor. These offline metrics do not establish accuracy for a wrist/pendant deployment or real-world unobserved falls."
    payload = {"dataset_summary": summary, "evaluation": evaluation, "configuration": metadata, "limitations": limitation}
    (directory / "evaluation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    m, c = evaluation["metrics"], evaluation["counts"]
    report = f"# SisFall Fall-Detection Evaluation\n\nThis run uses Leave-One-Subject-Out validation. {limitation}\n\n## Data summary\n\n- Source: {summary['source']}\n- Recordings found: {summary['recordings_found']}\n- Windows: {summary['windows']} (ADL: {summary['class_window_counts']['adl']}, Fall: {summary['class_window_counts']['fall']})\n- LOSO folds: {evaluation['folds']}\n\n## Confusion matrix\n\n| Actual / Predicted | ADL | Fall |\n| --- | ---: | ---: |\n| ADL | {c['true_negative']} | {c['false_positive']} |\n| Fall | {c['false_negative']} | {c['true_positive']} |\n\n## Metrics\n\n" + "\n".join(f"- {key}: {value if value is None else f'{value:.4f}'}" for key, value in m.items()) + "\n"
    (directory / "evaluation.md").write_text(report, encoding="utf-8")


def train_and_evaluate(data_dir: Path, model_output: Path, artifacts_dir: Path, estimators: int = 100, synthetic: bool = False) -> dict:
    dataset = build_synthetic_dataset() if synthetic else build_dataset(data_dir)
    metadata, evaluation = model_metadata(dataset.summary["source"], estimators), evaluate_loso(dataset, estimators)
    model = RandomForestClassifier(n_estimators=estimators, random_state=42, class_weight="balanced", n_jobs=-1).fit(dataset.features, dataset.labels)
    model_output.parent.mkdir(parents=True, exist_ok=True); joblib.dump({"model": model, "metadata": metadata}, model_output)
    write_artifacts(artifacts_dir, dataset.summary, evaluation, metadata)
    return {"dataset": dataset, "metadata": metadata, "evaluation": evaluation}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and validate a SisFall fall classifier.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR); parser.add_argument("--model-output", type=Path, default=DEFAULT_MODEL_OUTPUT)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR); parser.add_argument("--estimators", type=int, default=100)
    parser.add_argument("--synthetic", action="store_true", help="Use deterministic synthetic smoke-test data only; never use this for project results.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.estimators < 1: raise SystemExit("--estimators must be at least 1.")
    try: result = train_and_evaluate(args.data_dir, args.model_output, args.artifacts_dir, args.estimators, args.synthetic)
    except DatasetError as exc: raise SystemExit(f"Training aborted: {exc}") from exc
    print(f"Saved model: {args.model_output}\nSaved metrics: {args.artifacts_dir / 'evaluation.md'}\n{json.dumps(result['evaluation']['metrics'], indent=2)}")


if __name__ == "__main__": main()
