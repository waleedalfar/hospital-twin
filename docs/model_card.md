# Model card: Hospital Twin deterioration and arrivals models

Generated 2026-11-14 by `make train`. All data is simulated; no real patient data was used.

## Deterioration model (`lgbm-v1`)

**Task.** For every patient who is waiting or admitted, every 30 sim minutes: the probability of a
critical event (escalation to ICU or rapid response) within the next 6 sim hours.

**Data.** The simulation run headless with seed 20261114 for 30 sim days across three hospitals: 120,231 patient-snapshots,
2,804 positive. Patients are drawn from Synthea records (Phoenix, Arizona) for age, sex and
comorbidities. Vitals, deterioration and critical events come from the simulator's hidden severity process,
which the model never sees. Flu surges cover about 1% of the time.

**Split.** By time: first 60% train, next 20% validation (early stopping and calibration), last 20% test.
Rows: train 84,781, validation 20,414, test 15,036.

**Model.** LightGBM gradient-boosted trees, isotonic calibration, SHAP TreeExplainer for the top three
factors of each prediction. Levels: high at 0.70 or more, medium at 0.45 or more, otherwise low.

### Features

| Feature | Meaning |
| --- | --- |
| `hr` | Heart rate |
| `spo2` | SpO2 |
| `sbp` | Systolic BP |
| `dbp` | Diastolic BP |
| `temp` | Temperature |
| `rr` | Resp. rate |
| `hr_d1h` | HR change, 1h |
| `spo2_d1h` | SpO2 change, 1h |
| `sbp_d1h` | BP change, 1h |
| `rr_d1h` | Resp. rate change, 1h |
| `temp_d1h` | Temp. change, 1h |
| `hr_d2h` | HR change, 2h |
| `spo2_d2h` | SpO2 change, 2h |
| `sbp_d2h` | BP change, 2h |
| `rr_d2h` | Resp. rate change, 2h |
| `temp_d2h` | Temp. change, 2h |
| `spo2_min_2h` | Lowest SpO2, 2h |
| `spo2_max_2h` | Highest SpO2, 2h |
| `hr_min_2h` | Lowest HR, 2h |
| `hr_max_2h` | Highest HR, 2h |
| `rr_min_2h` | Lowest resp. rate, 2h |
| `rr_max_2h` | Highest resp. rate, 2h |
| `news2` | NEWS2 score |
| `age` | Age |
| `sex_male` | Male sex |
| `comorbidities` | Comorbidities |
| `unit` | Care unit |
| `hours_since_admission` | Hours in hospital |
| `esi` | Triage level (ESI) |

No latent severity and no future information is used; a test builds features at time t from a history with
future readings added and checks nothing changes.

### Metrics against NEWS2 alone

NEWS2 (calibrated the same way) is the baseline.

| Split | AUROC model | AUROC NEWS2 | AUPRC model | AUPRC NEWS2 | Brier model | Brier NEWS2 |
| --- | --- | --- | --- | --- | --- | --- |
| validation | 0.938 | 0.835 | 0.371 | 0.129 | 0.0192 | 0.0235 |
| test | 0.909 | 0.773 | 0.351 | 0.095 | 0.0225 | 0.0276 |

Positive rate on the test split: 0.030. The calibration curve is in `models/lgbm-v1/metrics.json`.

### Fairness on the test split

| Group | Rows | Positives | AUROC | Calibration gap |
| --- | --- | --- | --- | --- |
| age 18-39 | 2920 | 0 | n/a | +0.0108 |
| age 40-64 | 4221 | 90 | 0.927 | -0.0013 |
| age 65+ | 7895 | 355 | 0.881 | +0.0012 |
| male | 7499 | 196 | 0.908 | +0.0063 |
| female | 7537 | 249 | 0.910 | -0.0016 |

Largest AUROC gap between groups: 0.046 (gaps above 0.05 are flagged in the governance panel).

## Arrivals forecast (`arrivals-lgbm-v1`)

LightGBM regression on hourly arrivals per hospital for the next 6 hours, from hour of day, day of week, the
last 24 hourly counts, rolling means and an active-scenario flag.

| | MAE (arrivals per hour) |
| --- | --- |
| Model | 0.785 |
| Seasonal naive (same hour yesterday) | 1.036 |

The model is 24% more accurate than the baseline on 3,744 validation rows.

## Limits

- Everything is learned from a simulator. The labels follow the simulator's own deterioration rules, so the
  scores say how well the pipeline works, not how well it would work on real patients.
- The simulation has no weekday effect, so the day-of-week feature carries no signal.
- Consciousness and supplemental oxygen are not simulated; NEWS2 assumes alert and room air.
- Critical events are rare (about 2% of snapshots); the 0.70 high-risk threshold is rarely reached, which is
  intended for a demo where alerts should be meaningful.
- Not for clinical use.
