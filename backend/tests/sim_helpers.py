"""Helpers for simulation tests. The patient pool here is made up for tests (CLAUDE.md §1.3 allows
fixtures inside tests only)."""

import hashlib
import json
from datetime import timedelta

from twin.sim.engine import Simulation
from twin.sim.entities import PatientProfile
from twin.sim.layout_model import Layout, load_layout

SEED = 7


def make_profiles(n: int = 600) -> list[PatientProfile]:
    profiles = []
    for i in range(n):
        age = 18 + (i * 37) % 72
        profiles.append(
            PatientProfile(
                id=f"P-{i + 1:04d}",
                age=age,
                sex="female" if i % 2 else "male",
                comorbidity_count=(i * 5) % 7,
                conditions=("Essential hypertension (disorder)",) if i % 3 == 0 else (),
            )
        )
    return profiles


def make_sim(
    seed: int = SEED, warmup_h: float = 24.0, *, debug: bool = True, layout: Layout | None = None
) -> Simulation:
    return Simulation(layout or load_layout(), make_profiles(), seed, timedelta(hours=warmup_h), debug=debug)


def digest(sim: Simulation, minutes: int) -> str:
    """SHA-256 of the full event stream for `minutes` ticks."""
    h = hashlib.sha256()
    for _ in range(minutes):
        for item in sim.tick():
            h.update(item.event.model_dump_json(by_alias=True).encode())
            h.update(str(item.hospital_id).encode())
    return h.hexdigest()


def stream_json(sim: Simulation, minutes: int) -> list[str]:
    out: list[str] = []
    for _ in range(minutes):
        out.extend(
            json.dumps(i.event.model_dump(mode="json", by_alias=True), sort_keys=True) for i in sim.tick()
        )
    return out
