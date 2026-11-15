"""Walk-in arrivals (§5.3): a non-homogeneous Poisson process by hour of day, per hospital."""

from twin.sim import config as c
from twin.sim.entities import Patient, Place
from twin.sim.hospital import HospitalState
from twin.sim.patients import (
    create_patient,
    draw_complaint,
    draw_esi,
    draw_profile,
    journey,
    poisson,
    waiting_place,
)
from twin.sim.world import SimGen, World


def walk_ins(world: World, hospital: HospitalState) -> SimGen:
    from twin.sim.scenarios import demand_multiplier, flu_active

    rng = world.rng("walk-ins", hospital.id)
    while True:
        base = c.PROFILES[hospital.id].walk_in_per_h * c.HOURLY_PATTERN[world.local_hour()]
        multiplier = demand_multiplier(world, hospital.id)
        for k in range(poisson(rng, base * multiplier / 60.0)):
            # During a flu surge most of the extra arrivals are respiratory cases.
            extra_share = (multiplier - 1.0) / multiplier if flu_active(world, hospital.id) else 0.0
            respiratory = c.FLU_RESPIRATORY_SHARE if rng.random() < extra_share else None
            walk_in(world, hospital, rng, respiratory, k)
        yield world.env.timeout(c.TICK_MIN)


def walk_in(world: World, hospital: HospitalState, rng: object, respiratory_share: float | None, _k: int = 0) -> None:
    profile = draw_profile(world, rng)
    if profile is None:
        return
    esi = draw_esi(rng, "walk_in", profile.age)
    complaint = draw_complaint(rng, respiratory_share)
    patient = create_patient(world, hospital, profile, "walk_in", esi, complaint, world.curb())
    seat = waiting_place(world, hospital, patient.id)
    world.env.process(arrive_and_wait(world, hospital, patient, seat))


def arrive_and_wait(world: World, hospital: HospitalState, patient: Patient, seat: Place) -> SimGen:
    yield from world.walk(hospital, patient, seat)
    yield from journey(world, patient)
