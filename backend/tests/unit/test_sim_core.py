"""Determinism, invariants, clock and conservation (PROMPT.md §5.1, §5.8)."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.sim_helpers import digest, make_profiles, make_sim
from twin.sim import config as c
from twin.sim.engine import Simulation
from twin.sim.invariants import InvariantError, check, find_problems
from twin.sim.layout_model import load_layout
from twin.sim.world import World


def test_sim_starts_at_08_00_phoenix_time() -> None:
    assert datetime(2026, 11, 14, 15, 0, tzinfo=UTC) == c.SIM_START
    sim = make_sim(warmup_h=2)
    assert sim.visible_start == c.SIM_START
    assert sim.now == c.SIM_START - timedelta(hours=2)
    sim.tick()
    assert sim.now == c.SIM_START - timedelta(hours=2) + timedelta(minutes=1)  # one tick = one sim minute


def test_same_seed_gives_identical_event_stream() -> None:
    assert digest(make_sim(7, 6), 600) == digest(make_sim(7, 6), 600)


def test_different_seed_gives_a_different_stream() -> None:
    assert digest(make_sim(7, 6), 600) != digest(make_sim(8, 6), 600)


def test_same_seed_and_same_actions_give_identical_streams() -> None:
    def run() -> str:
        sim = make_sim(11, 12)
        sim.tick()
        sim.start_scenario("flu_surge", "mercy")
        for _ in range(60):
            sim.tick()
        sim.apply_action("divert_ambulances", {"hospital_id": "mercy", "duration_min": 90})
        sim.apply_action("call_in_staff", {"hospital_id": "stlukes", "unit": "ICU", "count": 1})
        return digest(sim, 300)

    assert run() == run()


def test_actions_change_the_stream() -> None:
    plain = make_sim(11, 12)
    acted = make_sim(11, 12)
    acted.apply_action("call_in_staff", {"hospital_id": "mercy", "unit": "ICU", "count": 2})
    assert digest(plain, 120) != digest(acted, 120)


def test_invariants_hold_every_tick_for_three_sim_days_with_scenarios() -> None:
    sim = make_sim(5, 12, debug=True)  # debug=True checks every tick and raises on a violation
    for minute in range(3 * 24 * 60):
        if minute == 600:
            sim.start_scenario("flu_surge", "mercy")
        if minute == 1500:
            sim.start_scenario("mass_casualty", None, 33.45, -112.07)
        if minute == 2400:
            sim.start_scenario("hospital_offline", "stlukes")
        if minute == 3000:
            sim.start_scenario("staff_shortage", "desert")
        sim.tick()


def test_conservation_of_patients_per_hospital() -> None:
    sim = make_sim(3, 24)
    sim.run_until(sim.visible_start)
    for hospital in sim.world.hospitals.values():
        k = hospital.counters
        assert k.arrived == len(hospital.patients()) + k.discharged + k.transferred_out
    assert sum(h.counters.arrived for h in sim.world.hospitals.values()) > 50


def test_bed_counts_never_exceed_capacity_and_beds_are_unique() -> None:
    sim = make_sim(3, 24)
    layout = load_layout()
    for _ in range(24 * 60):
        sim.tick()
        for hospital in sim.world.hospitals.values():
            for unit in ("ER", "WARD", "REC", "ICU"):
                occupied = [b for b in hospital.beds.values() if b.unit == unit and b.state == "occupied"]
                assert len(occupied) <= layout.capacity[unit]
            beds = [p.place.bed for p in hospital.patients() if p.place.bed]
            assert len(beds) == len(set(beds))


def test_every_present_patient_has_exactly_one_location_and_no_entity_is_in_two_places() -> None:
    sim = make_sim(3, 24)
    for _ in range(24 * 60):
        sim.tick()
        seen: set[str] = set()
        for hospital in sim.world.hospitals.values():
            for person in hospital.people.values():
                assert person.id not in seen
                seen.add(person.id)
                held = [x for x in (person.place.bed, person.place.spot, person.place.vehicle) if x is not None]
                assert len(held) == 1


def test_staff_are_always_at_valid_layout_spots() -> None:
    sim = make_sim(3, 12)
    layout = sim.world.layout
    valid = set(layout.spots_by_id) | set(layout.seats_by_id)
    for _ in range(12 * 60):
        sim.tick()
        for hospital in sim.world.hospitals.values():
            for staff in hospital.staff():
                assert staff.place.spot in valid or staff.place.vehicle is not None


def test_invariant_checker_detects_violations() -> None:
    sim = make_sim(3, 12)
    sim.run_until(sim.visible_start)
    world: World = sim.world
    hospital = world.hospitals["mercy"]
    assert find_problems(world) == []
    hospital.counters.arrived += 1  # break conservation
    with pytest.raises(InvariantError, match="conservation"):
        check(world)
    hospital.counters.arrived -= 1
    nurse = hospital.staff()[0]
    nurse.place = type(nurse.place)(floor=0, room="ER", bed="ER-1")  # staff in a bed
    assert any("holds bed" in p or "not a patient" in p for p in find_problems(world))


def test_empty_patient_pool_is_rejected() -> None:
    with pytest.raises(ValueError, match="make seed"):
        Simulation(load_layout(), [], 1)


def test_pool_has_enough_patients() -> None:
    assert len(make_profiles()) == 600
