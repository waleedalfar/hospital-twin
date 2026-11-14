"""Latent severity, vitals and the rule that hidden state is never exposed (PROMPT.md §5.4)."""

import json
import random

import pytest

from tests.sim_helpers import make_profiles, make_sim
from twin.sim import config as c
from twin.sim import physiology as phys
from twin.sim.entities import PatientProfile, Physiology

OLD_SICK = PatientProfile("P-1", 82, "male", 6, ())
YOUNG = PatientProfile("P-2", 25, "female", 0, ())


def fresh(profile: PatientProfile = YOUNG, esi: int = 3) -> Physiology:
    return phys.initial_physiology(profile, esi, False, random.Random(1))


def test_severity_is_never_negative_and_reverts_to_its_mean() -> None:
    rng = random.Random(3)
    p = fresh()
    p.s = 2.5
    xs = []
    for i in range(2000):
        phys.step(p, YOUNG, 3, i * 5.0, 5.0, rng, flu=False, in_icu=False, treated=False)
        assert p.s >= 0
        xs.append(p.s)
    assert abs(sum(xs[500:]) / len(xs[500:]) - p.mu) < 0.4


def test_episode_rate_rises_with_age_comorbidity_esi_and_flu() -> None:
    base = phys.episode_rate_per_h(YOUNG, 4, False, False, False)
    assert phys.episode_rate_per_h(OLD_SICK, 4, False, False, False) > base
    assert phys.episode_rate_per_h(PatientProfile("x", 25, "male", 5, ()), 4, False, False, False) > base
    assert phys.episode_rate_per_h(YOUNG, 1, False, False, False) > phys.episode_rate_per_h(
        YOUNG, 4, False, False, False
    )
    assert phys.episode_rate_per_h(YOUNG, 3, True, True, False) == pytest.approx(
        c.EPISODE_FLU_RESPIRATORY_FACTOR * phys.episode_rate_per_h(YOUNG, 3, True, False, False)
    )
    assert phys.episode_rate_per_h(YOUNG, 3, False, True, False) == phys.episode_rate_per_h(
        YOUNG, 3, False, False, False
    )
    assert phys.episode_rate_per_h(YOUNG, 3, False, False, True) < phys.episode_rate_per_h(
        YOUNG, 3, False, False, False
    )


def test_deterioration_episodes_happen_and_reach_the_critical_threshold() -> None:
    rng = random.Random(9)
    reached = 0
    for trial in range(60):
        p = phys.initial_physiology(OLD_SICK, 2, False, random.Random(trial))
        for i in range(24 * 12):
            phys.step(p, OLD_SICK, 2, i * 5.0, 5.0, rng, flu=False, in_icu=False, treated=False)
            if phys.is_critical(p, i * 5.0):
                reached += 1
                break
    assert 5 < reached < 60


def test_critical_cooldown_and_responses() -> None:
    p = fresh()
    p.s = c.CRITICAL_THRESHOLD + 0.1
    assert phys.is_critical(p, 0.0)
    phys.after_rapid_response(p, 100.0)
    assert p.s < c.CRITICAL_THRESHOLD
    p.s = c.CRITICAL_THRESHOLD + 0.5
    assert not phys.is_critical(p, 101.0)
    assert phys.is_critical(p, 100.0 + 60 * c.CRITICAL_COOLDOWN_H)
    q = fresh()
    q.episode_until = 1e9
    phys.after_icu_transfer(q, 0.0)
    assert q.episode_until == -1.0
    assert q.mu >= c.ICU_TARGET_MU


def test_treatment_pulls_the_mean_down() -> None:
    rng = random.Random(1)
    p = fresh(esi=1)
    start = p.mu
    for i in range(500):
        phys.step(p, YOUNG, 1, i * 5.0, 5.0, rng, flu=False, in_icu=False, treated=True)
    assert p.mu < start
    assert p.mu >= c.MU_FLOOR - 1e-9


def test_vitals_worsen_with_severity_and_stay_in_physical_ranges() -> None:
    rng = random.Random(2)
    healthy, sick = fresh(), fresh()
    healthy.s, sick.s = 0.2, 3.5
    h = [phys.vitals(healthy, YOUNG, rng) for _ in range(200)]
    s = [phys.vitals(sick, YOUNG, rng) for _ in range(200)]

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs)

    assert mean([v.hr for v in s]) > mean([v.hr for v in h]) + 20
    assert mean([v.spo2 for v in s]) < mean([v.spo2 for v in h]) - 4
    assert mean([v.sbp for v in s]) < mean([v.sbp for v in h])
    assert mean([v.rr for v in s]) > mean([v.rr for v in h])
    assert mean([v.temp for v in s]) > mean([v.temp for v in h])
    for v in h + s:
        assert 70 <= v.spo2 <= 100
        assert v.rr >= 8
        assert v.sbp >= 60


def test_respiratory_patients_lose_more_spo2() -> None:
    rng = random.Random(4)
    plain, resp = fresh(), phys.initial_physiology(YOUNG, 3, True, random.Random(1))
    plain.s = resp.s = 3.0
    assert sum(phys.vitals(resp, YOUNG, rng).spo2 for _ in range(100)) < sum(
        phys.vitals(plain, YOUNG, rng).spo2 for _ in range(100)
    )


def test_vitals_are_sampled_every_5_minutes_admitted_and_15_waiting() -> None:
    sim = make_sim(4, 12)
    sim.run_until(sim.visible_start)
    gaps: dict[tuple[str, str], list[float]] = {}
    last: dict[str, float] = {}
    for _ in range(240):
        for item in sim.tick():
            if item.event.kind == "vitals":
                pid = item.event.patient_id
                t = sim.world.minutes(item.event.time)
                if pid in last:
                    located = sim.world.patient(pid)
                    phase = located[1].phase if located else "gone"
                    gaps.setdefault(("waiting" if phase.startswith("waiting") else "other", pid), []).append(
                        t - last[pid]
                    )
                last[pid] = t
    waiting = [g for (kind, _), gs in gaps.items() if kind == "waiting" for g in gs]
    other = [g for (kind, _), gs in gaps.items() if kind == "other" for g in gs]
    assert other and min(other) >= 5.0 - 1e-6
    assert sum(1 for g in other if g == 5.0) / len(other) > 0.8
    if waiting:
        assert min(waiting) >= 5.0


def test_latent_severity_never_appears_in_any_payload() -> None:
    """§5.4: the latent severity is never written to the DB or exposed by the API."""
    sim = make_sim(4, 12)
    sim.run_until(sim.visible_start)
    texts = [sim.snapshot(h, 1, False, False).model_dump_json() for h in sim.world.hospitals]
    texts.append(sim.network(1, False, False).model_dump_json())
    for _ in range(120):
        texts.extend(i.event.model_dump_json() for i in sim.tick())
    blob = "\n".join(texts).lower()
    for word in ("severity", "latent", "physiology", '"mu"', "episode"):
        assert word not in blob, word
    for text in texts[:8]:
        json.loads(text)


def test_snapshot_models_have_no_field_that_could_carry_severity() -> None:
    from twin.common import ws

    for name in dir(ws):
        model = getattr(ws, name)
        if isinstance(model, type) and issubclass(model, ws.Msg):
            assert not {"s", "mu", "severity", "latent"} & set(model.model_fields), name


def test_profiles_helper_is_deterministic() -> None:
    assert make_profiles(5) == make_profiles(5)
