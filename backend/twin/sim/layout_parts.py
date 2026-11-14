"""Rooms, beds and bedside spots for `build_layout.py`, built from the PROMPT.md §3 tables."""

import math

from twin.sim import layout_tables as t
from twin.sim.layout_model import Bed, Facing, Rect, Room, Spot

ROTATION: dict[Facing, float] = {
    "south": 0.0,
    "north": round(math.pi, 6),
    "east": round(math.pi / 2, 6),
    "west": round(-math.pi / 2, 6),
}


def r3(value: float) -> float:
    return round(value, 3)


def rect(values: tuple[float, float, float, float]) -> Rect:
    return Rect(x1=values[0], x2=values[1], z1=values[2], z2=values[3])


def corridor_id(floor: int) -> str:
    return f"CORR-{floor}"


def elevator_id(floor: int) -> str:
    return f"ELEV-{floor}"


def build_rooms() -> dict[int, list[Room]]:
    by_floor: dict[int, list[Room]] = {level: [] for level in range(t.LEVELS + 1)}
    for d in t.ROOMS:
        by_floor[d.floor].append(
            Room(
                id=d.id,
                name=d.name,
                floor=d.floor,
                unit=d.unit,
                kind="room",
                rect=rect(d.rect),
                color=d.color,
                label_x=d.label[0],
                label_z=d.label[1],
            )
        )
    for level in range(t.LEVELS):
        by_floor[level].append(
            Room(
                id=corridor_id(level),
                name="Corridor",
                floor=level,
                unit="CORRIDOR",
                kind="corridor",
                rect=rect(t.CORRIDOR),
                color="CORR",
                label_x=0.0,
                label_z=0.0,
            )
        )
    for level in range(t.LEVELS + 1):
        by_floor[level].append(
            Room(
                id=elevator_id(level),
                name="Elevator",
                floor=level,
                unit="ELEVATOR",
                kind="elevator",
                rect=rect(t.ELEVATOR),
                color="CORR",
                label_x=t.ELEVATOR_X,
                label_z=0.0,
            )
        )
    by_floor[0].append(
        Room(
            id="OUTSIDE",
            name="Outside",
            floor=0,
            unit="OUTSIDE",
            kind="outside",
            rect=rect(t.OUTSIDE_RECT),
            color="OUT",
            label_x=14.0,
            label_z=20.0,
        )
    )
    by_floor[t.ROOF_LEVEL].append(
        Room(
            id="ROOF",
            name="Roof",
            floor=t.ROOF_LEVEL,
            unit="ROOF",
            kind="roof",
            rect=rect(t.FOOTPRINT),
            color="ROOF",
            label_x=t.HELIPAD[0],
            label_z=t.HELIPAD[1],
        )
    )
    return by_floor


def build_beds_and_bedsides() -> tuple[list[Bed], list[Spot]]:
    floors = {d.id: d.floor for d in t.ROOMS}
    units = {d.id: d.unit for d in t.ROOMS}
    beds: list[Bed] = []
    spots: list[Spot] = []
    for row in t.BED_ROWS:
        sign = 1.0 if row.head == "north" else -1.0
        for i in range(row.count):
            bed_id = f"{row.prefix}-{row.first + i}"
            spot_id = f"{row.room}-ws-{i + 1}"
            x = r3(row.x0 + row.dx * i)
            floor = floors[row.room]
            beds.append(
                Bed(
                    id=bed_id,
                    room=row.room,
                    floor=floor,
                    unit=units[row.room],
                    x=x,
                    z=row.z,
                    rotation=ROTATION[row.head],
                    head=row.head,
                    spot=spot_id,
                )
            )
            facing: Facing = "east" if row.head == "north" else "west"
            spots.append(
                Spot(
                    id=spot_id,
                    room=row.room,
                    floor=floor,
                    kind="bedside",
                    x=r3(x + sign * t.BEDSIDE_OFFSET_X),
                    z=r3(row.z + sign * t.BEDSIDE_OFFSET_Z),
                    facing=facing,
                    rotation=ROTATION[facing],
                    bed=bed_id,
                    node=f"f{floor}-{spot_id}",
                )
            )
    return beds, spots
