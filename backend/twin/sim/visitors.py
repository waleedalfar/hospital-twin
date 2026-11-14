"""Visitors (§5.3): some admitted patients get a visitor who sits in the waiting room for a while."""

from twin.common.ws import DespawnEvent, SpawnEvent
from twin.sim import config as c
from twin.sim.entities import Patient, Visitor
from twin.sim.hospital import HospitalState
from twin.sim.snapshot import entity_model
from twin.sim.world import SimGen, World


def maybe_visit(world: World, hospital: HospitalState, patient: Patient) -> None:
    if patient.visitor_id is not None or patient.unit not in ("WARD", "ICU"):
        return
    rng = world.rng("visitor", patient.id)
    if rng.random() >= c.VISITOR_SHARE:
        patient.visitor_id = ""
        return
    patient.visitor_id = world.next_id("V")
    world.env.process(visit(world, hospital, patient.id, patient.visitor_id))


def visit(world: World, hospital: HospitalState, patient_id: str, visitor_id: str) -> SimGen:
    from twin.sim.patients import waiting_place

    rng = world.rng("visitor", visitor_id)
    yield world.env.timeout(rng.uniform(*c.VISITOR_DELAY_MIN))
    visitor = Visitor(
        id=visitor_id,
        kind="visitor",
        hospital_id=hospital.id,
        place=world.curb(),
        appearance=world.appearance(visitor_id),
        patient_id=patient_id,
        task="visiting",
    )
    seat = waiting_place(world, hospital, visitor_id)
    if seat == world.curb():
        return
    hospital.people[visitor_id] = visitor
    world.emit(hospital.id, SpawnEvent(time=world.time(), entity=entity_model(world, visitor)))
    yield from world.walk(hospital, visitor, seat)
    yield world.env.timeout(rng.uniform(*c.VISITOR_STAY_MIN))
    old = visitor.place
    hospital.release_place(old, visitor_id)
    yield from world.walk(hospital, visitor, world.curb(), start=old)
    del hospital.people[visitor_id]
    visitor.hospital_id = None
    world.emit(hospital.id, DespawnEvent(time=world.time(), entity_id=visitor_id, reason="left"))
