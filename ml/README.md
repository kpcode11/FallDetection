# ML training and inference

`train.py` trains a Random Forest on real SisFall recordings with
Leave-One-Subject-Out (LOSO) validation. It selects the raw SisFall MMA8451Q
accelerometer columns 6–8 (zero-indexed) and converts them at `1/1024 g` per
LSB. SisFall's native 200 Hz stream is decimated by 20 to match the ESP32's
10 Hz stream. The deployed feature contract is seven acceleration features
over exactly 30 samples (three seconds), with a 15-sample training overlap.

## Dataset setup

Download the original SisFall archive or an unchanged mirror, then extract it
under `SisFall_dataset/` in the repository. Nested paths are fine: recording
files are discovered recursively. The expected names include
`D01_SA01_R01.txt` and `F01_SA01_R01.txt`.

The dataset is gitignored. Original SisFall rows are comma-delimited with a
trailing semicolon; the parser also accepts semicolon-delimited repackagings.
`D*` recordings are ADLs and `F*` recordings are falls.

## Train and evaluate

From the repository root in the WSL virtual environment:

```bash
python -m unittest discover -s ml/tests -v
python ml/train.py --data-dir SisFall_dataset
```

Training writes a metadata-wrapped model to `ml/fall_detection_model.joblib`
and ignored review artifacts:

- `ml/artifacts/evaluation.json` — configuration, data counts, confusion matrix, and metrics
- `ml/artifacts/evaluation.md` — concise results report

Use alternate locations when needed:

```bash
python ml/train.py --data-dir /path/to/SisFall --model-output ml/fall_detection_model.joblib --artifacts-dir ml/artifacts
```

`--synthetic` is deterministic smoke-test mode only. Never use its outputs for
project accuracy claims.

## Run the service

After real-data training, start the MQTT service from `ml/`:

```bash
python server.py
```

New models include the feature schema and 10 Hz / 30-sample contract; legacy
bare sklearn models can still load. MQTT payloads must contain exactly 30
numeric `[ax, ay, az]` samples. Invalid payloads are rejected without
publishing alerts. MQTT topics and the `ML_CONFIRMED_FALL` event are unchanged.

## Report limit

SisFall uses a waist-mounted device and performed falls. Its offline LOSO
metrics do not establish wrist/pendant or real-world fall accuracy. The model
and service should run in WSL on this machine because Windows Application
Control blocks scikit-learn native extensions in the host Python installation.
