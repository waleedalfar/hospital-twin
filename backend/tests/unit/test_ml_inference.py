"""Live inference inside the simulation (PROMPT.md §7.4)."""

from datetime import timedelta

import pytest

from tests.sim_helpers import make_profiles
from twin.common.ws import AlertEvent, RiskEvent
from twin.ml.dataset import build_dataset
from twin.ml.forecast import BED_UNITS, HORIZON_H, train_arrivals
from twin.ml.inference import FORECAST_EVERY_MIN, SCORE_EVERY_MIN, SCORING_LEAD_MIN, InferenceEngine
from twin.ml.model import HIGH, MEDIUM, DeteriorationModel
from twin.ml.train import train_deterioration
from twin.sim.engine import Simulation
from twin.sim.layout_model import load_layout


@pytest.fixture(scope="module")
def models() -> tuple[DeteriorationModel, object]:
    ds = build_dataset(make_profiles(), 5, days=14, surges=1)
    det = train_deterioration(ds.rows).model
    arrivals, _ = train_arrivals(ds.arrivals, ds.unit_stats)
    return det, arrivals


def make_sim(models: tuple[DeteriorationModel, object], warmup_h: float = 12.0, seed: int = 9) -> Simulation:
    sim = Simulation(load_layout(), make_profiles(), seed, timedelta(hours=warmup_h))
    sim.attach_ml(InferenceEngine(sim.world, models[0], models[1]))  # type: ignore[arg-type]
    return sim


def test_scores_every_five_minutes_with_valid_risk_events(models: tuple[DeteriorationModel, object]) -> None:
    sim = make_sim(models)
    sim.run_until(sim.visible_start)
    risk_times: set[float] = set()
    seen = 0
    for _ in range(120):
        for item in sim.tick():
            e = item.event
            if isinstance(e, RiskEvent):
                seen += 1
                risk_times.add(sim.world.minutes(e.time))
                assert 0.0 <= e.score <= 1.0
                assert e.level == ("high" if e.score >= HIGH else "medium" if e.score >= MEDIUM else "low")
                assert len(e.top_factors) == 3 and e.model_version == models[0].version
    assert seen > 100
    assert all(round(t) % SCORE_EVERY_MIN == 0 for t in risk_times)
    assert len(risk_times) == 120 // SCORE_EVERY_MIN


def test_every_scorable_patient_with_vitals_gets_a_score_and_it_shows_in_the_snapshot(
    models: tuple[DeteriorationModel, object],
) -> None:
    sim = make_sim(models)
    sim.run_until(sim.visible_start + timedelta(minutes=60))
    ml = sim.ml
    assert ml is not None
    sim.run_until(sim.world.time() + timedelta(minutes=(SCORE_EVERY_MIN - round(sim.world.now) % SCORE_EVERY_MIN) % SCORE_EVERY_MIN))
    for hospital_id in sim.world.hospitals:
        snap = sim.snapshot(hospital_id, 1, False, False)
        with_vitals = [e for e in snap.entities if e.kind == "patient" and e.vitals is not None]
        assert with_vitals
        for e in with_vitals:
            assert e.risk is not None and e.risk.model_version == ml.model.version
        assert snap.kpis.alerts == sum(1 for e in snap.entities if e.risk and e.risk.level == "high")
        assert ml.high_risk_count(hospital_id) == snap.kpis.alerts


def test_alerts_fire_once_when_a_patient_enters_high_risk(models: tuple[DeteriorationModel, object]) -> None:
    sim = make_sim(models, warmup_h=24)
    levels: dict[str, str] = {}
    alerts: dict[str, int] = {}
    entered_high: dict[str, int] = {}
    for _ in range(3 * 24 * 60):
        for item in sim.tick():
            e = item.event
            if isinstance(e, AlertEvent):
                alerts[e.patient_id] = alerts.get(e.patient_id, 0) + 1
                assert e.level == "high" and e.score >= HIGH
            if isinstance(e, RiskEvent):
                if e.level == "high" and levels.get(e.patient_id) != "high":
                    entered_high[e.patient_id] = entered_high.get(e.patient_id, 0) + 1
                levels[e.patient_id] = e.level
    assert alerts, "expected some high-risk alerts in three sim days"
    assert alerts == entered_high  # one alert per entry into high, never one per scoring batch


def test_forecasts_are_refreshed_every_15_minutes_for_each_hospital(
    models: tuple[DeteriorationModel, object],
) -> None:
    sim = make_sim(models)
    sim.run_until(sim.visible_start)
    sim.ml.drain_forecasts()  # type: ignore[union-attr]
    sim.run_until(sim.world.time() + timedelta(minutes=60))
    rows = sim.ml.drain_forecasts()  # type: ignore[union-attr]
    times = sorted({r.time for r in rows})
    assert len(times) == 60 // FORECAST_EVERY_MIN
    per = [r for r in rows if r.time == times[0] and r.hospital_id == "mercy"]
    assert [r.horizon_h for r in per if r.metric == "arrivals"] == list(range(1, HORIZON_H + 1))
    assert {r.metric for r in per if r.metric != "arrivals"} == {f"hours_until_full:{u}" for u in BED_UNITS}
    assert {r.hospital_id for r in rows} == {"mercy", "stlukes", "desert"}
    assert all(r.value >= 0 for r in rows)
    assert sim.ml.drain_forecasts() == []  # type: ignore[union-attr]


def test_scoring_starts_six_hours_before_the_visible_start(models: tuple[DeteriorationModel, object]) -> None:
    sim = make_sim(models, warmup_h=12)
    first = None
    while sim.world.time() < sim.visible_start:
        for item in sim.tick():
            if isinstance(item.event, RiskEvent) and first is None:
                first = item.event.time
    assert first is not None
    assert first >= sim.visible_start - timedelta(minutes=SCORING_LEAD_MIN)
    assert first <= sim.visible_start - timedelta(minutes=SCORING_LEAD_MIN - 60)


def test_hourly_arrivals_match_the_arrival_events(models: tuple[DeteriorationModel, object]) -> None:
    sim = make_sim(models)
    sim.run_until(sim.visible_start + timedelta(hours=5, minutes=20))
    ml = sim.ml
    assert ml is not None
    counts, last = ml.hourly_arrivals("mercy", 5)
    assert last == 4  # hours 0..4 are complete at 13:20; hour 0 starts at the visible start
    visible = sim.world.minutes(sim.visible_start)
    expected = [sum(1 for m, h, _ in ml.observer.arrivals if h == "mercy" and visible + 60 * k <= m < visible + 60 * (k + 1)) for k in range(5)]
    assert counts.tolist() == expected


def test_inference_does_not_change_the_simulation(models: tuple[DeteriorationModel, object]) -> None:
    """The models read the simulation but never steer it: with and without them, the same events happen."""

    def stream(with_ml: bool) -> list[str]:
        sim = Simulation(load_layout(), make_profiles(), 21, timedelta(hours=8))
        if with_ml:
            sim.attach_ml(InferenceEngine(sim.world, models[0], models[1]))  # type: ignore[arg-type]
        out: list[str] = []
        for _ in range(8 * 60 + 60):
            out.extend(i.event.model_dump_json() for i in sim.tick() if i.event.kind not in ("risk", "alert"))
        return out

    assert stream(True) == stream(False)


def test_no_models_means_no_scores() -> None:
    sim = Simulation(load_layout(), make_profiles(), 9, timedelta(hours=2))
    sim.run_until(sim.visible_start)
    assert sim.ml is None
    assert all(e.risk is None for e in sim.snapshot("mercy", 1, False, False).entities)
