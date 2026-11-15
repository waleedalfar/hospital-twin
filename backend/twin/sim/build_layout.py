"""Generates `shared/layout.json` from the PROMPT.md §3 tables in `layout_tables.py`.

python -m twin.sim.build_layout          # write the file
python -m twin.sim.build_layout --check  # exit 1 if the file is missing or out of date
"""

import argparse
import json
import sys
from pathlib import Path

from twin.sim import layout_tables as t
from twin.sim.layout_graph import GraphBuilder
from twin.sim.layout_model import (
    LAYOUT_PATH,
    LAYOUT_VERSION,
    AmbulanceSlot,
    Building,
    Door,
    Floor,
    Hospital,
    Layout,
    Outside,
    Prop,
    Roof,
    Seat,
    Spot,
    Unit,
)
from twin.sim.layout_parts import (
    ROTATION,
    build_beds_and_bedsides,
    build_rooms,
    corridor_id,
    elevator_id,
    r3,
    rect,
)


def build_layout() -> Layout:
    """Assemble the whole layout from the tables."""
    room_defs = {d.id: d for d in t.ROOMS}
    rooms = build_rooms()
    doors: dict[int, list[Door]] = {level: [] for level in range(t.LEVELS + 1)}
    g = GraphBuilder()

    for d in t.ROOMS:
        for index, z in enumerate(d.lanes):
            g.add_lane(d.id, index, d.floor, z, f"f{d.floor}-{d.id}-l{index}")
    for level in range(t.LEVELS):
        g.add_lane(corridor_id(level), 0, level, 0.0, f"f{level}-c")
    g.add_lane("OUTSIDE", 0, 0, t.OUTSIDE_LANE_Z, "f0-OUTSIDE-l0")
    g.add_lane("ROOF", 0, t.ROOF_LEVEL, 0.0, f"f{t.ROOF_LEVEL}-ROOF-l0")

    # Corridor doors.
    for d in t.ROOMS:
        north = d.rect[3] <= t.CORRIDOR[2]
        wall_z = t.CORRIDOR[2] if north else t.CORRIDOR[3]
        for k, (x1, x2) in enumerate(d.doors, start=1):
            cx = (x1 + x2) / 2
            node = g.node(f"f{d.floor}-{d.id}-door-{k}", d.floor, cx, wall_z, d.id)
            doors[d.floor].append(
                Door(
                    id=f"{d.id}-door-{k}",
                    floor=d.floor,
                    rooms=(corridor_id(d.floor), d.id),
                    wall="corridor-north" if north else "corridor-south",
                    axis="x",
                    at=wall_z,
                    start=x1,
                    end=x2,
                    kind="door",
                    node=node,
                )
            )
            g.connect(node, g.lane(corridor_id(d.floor), 0, cx), "door")
            g.connect(node, g.lane(d.id, 0, cx), "door")
        for x, a, b in d.links:
            g.connect(g.lane(d.id, a, x), g.lane(d.id, b, x))

    # Elevator: one car, a door on every level, vertical edges between levels.
    for level in range(t.LEVELS + 1):
        outside_room = corridor_id(level) if level < t.LEVELS else "ROOF"
        car = g.node(f"f{level}-ELEV", level, t.ELEVATOR_X, 0.0, elevator_id(level))
        door = g.node(f"f{level}-ELEV-door", level, t.ELEVATOR_DOOR["x"], 0.0, elevator_id(level))
        doors[level].append(
            Door(
                id=f"ELEV-door-{level}",
                floor=level,
                rooms=(outside_room, elevator_id(level)),
                wall="elevator-west",
                axis="z",
                at=t.ELEVATOR_DOOR["x"],
                start=t.ELEVATOR_DOOR["z1"],
                end=t.ELEVATOR_DOOR["z2"],
                kind="elevator",
                node=door,
            )
        )
        g.connect(door, car, "door")
        g.connect(door, g.lane(outside_room, 0, t.CORRIDOR_EAST_X), "door")
        if level < t.LEVELS:
            g.lane(corridor_id(level), 0, t.CORRIDOR_WEST_X)
        if level > 0:
            g.connect(f"f{level - 1}-ELEV", car, "elevator")

    # Waiting <-> Reception opening in the wall x = 8.
    east = g.node("f0-WAITING-east", 0, 7.0, 7.0, "WAITING")
    g.connect(east, g.lane("WAITING", 0, 7.0))
    g.connect(east, g.lane("WAITING", 1, 7.0))
    opening = g.node("f0-WAITING-opening", 0, t.WAITING_OPENING["x"], 7.0, "WAITING")
    doors[0].append(
        Door(
            id="WAITING-opening",
            floor=0,
            rooms=("WAITING", "RECEPTION"),
            wall="x=8",
            axis="z",
            at=t.WAITING_OPENING["x"],
            start=t.WAITING_OPENING["z1"],
            end=t.WAITING_OPENING["z2"],
            kind="opening",
            node=opening,
        )
    )
    g.connect(east, opening, "door")
    g.connect(opening, g.lane("RECEPTION", 1, 9.5), "door")

    # Main entrance in the south exterior wall.
    entrance_x = (t.ENTRANCE["x1"] + t.ENTRANCE["x2"]) / 2
    entrance = g.node("f0-entrance", 0, entrance_x, t.ENTRANCE["z"], "RECEPTION")
    doors[0].append(
        Door(
            id="main-entrance",
            floor=0,
            rooms=("RECEPTION", "OUTSIDE"),
            wall="exterior-south",
            axis="x",
            at=t.ENTRANCE["z"],
            start=t.ENTRANCE["x1"],
            end=t.ENTRANCE["x2"],
            kind="entrance",
            node=entrance,
        )
    )
    g.connect(entrance, g.lane("RECEPTION", 1, entrance_x), "door")
    g.connect(entrance, g.lane("OUTSIDE", 0, entrance_x), "door")

    beds, spots = build_beds_and_bedsides()
    lane_of_bed_room = 0
    for spot in spots:
        g.node(spot.node, spot.floor, spot.x, spot.z, spot.room)
        g.connect(spot.node, g.lane(spot.room, lane_of_bed_room, spot.x))

    seats: list[Seat] = []
    props: list[Prop] = []
    for s in t.SEATS:
        floor = room_defs[s.room].floor
        node = g.node(f"f{floor}-{s.id}", floor, s.x, s.z, s.room)
        g.connect(node, g.lane(s.room, s.lane, s.x))
        seats.append(
            Seat.model_validate(
                {
                    "id": s.id,
                    "room": s.room,
                    "floor": floor,
                    "kind": s.kind,
                    "x": r3(s.x),
                    "z": r3(s.z),
                    "facing": s.facing,
                    "rotation": ROTATION[s.facing],
                    "node": node,
                }
            )
        )
        if s.chair:
            props.append(
                Prop(
                    id=f"{s.id}-chair",
                    type="chair",
                    room=s.room,
                    floor=floor,
                    x=r3(s.x),
                    z=r3(s.z),
                    w=0.6,
                    d=0.6,
                    rotation=ROTATION[s.facing],
                    target=s.id,
                )
            )
    for p in t.SPOTS:
        floor = room_defs[p.room].floor
        node = g.node(f"f{floor}-{p.id}", floor, p.x, p.z, p.room)
        g.connect(node, g.lane(p.room, p.lane, p.x))
        spots.append(
            Spot.model_validate(
                {
                    "id": p.id,
                    "room": p.room,
                    "floor": floor,
                    "kind": p.kind,
                    "x": r3(p.x),
                    "z": r3(p.z),
                    "facing": p.facing,
                    "rotation": ROTATION[p.facing],
                    "node": node,
                }
            )
        )

    # Outside: ambulance slots with an unload spot each, and the curb where walk-ins appear.
    slots: list[AmbulanceSlot] = []
    for i, x in enumerate(t.AMBULANCE_SLOT_XS, start=1):
        spot_id = f"AMB-unload-{i}"
        node = g.node(f"f0-{spot_id}", 0, x, t.UNLOAD_Z, "OUTSIDE")
        g.connect(node, g.lane("OUTSIDE", 0, x))
        spots.append(
            Spot(
                id=spot_id,
                room="OUTSIDE",
                floor=0,
                kind="unload",
                x=x,
                z=t.UNLOAD_Z,
                facing="north",
                rotation=ROTATION["north"],
                node=node,
            )
        )
        slots.append(AmbulanceSlot(id=f"AMB-slot-{i}", x=x, z=t.AMBULANCE_SLOT_Z, rotation=ROTATION["north"], spot=spot_id))
    curb = g.node("f0-CURB", 0, t.CURB[0], t.CURB[1], "OUTSIDE")
    g.connect(curb, g.lane("OUTSIDE", 0, t.CURB[0]))
    spots.append(
        Spot(
            id="CURB",
            room="OUTSIDE",
            floor=0,
            kind="curb",
            x=t.CURB[0],
            z=t.CURB[1],
            facing="north",
            rotation=ROTATION["north"],
            node=curb,
        )
    )

    # Roof: the helipad spot next to the parked helicopter.
    pad = g.node(f"f{t.ROOF_LEVEL}-HELIPAD", t.ROOF_LEVEL, t.HELIPAD_SPOT[0], t.HELIPAD_SPOT[1], "ROOF")
    g.connect(pad, g.lane("ROOF", 0, t.CORRIDOR_EAST_X))
    spots.append(
        Spot(
            id="HELIPAD",
            room="ROOF",
            floor=t.ROOF_LEVEL,
            kind="helipad",
            x=t.HELIPAD_SPOT[0],
            z=t.HELIPAD_SPOT[1],
            facing="west",
            rotation=ROTATION["west"],
            node=pad,
        )
    )

    for pd in t.PROPS:
        floor = t.ROOF_LEVEL if pd.room == "ROOF" else room_defs[pd.room].floor
        props.append(
            Prop(
                id=pd.id,
                type=pd.type,
                room=pd.room,
                floor=floor,
                x=r3(pd.x),
                z=r3(pd.z),
                w=pd.w,
                d=pd.d,
                blocks=pd.blocks,
            )
        )
    for level in range(t.LEVELS):
        props.append(
            Prop(
                id=f"stairs-{level}",
                type="stairs",
                room=corridor_id(level),
                floor=level,
                x=-19.2,
                z=-0.05,
                w=1.2,
                d=3.6,
            )
        )

    capacity = {unit_id: 0 for unit_id, _, _ in t.UNITS}
    for bed in beds:
        capacity[bed.unit] += 1
    capacity["WAITING"] = sum(1 for seat in seats if seat.kind == "waiting")
    capacity["TRIAGE"] = sum(1 for seat in seats if seat.kind == "triage")
    capacity["OR"] = sum(1 for spot in spots if spot.room == "OR" and spot.kind == "table")

    return Layout(
        version=LAYOUT_VERSION,
        units="meters",
        building=Building(
            footprint=rect(t.FOOTPRINT),
            levels=t.LEVELS,
            floor_height=t.FLOOR_HEIGHT,
            slab=t.SLAB,
            wall_height=t.WALL_HEIGHT,
            corridor=rect(t.CORRIDOR),
            stairs=rect(t.STAIRS),
            elevator=rect(t.ELEVATOR),
        ),
        hospitals=[Hospital(id=h[0], name=h[1], lat=h[2], lon=h[3], helipad=h[4]) for h in t.HOSPITALS],
        care_units=[Unit(id=u[0], name=u[1], clinical=u[2], capacity=capacity[u[0]]) for u in t.UNITS],
        floors=[Floor(level=level, name=t.FLOOR_NAMES[level], rooms=rooms[level], doors=doors[level]) for level in range(t.LEVELS + 1)],
        beds=beds,
        seats=seats,
        spots=spots,
        props=props,
        outside=Outside(
            ambulance_bay=rect(t.AMBULANCE_BAY),
            ambulance_slots=slots,
            street_z=t.STREET_Z,
            street_width=t.STREET_WIDTH,
            entrance_node=entrance,
            curb_spot="CURB",
        ),
        roof=Roof(
            level=t.ROOF_LEVEL,
            helipad_x=t.HELIPAD[0],
            helipad_z=t.HELIPAD[1],
            helipad_size=t.HELIPAD[2],
            helicopter_x=t.HELIPAD[0],
            helicopter_z=t.HELIPAD[1],
            helipad_spot="HELIPAD",
        ),
        graph=g.build(t.FLOOR_HEIGHT),
    )


def render(layout: Layout) -> str:
    """The exact text written to `shared/layout.json`."""
    return json.dumps(layout.model_dump(mode="json"), indent=1, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate shared/layout.json")
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    parser.add_argument("--path", type=Path, default=LAYOUT_PATH)
    args = parser.parse_args(argv)
    text = render(build_layout())
    path: Path = args.path
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            print(f"{path} is out of date. Run: python -m twin.sim.build_layout", file=sys.stderr)
            return 1
        print(f"{path} is up to date")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
