"""Records a snapshot of the running simulation for the 3D scene tests (frontend/tests/fixtures).

    uv run python -m tests.record_fixture

The snapshot comes from the real simulation (seeded, test patient pool). Risk scores do not exist before the
models are trained, so this script adds fixed fake ones to patients in beds so the risk colors, blinking
monitors and "!" signs can be rendered and checked. This file is TEST DATA ONLY and never reaches the
product path.
"""

import json
from typing import Any

from tests.sim_helpers import make_sim
from twin.common.config import REPO_ROOT
from twin.sim.engine import Simulation

OUT = REPO_ROOT / "frontend" / "tests" / "fixtures" / "snapshot_mercy.json"
SEED = 11
FACTORS = [["SpO2 drop, 2h", 0.21], ["HR trend", 0.14], ["Resp. rate", 0.09]]


def score_for(index: int, bed_id: str) -> tuple[float, str]:
    if bed_id == "ICU-3":
        return 0.81, "high"
    base = [0.12, 0.18, 0.52, 0.23, 0.64, 0.31, 0.15, 0.47][index % 8]
    return base, "high" if base >= 0.7 else "medium" if base >= 0.45 else "low"


def richness(sim: Simulation) -> int:
    mercy = sim.world.hospitals["mercy"]
    occupied = {u: sum(1 for b in mercy.beds.values() if b.unit == u and b.state == "occupied") for u in ("ER", "WARD", "REC", "ICU")}
    waiting = sum(1 for p in mercy.patients() if p.phase.startswith("waiting"))
    surgery = sum(1 for p in mercy.patients() if p.phase == "surgery")
    visitors = sum(1 for p in mercy.people.values() if p.kind == "visitor")
    icu3 = 3 if mercy.beds["ICU-3"].state == "occupied" else 0
    return (
        min(occupied["ICU"], 5) * 3
        + min(occupied["ER"], 4) * 2
        + min(occupied["WARD"], 9)
        + occupied["REC"] * 2
        + min(waiting, 6)
        + surgery * 4
        + min(visitors, 3)
        + icu3 * 4
    )


def main() -> None:
    sim = make_sim(SEED, 24, debug=False)
    best: tuple[int, dict[str, Any]] | None = None
    for minute in range(24 * 60 * 6):
        sim.tick()
        if minute % 10:
            continue
        score = richness(sim)
        if best is None or score > best[0]:
            snap = sim.snapshot("mercy", 1, False, True).model_dump(mode="json", by_alias=True)
            best = (score, snap)
    assert best is not None
    snap = best[1]
    n = 0
    for entity in snap["entities"]:
        bed = entity["location"]["bed"]
        if entity["kind"] == "patient" and bed:
            risk_score, level = score_for(n, bed)
            n += 1
            entity["risk"] = {
                "score": risk_score,
                "level": level,
                "top_factors": FACTORS,
                "model_version": "fixture",
            }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    kinds: dict[str, int] = {}
    for entity in snap["entities"]:
        kinds[entity["kind"]] = kinds.get(entity["kind"], 0) + 1
    print(f"Wrote {OUT} (richness {best[0]}, sim time {snap['sim_time']}, entities {kinds})")


if __name__ == "__main__":
    main()
