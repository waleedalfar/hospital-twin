"""The fixed, read-only tool set behind "Ask Hospital Twin" (PROMPT.md §9.1).

Each tool answers from the live simulation state, the same state the REST API serves, and the forecasts table.
Tools never change anything. Their results are plain dictionaries of numbers, ids and names: those are the only
facts an answer may use (see `grounding.py`).
"""

import math
from dataclasses import dataclass
from typing import Any

from twin.agent.summary import STAFF_UNITS
from twin.db.pool import Pool
from twin.ml.forecast import BED_UNITS, HORIZON_H, MAX_HOURS_UNTIL_FULL
from twin.sim import config as c
from twin.sim.engine import Simulation
from twin.sim.entities import Patient
from twin.sim.hospital import HospitalState
from twin.sim.snapshot import kpis

TOOL_NAMES = ("list_high_risk_patients", "get_occupancy", "get_forecast", "find_patient", "get_er_wait", "get_staffing")
MAX_LIMIT = 20


class ToolError(Exception):
    """A tool was called with something that does not exist (unknown hospital, unit or patient)."""


# Declarations for Gemini function calling: name, description and a JSON-schema of the parameters.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_high_risk_patients",
        "description": "Patients with the highest deterioration risk right now, highest first.",
        "parameters": {
            "type": "object",
            "properties": {
                "hospital": {"type": "string", "description": "mercy, stlukes or desert"},
                "unit": {"type": "string", "description": "optional: ER, WARD, ICU or REC"},
                "limit": {"type": "integer", "description": "how many patients, 1-20"},
            },
            "required": ["hospital"],
        },
    },
    {
        "name": "get_occupancy",
        "description": "Occupied beds and capacity per unit.",
        "parameters": {
            "type": "object",
            "properties": {"hospital": {"type": "string"}, "unit": {"type": "string", "description": "optional: ER, WARD, ICU or REC"}},
            "required": ["hospital"],
        },
    },
    {
        "name": "get_forecast",
        "description": "Expected ER arrivals for the next 6 hours and the hours until each unit is full.",
        "parameters": {
            "type": "object",
            "properties": {"hospital": {"type": "string"}, "unit": {"type": "string", "description": "optional: ER, WARD, ICU or REC"}},
            "required": ["hospital"],
        },
    },
    {
        "name": "find_patient",
        "description": "Where one patient is, and their risk, vitals and expected discharge.",
        "parameters": {
            "type": "object",
            "properties": {"patient_id": {"type": "string", "description": "for example P-0412"}},
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_er_wait",
        "description": "Current ER wait in minutes and how many patients are waiting.",
        "parameters": {"type": "object", "properties": {"hospital": {"type": "string"}}, "required": ["hospital"]},
    },
    {
        "name": "get_staffing",
        "description": "Nurses on duty against the number the ratio requires, per unit.",
        "parameters": {
            "type": "object",
            "properties": {"hospital": {"type": "string"}, "unit": {"type": "string", "description": "optional: ER, WARD, ICU or REC"}},
            "required": ["hospital"],
        },
    },
]


def _unit(unit: str | None) -> str | None:
    if unit is None or unit == "":
        return None
    u = unit.upper()
    if u not in BED_UNITS:
        raise ToolError(f"Unknown unit {unit}; choose one of {', '.join(BED_UNITS)}")
    return u


def _r(x: float) -> float:
    return round(x, 1)


@dataclass
class ToolBox:
    sim: Simulation
    pool: Pool

    def _hospital(self, hospital: str) -> HospitalState:
        hospital_state = self.sim.world.hospitals.get(hospital)
        if hospital_state is None:
            raise ToolError(f"Unknown hospital {hospital}; choose one of {', '.join(sorted(self.sim.world.hospitals))}")
        return hospital_state

    def _unit_of(self, hospital: HospitalState, p: Patient) -> str:
        return hospital.beds[p.place.bed].unit if p.place.bed else (p.unit or "WAITING")

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool by name. Unknown tools and bad arguments raise ToolError."""
        if name not in TOOL_NAMES:
            raise ToolError(f"Unknown tool {name}")
        try:
            result: dict[str, Any] = await getattr(self, name)(**args)
            return result
        except TypeError as error:
            raise ToolError(f"Bad arguments for {name}: {error}") from error

    async def list_high_risk_patients(self, hospital: str, unit: str | None = None, limit: int = 5) -> dict[str, Any]:
        h, u = self._hospital(hospital), _unit(unit)
        n = max(1, min(int(limit), MAX_LIMIT))
        scored = [p for p in h.patients() if p.risk is not None and (u is None or self._unit_of(h, p) == u)]
        scored.sort(key=lambda p: (-(p.risk.score if p.risk else 0.0), p.id))
        return {
            "hospital": hospital,
            "unit": u,
            "patients": [
                {
                    "patient_id": p.id,
                    "unit": self._unit_of(h, p),
                    "bed": p.place.bed,
                    "score": round(p.risk.score, 2) if p.risk else 0.0,
                    "level": p.risk.level if p.risk else "low",
                    "top_factors": [name for name, _ in (p.risk.top_factors if p.risk else [])],
                }
                for p in scored[:n]
            ],
        }

    async def get_occupancy(self, hospital: str, unit: str | None = None) -> dict[str, Any]:
        h, u = self._hospital(hospital), _unit(unit)
        cap = self.sim.world.layout.capacity
        rows = []
        for unit_name in BED_UNITS if u is None else (u,):
            occupied = sum(1 for b in h.beds.values() if b.unit == unit_name and b.state == "occupied")
            rows.append(
                {"unit": unit_name, "occupied": occupied, "capacity": cap[unit_name], "occupancy_pct": _r(100.0 * occupied / max(1, cap[unit_name]))}
            )
        return {"hospital": hospital, "units": rows}

    async def get_forecast(self, hospital: str, unit: str | None = None) -> dict[str, Any]:
        self._hospital(hospital)
        u = _unit(unit)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (metric, horizon_h) metric, horizon_h, value FROM forecasts
                WHERE hospital_id = $1 AND time <= $2 ORDER BY metric, horizon_h, time DESC
                """,
                hospital,
                self.sim.now,
            )
        arrivals = [
            {"hours_ahead": r["horizon_h"], "expected": _r(r["value"])}
            for r in sorted(rows, key=lambda r: r["horizon_h"])
            if r["metric"] == "arrivals"
        ]
        until_full: dict[str, float | None] = {}
        for r in rows:
            if r["metric"].startswith("hours_until_full:"):
                name = r["metric"].split(":", 1)[1]
                if u is None or name == u:
                    until_full[name] = _r(r["value"]) if r["value"] <= MAX_HOURS_UNTIL_FULL else None
        return {
            "hospital": hospital,
            "horizon_h": HORIZON_H,
            "expected_arrivals_total": _r(sum(a["expected"] for a in arrivals)),
            "arrivals": arrivals,
            "hours_until_full": until_full,
            "forecast_available": bool(rows),
        }

    async def find_patient(self, patient_id: str) -> dict[str, Any]:
        for hospital in self.sim.world.hospitals.values():
            p = next((x for x in hospital.patients() if x.id == patient_id.upper()), None)
            if p is None:
                continue
            where = self.sim.world.location(p.place)
            return {
                "found": True,
                "patient_id": p.id,
                "hospital": hospital.id,
                "unit": self._unit_of(hospital, p),
                "bed": p.place.bed,
                "floor": where.floor,
                "room": where.room,
                "phase": p.phase,
                "score": round(p.risk.score, 2) if p.risk else None,
                "level": p.risk.level if p.risk else None,
                "expected_discharge_h": p.expected_discharge_h,
            }
        return {"found": False, "patient_id": patient_id.upper()}

    async def get_er_wait(self, hospital: str) -> dict[str, Any]:
        k = kpis(self.sim.world, self._hospital(hospital))
        return {"hospital": hospital, "er_wait_min": _r(k.er_wait_min), "waiting": k.waiting}

    async def get_staffing(self, hospital: str, unit: str | None = None) -> dict[str, Any]:
        h, u = self._hospital(hospital), _unit(unit)
        rows = []
        for unit_name in STAFF_UNITS if u is None else (u,):
            occupied = sum(1 for b in h.beds.values() if b.unit == unit_name and b.state == "occupied")
            nurses = sum(1 for s in h.staff() if s.kind == "nurse" and s.unit == unit_name and s.on_duty)
            required = math.ceil(occupied / c.NURSE_RATIO[unit_name]) if unit_name in c.NURSE_RATIO else 0
            rows.append({"unit": unit_name, "nurses": nurses, "required": required})
        return {"hospital": hospital, "units": rows}
