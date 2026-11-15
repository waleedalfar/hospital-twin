"""Scenarios (PROMPT.md §5.6) and actions (§5.7)."""

import collections
from datetime import timedelta

import pytest

from tests.sim_helpers import make_sim
from twin.common.ws import ActionName
from twin.sim.actions import ActionError
from twin.sim.engine import Simulation
from twin.sim.scenarios import ScenarioError


def warm(seed: int = 5) -> Simulation:
    sim = make_sim(seed, 24)
    sim.run_until(sim.visible_start)
    return sim


def status_of(sim: Simulation, hospital_id: str) -> str:
    return str(sim.world.hospitals[hospital_id].status)


def count(sim: Simulation, minutes: int, kind: str, hospital: str | None = None) -> collections.Counter[str]:
    out: collections.Counter[str] = collections.Counter()
    for _ in range(minutes):
        for item in sim.tick():
            if item.event.kind == kind and (hospital is None or item.hospital_id == hospital):
                out[getattr(item.event, "complaint", getattr(item.event, "mode", "x"))] += 1
    return out


def arrivals(sim: Simulation, minutes: int, hospital: str) -> int:
    return sum(count(sim, minutes, "arrival", hospital).values())


def test_flu_surge_raises_arrivals_waiting_and_respiratory_share() -> None:
    base = sum(arrivals(warm(s), 180, "mercy") for s in range(1, 5))
    flu_total, resp = 0, 0
    for s in range(1, 5):
        sim = warm(s)
        sim.start_scenario("flu_surge", "mercy")
        counts = count(sim, 180, "arrival", "mercy")
        flu_total += sum(counts.values())
        resp += counts["respiratory"]
    assert flu_total > 1.8 * base
    assert resp / flu_total > 0.4


def test_flu_surge_raises_waiting_count_and_er_wait() -> None:
    worst_waiting, worst_wait = 0, 0.0
    for s in range(1, 5):
        sim = warm(s)
        sim.start_scenario("flu_surge", "mercy")
        for _ in range(240):
            sim.tick()
            k = sim.snapshot("mercy", 1, False, False).kpis
            worst_waiting, worst_wait = max(worst_waiting, k.waiting), max(worst_wait, k.er_wait_min)
    assert worst_waiting >= 2
    assert worst_wait > 15


def test_flu_surge_ends_after_three_sim_hours_and_can_be_stopped() -> None:
    sim = warm()
    s = sim.start_scenario("flu_surge", "mercy")
    sim.run_until(sim.now + timedelta(minutes=181))
    assert not s.active
    stopped = sim.start_scenario("flu_surge", "mercy")
    sim.tick()
    sim.stop_scenario(stopped.id)
    assert not stopped.active


def test_mass_casualty_sends_twelve_trauma_arrivals_to_the_nearest_hospital_and_a_helicopter() -> None:
    sim = warm()
    s = sim.start_scenario("mass_casualty", None, 33.4484, -112.0740)  # at Mercy
    assert s.hospital_id == "mercy"
    modes: collections.Counter[str] = collections.Counter()
    complaints: collections.Counter[str] = collections.Counter()
    for _ in range(180):
        for item in sim.tick():
            if item.event.kind == "arrival" and item.hospital_id == "mercy":
                modes[item.event.mode] += 1
                complaints[item.event.complaint] += 1
    assert modes["air"] == 1
    assert complaints["trauma"] >= 12
    far = warm().start_scenario("mass_casualty", None, 33.51, -112.03)
    assert far.hospital_id == "stlukes"


def test_helicopter_animates_from_the_mercy_roof() -> None:
    sim = warm()
    sim.start_scenario("mass_casualty", None, 33.46, -112.08)
    statuses: set[str] = set()
    for _ in range(90):
        sim.tick()
        statuses.add(sim.world.vehicles["HELI-mercy"].status)
    assert {"to_scene", "on_scene", "to_hospital", "at_base"} <= statuses


def test_staff_shortage_removes_thirty_percent_of_nurses_for_four_hours() -> None:
    sim = warm()
    mercy = sim.world.hospitals["mercy"]
    before = sum(1 for s in mercy.staff() if s.kind == "nurse")
    s = sim.start_scenario("staff_shortage", "mercy")
    sim.run_until(sim.now + timedelta(minutes=15))
    during = sum(1 for x in mercy.staff() if x.kind == "nurse")
    assert during == before - round(before * 0.3)
    sim.run_until(sim.now + timedelta(minutes=240))
    assert not s.active
    sim.run_until(sim.now + timedelta(minutes=15))
    assert sum(1 for x in mercy.staff() if x.kind == "nurse") == before


def test_hospital_offline_reroutes_ambulances_and_stop_reopens() -> None:
    sim = warm()
    s = sim.start_scenario("hospital_offline", "mercy")
    destinations: set[str | None] = set()
    for _ in range(360):
        sim.tick()
        destinations |= {v.destination for v in sim.world.vehicles.values() if v.status == "to_hospital"}
        assert sim.world.hospitals["mercy"].status == "offline"
    assert "mercy" not in destinations
    assert destinations & {"stlukes", "desert"}
    sim.stop_scenario(s.id)
    assert sim.world.hospitals["mercy"].status == "open"


def test_ambulance_en_route_is_redirected_when_its_hospital_goes_offline() -> None:
    sim = warm(2)
    for _ in range(2000):
        sim.tick()
        heading = [v for v in sim.world.vehicles.values() if v.status == "to_hospital" and v.patient]
        if heading:
            target = heading[0].destination
            assert target is not None
            sim.start_scenario("hospital_offline", target)
            sim.tick()
            assert heading[0].destination != target or heading[0].status != "to_hospital"
            return
    pytest.fail("no ambulance carried a patient in 2000 minutes")


def test_scenarios_write_events_and_show_in_the_snapshot() -> None:
    sim = warm()
    s = sim.start_scenario("flu_surge", "stlukes")
    kinds = [(i.event.kind, getattr(i.event, "status", None)) for i in sim.world.drain()]
    assert ("scenario", "started") in kinds
    assert [x.id for x in sim.snapshot("stlukes", 1, False, False).scenarios] == [s.id]
    assert sim.snapshot("mercy", 1, False, False).scenarios == []
    sim.stop_scenario(s.id)
    assert ("scenario", "stopped") in [(i.event.kind, getattr(i.event, "status", None)) for i in sim.world.drain()]
    assert sim.snapshot("stlukes", 1, False, False).scenarios == []


def test_scenario_request_errors() -> None:
    sim = warm()
    with pytest.raises(ScenarioError, match="Unknown hospital"):
        sim.start_scenario("flu_surge", "nowhere")
    with pytest.raises(ScenarioError, match="needs a hospital_id"):
        sim.start_scenario("staff_shortage", None)
    with pytest.raises(ScenarioError, match="needs the incident location"):
        sim.start_scenario("mass_casualty", None)
    with pytest.raises(ScenarioError, match="Unknown scenario"):
        sim.stop_scenario("SC-99")
    s = sim.start_scenario("hospital_offline", "desert")
    sim.stop_scenario(s.id)
    with pytest.raises(ScenarioError, match="not running"):
        sim.stop_scenario(s.id)


# ---- actions -------------------------------------------------------------------------------------------


def test_divert_ambulances_sets_status_then_expires() -> None:
    sim = warm()
    sim.apply_action("divert_ambulances", {"hospital_id": "mercy", "duration_min": 30})
    assert status_of(sim, "mercy") == "diverting"
    destinations: set[str | None] = set()
    for _ in range(29):
        sim.tick()
        destinations |= {v.destination for v in sim.world.vehicles.values() if v.status == "to_hospital"}
    assert "mercy" not in destinations
    sim.run_until(sim.now + timedelta(minutes=3))
    assert status_of(sim, "mercy") == "open"


def test_expedite_discharge_discharges_a_ward_patient_soon() -> None:
    sim = warm()
    mercy = sim.world.hospitals["mercy"]
    patient = next(p for p in mercy.patients() if p.phase == "inpatient" and p.unit == "WARD")
    sim.apply_action("expedite_discharge", {"patient_ids": [patient.id], "hospital_id": "mercy"})
    sim.run_until(sim.now + timedelta(minutes=30))
    assert patient.id not in mercy.people
    assert patient.expedited


def test_move_patient_moves_to_a_free_bed() -> None:
    sim = warm()
    mercy = sim.world.hospitals["mercy"]
    patient = next(p for p in mercy.patients() if p.phase == "inpatient" and p.unit == "WARD")
    old = patient.place.bed
    target = next(b.id for b in mercy.beds.values() if b.unit == "WARD" and b.state == "open")
    sim.apply_action("move_patient", {"patient_id": patient.id, "bed_id": target, "hospital_id": "mercy"})
    sim.run_until(sim.now + timedelta(minutes=10))
    assert patient.place.bed == target
    assert mercy.beds[target].patient_id == patient.id
    assert mercy.beds[old or ""].state in ("cleaning", "open")


def test_call_in_staff_adds_nurses_who_walk_in() -> None:
    sim = warm()
    mercy = sim.world.hospitals["mercy"]
    before = sum(1 for s in mercy.staff() if s.unit == "ICU" and s.kind == "nurse")
    sim.apply_action("call_in_staff", {"hospital_id": "mercy", "unit": "ICU", "count": 3})
    assert sum(1 for s in mercy.staff() if s.unit == "ICU" and s.kind == "nurse") == before + 3
    sim.tick()
    assert any(s.move is not None for s in mercy.staff() if s.unit == "ICU")


def test_hold_bed_blocks_then_releases() -> None:
    sim = warm()
    mercy = sim.world.hospitals["mercy"]
    bed = next(b.id for b in mercy.beds.values() if b.unit == "ICU" and b.state == "open")
    sim.apply_action("hold_bed", {"hospital_id": "mercy", "bed_id": bed, "minutes": 20})
    assert mercy.beds[bed].state == "blocked"
    for _ in range(19):
        sim.tick()
        assert mercy.beds[bed].state == "blocked"
    sim.run_until(sim.now + timedelta(minutes=2))
    assert mercy.beds[bed].state == "open"


def test_actions_emit_events() -> None:
    sim = warm()
    sim.world.drain()
    sim.apply_action("call_in_staff", {"hospital_id": "desert", "unit": "WARD", "count": 1})
    assert "action" in [i.event.kind for i in sim.world.drain()]


@pytest.mark.parametrize(
    ("action", "params", "message"),
    [
        ("divert_ambulances", {"hospital_id": "nope", "duration_min": 10}, "Unknown hospital"),
        ("divert_ambulances", {"hospital_id": "mercy", "duration_min": 0}, "duration_min"),
        ("divert_ambulances", {"hospital_id": "mercy", "duration_min": "x"}, "must be a number"),
        ("divert_ambulances", {"duration_min": 10}, "must be a string"),
        ("expedite_discharge", {"patient_ids": []}, "No patients"),
        ("expedite_discharge", {"patient_ids": ["P-9999"]}, "not in any hospital"),
        ("expedite_discharge", {"patient_ids": "P-0001"}, "must be a list"),
        ("move_patient", {"patient_id": "P-9999", "bed_id": "ICU-1"}, "not in any hospital"),
        ("call_in_staff", {"hospital_id": "mercy", "unit": "OR", "count": 1}, "Unit must be"),
        ("call_in_staff", {"hospital_id": "mercy", "unit": "ICU", "count": 99}, "count must be"),
        ("hold_bed", {"hospital_id": "mercy", "bed_id": "NOPE-1", "minutes": 10}, "Unknown bed"),
        ("hold_bed", {"hospital_id": "mercy", "bed_id": "ICU-1", "minutes": 99999}, "minutes must be"),
    ],
)
def test_invalid_actions_are_rejected_and_change_nothing(action: ActionName, params: dict[str, str | float | int | list[str]], message: str) -> None:
    sim = warm()
    sim.world.drain()
    with pytest.raises(ActionError, match=message):
        sim.apply_action(action, params)
    assert sim.world.drain() == []


def test_diverting_an_offline_hospital_and_moving_to_a_taken_bed_are_rejected() -> None:
    sim = warm()
    sim.start_scenario("hospital_offline", "desert")
    with pytest.raises(ActionError, match="offline"):
        sim.apply_action("divert_ambulances", {"hospital_id": "desert", "duration_min": 10})
    mercy = sim.world.hospitals["mercy"]
    patient = next(p for p in mercy.patients() if p.phase == "inpatient" and p.unit == "WARD")
    taken = next(b.id for b in mercy.beds.values() if b.state == "occupied" and b.id != patient.place.bed)
    with pytest.raises(ActionError, match="not free"):
        sim.apply_action("move_patient", {"patient_id": patient.id, "bed_id": taken})
    with pytest.raises(ActionError, match="already in"):
        sim.apply_action("move_patient", {"patient_id": patient.id, "bed_id": str(patient.place.bed)})
    icu_patient = next(p for p in mercy.patients() if p.unit == "ICU")
    with pytest.raises(ActionError, match="not a ward"):
        sim.apply_action("expedite_discharge", {"patient_ids": [icu_patient.id]})
