"""Writes what the simulation emits to Tiger Data (PROMPT.md §4.1): vitals, events, bed snapshots,
encounters, staff. Rows are buffered and written with COPY."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from twin.common.ws import (
    AdmitEvent,
    ArrivalEvent,
    DischargeEvent,
    HospitalStatusEvent,
    StaffEvent,
    SurgeryEvent,
    TransferEvent,
    VitalsEvent,
)
from twin.db.pool import Conn
from twin.sim.entities import Staff
from twin.sim.world import Emitted, World

RUN_TABLES = (
    "vitals",
    "events",
    "bed_state",
    "risk_scores",
    "forecasts",
    "agent_recs",
    "audit_log",
    "drift",
    "encounters",
    "staff",
)
NETWORK = "network"
BED_SNAPSHOT_MIN = 5
FIRST_DISPOSITION = {"WARD": "admit_ward", "ICU": "admit_icu", "REC": "surgery"}


async def reset_run(conn: Conn) -> None:
    """Start a new simulation run: remove the previous run's rows. Synthea patients and the building stay."""
    await conn.execute(f"TRUNCATE {', '.join(RUN_TABLES)}")
    await conn.execute("UPDATE hospitals SET status = 'open'")


def entity_of(event: Any) -> str | None:
    for name in ("patient_id", "entity_id", "vehicle_id", "bed_id", "scenario_id"):
        value = getattr(event, name, None)
        if isinstance(value, str):
            return value
    return None


@dataclass
class Batch:
    vitals: list[tuple[Any, ...]] = field(default_factory=list)
    events: list[tuple[Any, ...]] = field(default_factory=list)
    bed_state: list[tuple[Any, ...]] = field(default_factory=list)
    encounters: list[tuple[Any, ...]] = field(default_factory=list)
    encounter_updates: list[tuple[Any, ...]] = field(default_factory=list)
    staff: list[tuple[Any, ...]] = field(default_factory=list)
    hospital_status: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.vitals) + len(self.events) + len(self.bed_state) + len(self.encounters)


class SimWriter:
    def __init__(self, world: World) -> None:
        self._world = world
        self._batch = Batch()
        self._encounter_of: dict[str, int] = {}
        self._staff_written: set[str] = set()
        self._last_snapshot_minute = -1

    @property
    def pending(self) -> int:
        return len(self._batch)

    def add(self, emitted: list[Emitted]) -> None:
        """Turn one tick's events into rows, and take a bed snapshot every BED_SNAPSHOT_MIN sim minutes."""
        batch = self._batch
        for item in emitted:
            event = item.event
            hospital_id = item.hospital_id or NETWORK
            if isinstance(event, VitalsEvent):
                v = event.vitals
                batch.vitals.append(
                    (event.time, event.patient_id, hospital_id, v.hr, v.spo2, v.sbp, v.dbp, v.temp, v.rr)
                )
                continue
            payload = event.model_dump(mode="json", by_alias=True, exclude={"time", "kind"})
            batch.events.append((event.time, hospital_id, event.kind, entity_of(event), json.dumps(payload)))
            self._encounter_rows(event, hospital_id)
            if isinstance(event, StaffEvent):
                self._staff_row(event.entity_id)
            if isinstance(event, HospitalStatusEvent):
                batch.hospital_status[hospital_id] = event.status
        minute = round(self._world.now)
        if minute % BED_SNAPSHOT_MIN == 0 and minute != self._last_snapshot_minute:
            self._last_snapshot_minute = minute
            when = self._world.time()
            for hospital in self._world.hospitals.values():
                for bed in hospital.beds.values():
                    batch.bed_state.append((when, bed.id, hospital.id, bed.patient_id, bed.state))

    def _encounter_rows(self, event: Any, hospital_id: str) -> None:
        batch = self._batch
        if isinstance(event, ArrivalEvent):
            self._encounter_of[event.patient_id] = event.encounter_id
            patient = self._world.patient(event.patient_id)
            esi = patient[1].esi if patient is not None else event.esi
            batch.encounters.append(
                (event.encounter_id, event.patient_id, hospital_id, event.time, event.mode, esi)
            )
            return
        patient_id = getattr(event, "patient_id", None)
        encounter = self._encounter_of.get(patient_id) if isinstance(patient_id, str) else None
        if encounter is None:
            return
        if isinstance(event, AdmitEvent) and event.unit in FIRST_DISPOSITION:
            batch.encounter_updates.append(("first", encounter, FIRST_DISPOSITION[event.unit], None))
        elif isinstance(event, SurgeryEvent) and event.phase == "start":
            batch.encounter_updates.append(("first", encounter, "surgery", None))
        elif isinstance(event, DischargeEvent):
            batch.encounter_updates.append(("end", encounter, "discharge", event.time))
        elif isinstance(event, TransferEvent):
            batch.encounter_updates.append(("transfer", encounter, "transfer", event.time))

    def _staff_row(self, staff_id: str) -> None:
        if staff_id in self._staff_written:
            return
        staff = self._world.staff_by_id(staff_id)
        if isinstance(staff, Staff):
            self._staff_written.add(staff_id)
            self._batch.staff.append(
                (staff.id, staff.home_hospital, staff.kind, staff.unit or "ER", staff.id)
            )

    def add_all_staff(self) -> None:
        for staff_id in sorted(self._world.staff):
            self._staff_row(staff_id)

    async def flush(self, conn: Conn) -> int:
        """Write everything buffered in one transaction. Returns the number of rows written."""
        batch, self._batch = self._batch, Batch()
        written = len(batch) + len(batch.staff)
        async with conn.transaction():
            if batch.staff:
                await conn.executemany(
                    "INSERT INTO staff (id, hospital_id, role, unit, name_code) VALUES ($1, $2, $3, $4, $5) "
                    "ON CONFLICT (id) DO NOTHING",
                    batch.staff,
                )
            if batch.encounters:
                await conn.copy_records_to_table(
                    "encounters",
                    records=batch.encounters,
                    columns=["id", "patient_id", "hospital_id", "arrived_at", "mode", "esi"],
                )
            for kind, encounter, disposition, ended in batch.encounter_updates:
                if kind == "first":
                    await conn.execute(
                        "UPDATE encounters SET disposition = COALESCE(disposition, $2) WHERE id = $1",
                        encounter,
                        disposition,
                    )
                elif kind == "end":
                    await conn.execute(
                        "UPDATE encounters SET disposition = COALESCE(disposition, $2), ended_at = $3 "
                        "WHERE id = $1",
                        encounter,
                        disposition,
                        ended,
                    )
                else:
                    await conn.execute(
                        "UPDATE encounters SET disposition = $2, ended_at = $3 WHERE id = $1",
                        encounter,
                        disposition,
                        ended,
                    )
            for table, rows in (
                ("vitals", batch.vitals),
                ("events", batch.events),
                ("bed_state", batch.bed_state),
            ):
                if rows:
                    await conn.copy_records_to_table(table, records=rows, columns=COLUMNS[table])
            for hospital_id, status in batch.hospital_status.items():
                await conn.execute("UPDATE hospitals SET status = $2 WHERE id = $1", hospital_id, status)
        return written


COLUMNS = {
    "vitals": ["time", "patient_id", "hospital_id", "hr", "spo2", "sbp", "dbp", "temp", "rr"],
    "events": ["time", "hospital_id", "kind", "entity_id", "payload"],
    "bed_state": ["time", "bed_id", "hospital_id", "patient_id", "state"],
}


async def write_audit(conn: Conn, when: datetime, actor: str, action: str, payload: dict[str, Any]) -> None:
    await conn.execute(
        "INSERT INTO audit_log (time, actor, action, payload) VALUES ($1, $2, $3, $4::jsonb)",
        when,
        actor,
        action,
        json.dumps(payload),
    )
