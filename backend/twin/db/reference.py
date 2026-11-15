"""Copies the building from `shared/layout.json` into the reference tables (hospitals, units, rooms, beds).

The layout file is the single source of truth; the tables are a copy so SQL can join against them.
Every hospital uses the same building template, so each one gets the full set of beds.
"""

from dataclasses import dataclass

import asyncpg

from twin.sim.layout_model import Layout


@dataclass(frozen=True)
class ReferenceCounts:
    hospitals: int
    units: int
    rooms: int
    beds: int


async def sync_reference(conn: asyncpg.Connection, layout: Layout) -> ReferenceCounts:
    """Make the reference tables match `layout` exactly. Safe to run repeatedly."""
    rooms = list(layout.rooms.values())
    beds = [(bed, hospital.id) for hospital in layout.hospitals for bed in layout.beds]
    async with conn.transaction():
        # A hospital's live status belongs to the simulation, so an existing row keeps its status.
        await conn.executemany(
            """
            INSERT INTO hospitals (id, name, lat, lon) VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon
            """,
            [(h.id, h.name, h.lat, h.lon) for h in layout.hospitals],
        )
        await conn.executemany(
            """
            INSERT INTO units (id, name, clinical, capacity) VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name, clinical = EXCLUDED.clinical, capacity = EXCLUDED.capacity
            """,
            [(u.id, u.name, u.clinical, u.capacity) for u in layout.care_units],
        )
        await conn.executemany(
            """
            INSERT INTO rooms (id, name, unit, floor, kind, x1, x2, z1, z2)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name, unit = EXCLUDED.unit, floor = EXCLUDED.floor, kind = EXCLUDED.kind,
                x1 = EXCLUDED.x1, x2 = EXCLUDED.x2, z1 = EXCLUDED.z1, z2 = EXCLUDED.z2
            """,
            [(r.id, r.name, r.unit, r.floor, r.kind, r.rect.x1, r.rect.x2, r.rect.z1, r.rect.z2) for r in rooms],
        )
        await conn.executemany(
            """
            INSERT INTO beds (bed_id, hospital_id, room_id, unit, floor, x, z, rotation)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (hospital_id, bed_id) DO UPDATE
            SET room_id = EXCLUDED.room_id, unit = EXCLUDED.unit, floor = EXCLUDED.floor,
                x = EXCLUDED.x, z = EXCLUDED.z, rotation = EXCLUDED.rotation
            """,
            [(b.id, hospital_id, b.room, b.unit, b.floor, b.x, b.z, b.rotation) for b, hospital_id in beds],
        )
        # Remove anything the layout no longer has, children first.
        await conn.execute(
            "DELETE FROM beds WHERE NOT (hospital_id || '/' || bed_id = ANY($1::text[]))",
            [f"{hospital_id}/{b.id}" for b, hospital_id in beds],
        )
        await conn.execute("DELETE FROM rooms WHERE NOT (id = ANY($1::text[]))", [r.id for r in rooms])
        await conn.execute("DELETE FROM units WHERE NOT (id = ANY($1::text[]))", [u.id for u in layout.care_units])
    return ReferenceCounts(hospitals=len(layout.hospitals), units=len(layout.care_units), rooms=len(rooms), beds=len(beds))
