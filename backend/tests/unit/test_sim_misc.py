"""Slot pools, vehicles, snapshots, patient journeys and staff behaviour."""

import collections
from datetime import timedelta

import pytest
import simpy

from tests.sim_helpers import make_sim
from twin.sim.entities import PatientProfile
from twin.sim.patients import lognormal, poisson
from twin.sim.pools import SlotPool
from twin.sim.vehicles import Vehicle, km, plan_route


def test_pool_gives_slots_in_priority_order() -> None:
    env = simpy.Environment()
    pool = SlotPool(env, ["a", "b"])
    first, second = pool.request(1), pool.request(1)
    late_urgent = pool.request(5)
    urgent = pool.request(0)
    assert first.value == "a" and second.value == "b"
    assert pool.queue_length == 2
    pool.release("a")
    assert urgent.value == "a"
    pool.release("b")
    assert late_urgent.value == "b"
    assert pool.free == []
    pool.release("a")
    assert pool.free == ["a"]
    with pytest.raises(ValueError, match="released twice"):
        pool.release("a")


def test_pool_try_take_and_cancel() -> None:
    env = simpy.Environment()
    pool = SlotPool(env, ["a", "b", "c"])
    assert pool.try_take("b") == "b"
    assert pool.try_take("b") is None
    assert pool.try_take() == "a"
    granted = pool.request(1)  # takes "c"
    assert granted.value == "c"
    waiting = pool.request(1)
    pool.cancel(waiting)
    assert pool.queue_length == 0
    pool.cancel(granted)  # a granted request gives its slot back
    assert pool.free == ["c"]
    assert pool.try_take() == "c"
    assert pool.try_take() is None


def test_poisson_and_lognormal_have_the_right_means() -> None:
    import random

    rng = random.Random(1)
    draws = [poisson(rng, 0.7) for _ in range(20000)]
    assert abs(sum(draws) / len(draws) - 0.7) < 0.03
    logs = sorted(lognormal(rng, 10.0) for _ in range(20001))
    assert abs(logs[10000] - 10.0) < 0.4


def test_vehicle_routes_follow_streets_and_position_interpolates() -> None:
    route = plan_route("ambulance", (33.40, -112.10), (33.45, -112.05), 10.0)
    assert len(route) == 3
    assert route[1][0] == 33.40 and route[1][1] == -112.05  # east-west first, then north-south
    assert route[0][2] == 10.0 < route[1][2] < route[2][2]
    v = Vehicle("A", "ambulance", "mercy", 33.40, -112.10, route=route)
    assert v.position(5.0) == (33.40, -112.10)
    assert v.position(route[2][2] + 5) == (33.45, -112.05)
    mid = v.position((route[0][2] + route[1][2]) / 2)
    assert 33.39 < mid[0] < 33.41 and -112.10 < mid[1] < -112.05
    assert Vehicle("B", "ambulance", "mercy", 1.0, 2.0).position(0) == (1.0, 2.0)
    assert km((33.4, -112.0), (33.4, -112.0)) == 0
    heli = plan_route("helicopter", (33.4, -112.1), (33.41, -112.1), 0.0)
    assert len(heli) == 2 and heli[1][2] >= 3.0


def test_snapshot_matches_world_state() -> None:
    sim = make_sim(6, 24)
    sim.run_until(sim.visible_start)
    for hospital_id, hospital in sim.world.hospitals.items():
        snap = sim.snapshot(hospital_id, 4, True, False)
        assert snap.speed == 4 and snap.paused and not snap.frozen
        assert {e.id for e in snap.entities} == set(hospital.people)
        assert {b.id: (b.patient_id, b.state) for b in snap.beds} == {
            b.id: (b.patient_id, b.state) for b in hospital.beds.values()
        }
        assert snap.kpis.census == sum(1 for b in snap.beds if b.state == "occupied")
        assert snap.kpis.capacity == 29
        for entity in snap.entities:
            if entity.kind == "patient" and entity.location.bed:
                assert entity.pose in ("lying", "walking")
            if entity.location.spot and entity.location.spot.startswith("W-") and entity.move is None:
                assert entity.pose == "seated"
        for e in snap.entities:
            assert e.risk is None
            assert (e.vitals is not None) == (e.kind == "patient" and e.vitals is not None)


def test_network_message_lists_hospitals_and_all_vehicles() -> None:
    sim = make_sim(6, 24)
    sim.run_until(sim.visible_start)
    net = sim.network(1, False, False)
    assert [h.id for h in net.hospitals] == ["mercy", "stlukes", "desert"]
    assert sum(1 for v in net.vehicles if v.kind == "ambulance") == 12
    assert sum(1 for v in net.vehicles if v.kind == "helicopter") == 1
    assert all(-113 < v.lon < -111 and 33 < v.lat < 34 for v in net.vehicles)


def test_all_patient_phases_and_dispositions_occur() -> None:
    sim = make_sim(8, 24)
    seen: collections.Counter[str] = collections.Counter()
    for _ in range(14 * 24 * 60):
        for item in sim.tick():
            seen[item.event.kind] += 1
    for kind in (
        "arrival",
        "triage",
        "er_admit",
        "admit",
        "surgery",
        "discharge",
        "transfer",
        "critical",
        "bed",
        "move",
    ):
        assert seen[kind] > 0, kind


def test_er_wait_is_arrival_to_er_bay() -> None:
    sim = make_sim(8, 24)
    arrivals: dict[str, float] = {}
    checked = 0
    for _ in range(2 * 24 * 60):
        for item in sim.tick():
            e = item.event
            t = sim.world.minutes(e.time)
            if e.kind == "arrival":
                arrivals[e.patient_id] = t
            if e.kind == "er_admit" and e.patient_id in arrivals:
                assert e.wait_min == pytest.approx(t - arrivals[e.patient_id], abs=0.11)
                checked += 1
    assert checked > 20


def test_moves_have_origin_destination_path_and_walking_duration() -> None:
    sim = make_sim(8, 12)
    layout = sim.world.layout
    seen = 0
    for _ in range(600):
        for item in sim.tick():
            e = item.event
            if e.kind != "move":
                continue
            seen += 1
            assert e.path and e.path[0] in layout.nodes and e.path[-1] in layout.nodes
            assert len(e.times) == len(e.path)
            assert e.depart == e.times[0] and e.arrive == e.times[-1]
            assert list(e.times) == sorted(e.times)
            for a, b, ta, tb in zip(e.path, e.path[1:], e.times, e.times[1:], strict=False):
                if layout.nodes[a].floor == layout.nodes[b].floor and a != b:
                    dist = (
                        (layout.nodes[a].x - layout.nodes[b].x) ** 2
                        + (layout.nodes[a].z - layout.nodes[b].z) ** 2
                    ) ** 0.5
                    assert (tb - ta).total_seconds() == pytest.approx(dist / 1.3, rel=0.02, abs=0.05)
    assert seen > 100


def test_elevator_rides_never_overlap_in_time() -> None:
    """Each building has one car. Walkers who ride together (a patient and their EMT) share one interval."""
    sim = make_sim(8, 24)
    rides: dict[str | None, set[tuple[float, float]]] = collections.defaultdict(set)
    for _ in range(24 * 60):
        for item in sim.tick():
            e = item.event
            if e.kind != "move":
                continue
            for a, b, ta, tb in zip(e.path, e.path[1:], e.times, e.times[1:], strict=False):
                if a.endswith("ELEV") and b.endswith("ELEV") and a != b:
                    rides[item.hospital_id].add((ta.timestamp(), tb.timestamp()))
    assert rides
    for hospital_rides in rides.values():
        ordered = sorted(hospital_rides)
        for (_, end), (start, _) in zip(ordered, ordered[1:], strict=False):
            assert start >= end - 1e-6


def test_staff_visit_beds_take_breaks_and_pray() -> None:
    sim = make_sim(8, 24)
    tasks: collections.Counter[str] = collections.Counter()
    for _ in range(2 * 24 * 60):
        sim.tick()
        for hospital in sim.world.hospitals.values():
            for s in hospital.staff():
                if s.task:
                    tasks[s.task] += 1
    for task in ("vitals", "meds", "rounds", "break", "prayer", "surgery"):
        assert tasks[task] > 0, task


def test_nurse_ratios_are_configured_per_spec() -> None:
    from twin.sim import config as c

    assert c.NURSE_RATIO == {"ICU": 2, "WARD": 5, "ER": 3, "REC": 2}
    assert pytest.approx(1.3 * 60) == c.WALK_SPEED_M_PER_MIN


def test_visitors_sit_in_the_waiting_room() -> None:
    sim = make_sim(8, 24)
    seen = 0
    for _ in range(3 * 24 * 60):
        sim.tick()
        for hospital in sim.world.hospitals.values():
            for p in hospital.people.values():
                if p.kind == "visitor" and p.move is None:
                    assert p.place.room == "WAITING"
                    seen += 1
    assert seen > 0


def test_ambulance_patients_are_wheeled_in_by_an_emt() -> None:
    sim = make_sim(8, 24)
    emt_moves = 0
    for _ in range(2 * 24 * 60):
        for item in sim.tick():
            if item.event.kind == "move" and item.event.entity_id.startswith("E-"):
                emt_moves += 1
    assert emt_moves > 0


def test_unused_profile_type() -> None:
    assert PatientProfile("P-1", 1, "male", 0, ()).id == "P-1"
    assert timedelta(minutes=1).total_seconds() == 60


def test_scenes_and_routes_stay_on_the_street_grid() -> None:
    """Ambulances drive east-west first, then north-south, along streets through the hospitals."""
    from twin.sim.vehicles import road_lines, scene_crossings, snap_to_roads

    sim = make_sim(8, 24)
    world = sim.world
    lats, lons = road_lines(world)
    assert len(lats) == 3 and len(lons) == 3
    assert len(scene_crossings(world)) == 6  # 9 crossings, 3 are hospitals
    assert snap_to_roads(world, 33.46, -112.08) == (lats[1], lons[1])
    for _ in range(2 * 24 * 60):
        sim.tick()
        for v in world.vehicles.values():
            if v.kind == "ambulance" and v.route:
                for lat, lon, _t in v.route:
                    assert lat in lats and lon in lons
