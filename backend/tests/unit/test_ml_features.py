"""Features and NEWS2 for the deterioration model (PROMPT.md §7.2)."""

import math

import pytest

from twin.ml.features import FEATURE_NAMES, FEATURES, READABLE, Reading, Static, build_features, news2

STATIC = Static(age=70, male=True, comorbidities=3, unit="ICU", hours_since_admission=5.0, esi=2)


def reading(
    t: float,
    hr: float = 80,
    spo2: float = 97,
    sbp: float = 120,
    dbp: float = 75,
    temp: float = 37.0,
    rr: float = 16,
) -> Reading:
    return Reading(t, hr, spo2, sbp, dbp, temp, rr)


@pytest.mark.parametrize(
    ("r", "expected"),
    [
        (reading(0), 0),
        (reading(0, rr=8), 3),
        (reading(0, rr=10), 1),
        (reading(0, rr=22), 2),
        (reading(0, rr=26), 3),
        (reading(0, spo2=91), 3),
        (reading(0, spo2=93), 2),
        (reading(0, spo2=95), 1),
        (reading(0, sbp=90), 3),
        (reading(0, sbp=100), 2),
        (reading(0, sbp=110), 1),
        (reading(0, sbp=230), 3),
        (reading(0, hr=40), 3),
        (reading(0, hr=50), 1),
        (reading(0, hr=100), 1),
        (reading(0, hr=120), 2),
        (reading(0, hr=140), 3),
        (reading(0, temp=35.0), 3),
        (reading(0, temp=35.5), 1),
        (reading(0, temp=38.5), 1),
        (reading(0, temp=39.5), 2),
        (reading(0, hr=140, spo2=88, sbp=85, rr=28, temp=39.5), 3 + 3 + 3 + 3 + 2),
    ],
)
def test_news2_follows_the_royal_college_table(r: Reading, expected: int) -> None:
    assert news2(r) == expected


def test_feature_schema_is_stable_and_every_feature_has_a_readable_name() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)) == len(FEATURES) == 29
    assert set(READABLE) == set(FEATURE_NAMES)
    for required in (
        "hr",
        "spo2",
        "news2",
        "age",
        "unit",
        "esi",
        "hours_since_admission",
        "spo2_d1h",
        "hr_d2h",
        "spo2_min_2h",
        "rr_max_2h",
    ):
        assert required in FEATURE_NAMES
    assert not any("sever" in n or "latent" in n for n in FEATURE_NAMES)


def test_features_from_a_history() -> None:
    history = [
        reading(0, hr=70, spo2=98),
        reading(60, hr=80, spo2=96),
        reading(120, hr=95, spo2=92),
        reading(150, hr=100, spo2=90),
    ]
    f = build_features(history, STATIC, 150)
    assert f is not None
    assert (f["hr"], f["spo2"]) == (100, 90)
    assert f["hr_d1h"] == 100 - 80  # the reading at or before minute 90 is the one at 60
    assert f["hr_d2h"] == 100 - 70  # the reading at or before minute 30 is the one at 0
    assert f["spo2_min_2h"] == 90 and f["spo2_max_2h"] == 96  # window: minutes 30..150
    assert f["hr_max_2h"] == 100 and f["hr_min_2h"] == 80
    assert (f["age"], f["sex_male"], f["comorbidities"], f["esi"], f["hours_since_admission"]) == (
        70,
        1.0,
        3,
        2,
        5.0,
    )
    assert f["news2"] == news2(history[-1])
    assert list(f) == list(FEATURE_NAMES)


def test_missing_history_gives_nan_deltas_and_no_charts_gives_none() -> None:
    f = build_features([reading(100)], STATIC, 100)
    assert f is not None and math.isnan(f["hr_d1h"]) and math.isnan(f["hr_d2h"])
    assert build_features([], STATIC, 100) is None
    assert build_features([reading(500)], STATIC, 100) is None


def test_unknown_units_get_their_own_code() -> None:
    odd = Static(age=1, male=False, comorbidities=0, unit="MARS", hours_since_admission=0, esi=3)
    f = build_features([reading(0)], odd, 0)
    assert f is not None and f["unit"] == 6.0 and f["sex_male"] == 0.0


def test_no_future_information_leaks_into_features() -> None:
    """§7.2: features built at time t use no data after t. Adding readings after t changes nothing."""
    past = [reading(0, hr=70), reading(30, hr=75), reading(60, hr=80), reading(90, hr=85)]
    future = [reading(95, hr=200, spo2=60, rr=40), reading(120, hr=210), reading(400, hr=220)]
    for now in (90.0, 92.0):
        assert build_features(past + future, STATIC, now) == build_features(past, STATIC, now)
    assert build_features(past + future, STATIC, 90) != build_features(past + future, STATIC, 400)
