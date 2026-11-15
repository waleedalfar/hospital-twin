"""Reference tables are an exact copy of shared/layout.json."""

import asyncpg

from twin.db.reference import sync_reference
from twin.sim.layout_model import load_layout


async def test_every_bed_in_the_db_is_in_the_layout_and_vice_versa(db: asyncpg.Connection) -> None:
    """CLAUDE.md §7: every bed ID in the DB exists in the layout and vice versa."""
    layout = load_layout()
    rows = await db.fetch("SELECT hospital_id, bed_id, room_id, unit, floor, x, z, rotation FROM beds")
    in_db = {(row["hospital_id"], row["bed_id"]) for row in rows}
    in_layout = {(hospital.id, bed.id) for hospital in layout.hospitals for bed in layout.beds}
    assert in_db == in_layout
    assert len(in_db) == 3 * 29
    for row in rows:
        bed = layout.beds_by_id[row["bed_id"]]
        assert (row["room_id"], row["unit"], row["floor"], row["x"], row["z"], row["rotation"]) == (
            bed.room,
            bed.unit,
            bed.floor,
            bed.x,
            bed.z,
            bed.rotation,
        )


async def test_hospitals_units_and_rooms_match_the_layout(db: asyncpg.Connection) -> None:
    layout = load_layout()
    hospitals = await db.fetch("SELECT id, name, lat, lon, status FROM hospitals ORDER BY id")
    assert {(h["id"], h["name"], h["lat"], h["lon"]) for h in hospitals} == {(h.id, h.name, h.lat, h.lon) for h in layout.hospitals}
    assert {h["status"] for h in hospitals} == {"open"}
    units = await db.fetch("SELECT id, capacity FROM units")
    assert {u["id"]: u["capacity"] for u in units} == layout.capacity
    rooms = await db.fetch("SELECT id, unit, floor FROM rooms")
    assert {(r["id"], r["unit"], r["floor"]) for r in rooms} == {(room.id, room.unit, room.floor) for room in layout.rooms.values()}
    per_unit = await db.fetch("SELECT unit, count(*) AS n FROM beds WHERE hospital_id = 'mercy' GROUP BY unit")
    assert {row["unit"]: row["n"] for row in per_unit} == {"ER": 6, "WARD": 14, "REC": 3, "ICU": 6}


async def test_sync_is_repeatable_removes_stale_rows_and_keeps_hospital_status(
    db: asyncpg.Connection,
) -> None:
    layout = load_layout()
    await db.execute("UPDATE hospitals SET status = 'offline' WHERE id = 'stlukes'")
    await db.execute("UPDATE beds SET x = 999 WHERE bed_id = 'ICU-1'")
    await db.execute("INSERT INTO units (id, name, clinical, capacity) VALUES ('OLD', 'Old unit', false, 0)")
    await db.execute("INSERT INTO rooms (id, name, unit, floor, kind, x1, x2, z1, z2) VALUES ('OLDROOM', 'Old', 'OLD', 0, 'room', 0, 1, 0, 1)")
    await db.execute(
        "INSERT INTO beds (bed_id, hospital_id, room_id, unit, floor, x, z, rotation) VALUES ('OLD-1', 'mercy', 'OLDROOM', 'OLD', 0, 0, 0, 0)"
    )
    counts = await sync_reference(db, layout)
    assert (counts.hospitals, counts.units, counts.rooms, counts.beds) == (3, 18, 24, 87)
    assert await db.fetchval("SELECT count(*) FROM beds") == 87
    assert await db.fetchval("SELECT count(*) FROM beds WHERE x = 999") == 0
    assert await db.fetchval("SELECT count(*) FROM rooms WHERE id = 'OLDROOM'") == 0
    assert await db.fetchval("SELECT count(*) FROM units WHERE id = 'OLD'") == 0
    assert await db.fetchval("SELECT status FROM hospitals WHERE id = 'stlukes'") == "offline"
