"""`shared/layout.json` checked against the tables in PROMPT.md §3.

The expected values below are typed from the spec by hand, on purpose: they do not import the generator's
tables, so a wrong number in `layout_tables.py` fails here.
"""

import math
import re
from pathlib import Path

import pytest

from twin.sim import build_layout
from twin.sim.layout_model import LAYOUT_PATH, Layout, load_layout

# room id -> (floor, rect x1,x2,z1,z2, door gaps on the corridor wall)
SPEC_ROOMS: dict[str, tuple[int, tuple[float, float, float, float], list[tuple[float, float]]]] = {
    "ER": (0, (-20, -4, -14, -2), [(-13, -10)]),
    "IMAGING": (0, (-4, 8, -14, -2), [(0, 3)]),
    "PHARMACY": (0, (8, 20, -14, -2), [(12, 14.5)]),
    "TRIAGE": (0, (-20, -4, 2, 14), [(-13, -10)]),
    "WAITING": (0, (-4, 8, 2, 14), [(-2, 4)]),
    "RECEPTION": (0, (8, 20, 2, 14), [(10, 13)]),
    "WARD_A": (1, (-20, 6, -14, -2), [(-14, -11), (-1, 2)]),
    "OR": (1, (6, 20, -14, -2), [(10, 13)]),
    "WARD_B": (1, (-20, 6, 2, 14), [(-14, -11), (-1, 2)]),
    "RECOVERY": (1, (6, 20, 2, 14), [(10, 13)]),
    "ICU": (2, (-20, 6, -14, -2), [(-14, -11), (-1, 2)]),
    "LAB": (2, (6, 20, -14, -2), [(10, 13)]),
    "STAFF": (2, (-20, -4, 2, 14), [(-13, -10)]),
    "PRAYER": (2, (-4, 6, 2, 14), [(0, 3)]),
    "ADMIN": (2, (6, 20, 2, 14), [(10, 13)]),
}

# bed prefix, first number, count, room, floor, x0, dx, z, head
SPEC_BEDS = [
    ("ER", 1, 6, "ER", 0, -18.0, 2.6, -12.4, "north"),
    ("WARD", 1, 8, "WARD_A", 1, -18.5, 2.9, -12.4, "north"),
    ("WARD", 9, 6, "WARD_B", 1, -18.5, 3.0, 12.4, "south"),
    ("REC", 1, 3, "RECOVERY", 1, 9.0, 3.5, 12.4, "south"),
    ("ICU", 1, 6, "ICU", 2, -18.5, 3.6, -12.4, "north"),
]


@pytest.fixture(scope="module")
def layout() -> Layout:
    return load_layout()


def props_of(layout: Layout, prop_type: str) -> list[tuple[float, float]]:
    return sorted((p.x, p.z) for p in layout.props if p.type == prop_type)


def test_building_dimensions(layout: Layout) -> None:
    b = layout.building
    assert (b.footprint.x1, b.footprint.x2, b.footprint.z1, b.footprint.z2) == (-20, 20, -14, 14)
    assert (b.floor_height, b.slab, b.wall_height, b.levels) == (3.4, 0.3, 3.0, 3)
    assert (b.corridor.x1, b.corridor.x2, b.corridor.z1, b.corridor.z2) == (-20, 17, -2, 2)
    assert (b.stairs.x1, b.stairs.x2) == (-20, -17)
    assert (b.elevator.x1, b.elevator.x2, b.elevator.z1, b.elevator.z2) == (17, 20, -2, 2)
    assert layout.units == "meters"


def test_every_spec_room_has_the_right_floor_and_rectangle(layout: Layout) -> None:
    listed = {room.id for room in layout.rooms.values() if room.kind == "room"}
    assert listed == set(SPEC_ROOMS)
    for room_id, (floor, rect, _) in SPEC_ROOMS.items():
        room = layout.rooms[room_id]
        assert room.floor == floor, room_id
        assert (room.rect.x1, room.rect.x2, room.rect.z1, room.rect.z2) == rect, room_id
        assert room.color, room_id


def test_corridor_doors_match_the_spec(layout: Layout) -> None:
    for room_id, (floor, rect, gaps) in SPEC_ROOMS.items():
        doors = [d for d in layout.doors if d.kind == "door" and room_id in d.rooms]
        assert sorted((d.start, d.end) for d in doors) == sorted(gaps), room_id
        north_of_corridor = rect[3] == -2
        for door in doors:
            assert door.floor == floor
            assert door.axis == "x"
            assert door.at == (-2 if north_of_corridor else 2)
            assert door.wall == ("corridor-north" if north_of_corridor else "corridor-south")
            assert f"CORR-{floor}" in door.rooms


def test_reception_opening_and_main_entrance(layout: Layout) -> None:
    opening = next(d for d in layout.doors if d.kind == "opening")
    assert set(opening.rooms) == {"WAITING", "RECEPTION"}
    assert (opening.axis, opening.at, opening.start, opening.end) == ("z", 8, 5, 9)
    entrance = next(d for d in layout.doors if d.kind == "entrance")
    assert set(entrance.rooms) == {"RECEPTION", "OUTSIDE"}
    assert (entrance.axis, entrance.at, entrance.start, entrance.end) == ("x", 14, 12, 16)


def test_beds_match_the_spec(layout: Layout) -> None:
    expected_ids: list[str] = []
    for prefix, first, count, room, floor, x0, dx, z, head in SPEC_BEDS:
        for i in range(count):
            bed_id = f"{prefix}-{first + i}"
            expected_ids.append(bed_id)
            bed = layout.beds_by_id[bed_id]
            assert bed.room == room, bed_id
            assert bed.floor == floor, bed_id
            assert bed.x == pytest.approx(x0 + dx * i, abs=1e-9), bed_id
            assert bed.z == z, bed_id
            assert bed.head == head, bed_id
            # the head end is local -z: rotation 0 = head north, pi = head south
            assert bed.rotation == pytest.approx(0.0 if head == "north" else math.pi, abs=1e-5), bed_id
            assert layout.rooms[room].rect.contains(bed.x, bed.z), bed_id
    assert [bed.id for bed in layout.beds] == expected_ids


def test_capacity_per_hospital(layout: Layout) -> None:
    cap = layout.capacity
    assert (cap["ER"], cap["WARD"], cap["REC"], cap["ICU"]) == (6, 14, 3, 6)
    assert cap["ER"] + cap["WARD"] + cap["REC"] + cap["ICU"] == 29 == len(layout.beds)
    assert (cap["OR"], cap["WAITING"], cap["TRIAGE"]) == (1, 12, 2)
    assert {bed.unit for bed in layout.beds} == {"ER", "WARD", "REC", "ICU"}


def test_waiting_seats(layout: Layout) -> None:
    seats = [s for s in layout.seats if s.kind == "waiting"]
    assert [s.id for s in seats] == [f"W-{n}" for n in range(1, 13)]
    expected = sorted((round(-2.5 + 1.7 * k, 3), z) for z in (7.0, 10.0) for k in range(6))
    assert sorted((s.x, s.z) for s in seats) == expected
    assert {s.facing for s in seats} == {"north"}
    assert {s.room for s in seats} == {"WAITING"}


def test_triage_desk_and_seats(layout: Layout) -> None:
    assert props_of(layout, "triage_desk") == [(-12, 6)]
    seats = [s for s in layout.seats if s.kind == "triage"]
    assert len(seats) == 2
    assert {s.room for s in seats} == {"TRIAGE"}


def test_ground_floor_contents(layout: Layout) -> None:
    assert props_of(layout, "ct_scanner") == [(2, -10)]
    table = next(p for p in layout.props if p.type == "ct_table")
    assert table.x == 2
    assert (table.z + -10) / 2 == pytest.approx(-9.1)  # scanner + table centered near (2, -9)
    assert props_of(layout, "shelf") == [(11, -9), (14, -9), (17, -9)]
    assert len(props_of(layout, "curtain")) == 5  # between the 6 ER bays
    desk = next(p for p in layout.props if p.type == "reception_desk")
    assert desk.x == 18


def test_curtains_and_glass_sit_between_neighbouring_beds(layout: Layout) -> None:
    for prop_type, prefix in (("curtain", "ER"), ("glass_partition", "ICU")):
        xs = sorted(p.x for p in layout.props if p.type == prop_type)
        beds = sorted(b.x for b in layout.beds if b.id.startswith(prefix + "-"))
        assert len(xs) == len(beds) - 1
        for x, left, right in zip(xs, beds, beds[1:], strict=False):
            assert left + 0.55 < x < right - 0.55


def test_upper_floor_contents(layout: Layout) -> None:
    assert props_of(layout, "or_table") == [(13, -8)]
    assert len(props_of(layout, "or_lamp")) == 1
    assert len(props_of(layout, "anesthesia_machine")) == 1
    assert props_of(layout, "lab_bench") == [(13, -9), (13, -6)]
    assert len(props_of(layout, "couch")) == 1
    assert len(props_of(layout, "coffee_table")) == 1
    assert len(props_of(layout, "vending_machine")) == 1
    rugs = props_of(layout, "prayer_rug")
    assert len(rugs) == 8
    assert len({z for _, z in rugs}) == 2  # 2 rows
    assert len(props_of(layout, "shoe_shelf")) == 1
    assert len(props_of(layout, "admin_desk")) == 5
    assert len([s for s in layout.seats if s.kind == "desk"]) == 5
    assert len([s for s in layout.spots if s.kind == "prayer"]) == 8


def test_roof_and_outside(layout: Layout) -> None:
    roof = layout.roof
    assert (roof.helipad_x, roof.helipad_z, roof.helipad_size) == (6, 0, 12)
    assert (roof.helicopter_x, roof.helicopter_z) == (6, 0)
    assert len(props_of(layout, "hvac")) >= 1
    assert len(props_of(layout, "elevator_machine_room")) == 1
    bay = layout.outside.ambulance_bay
    assert ((bay.x1 + bay.x2) / 2, (bay.z1 + bay.z2) / 2) == (14, 20)
    assert layout.outside.street_z == 28
    assert len(layout.outside.ambulance_slots) == 4  # 4 ambulances per hospital (§5.2)
    for slot in layout.outside.ambulance_slots:
        assert bay.contains(slot.x, slot.z)


def test_three_hospitals_in_phoenix(layout: Layout) -> None:
    assert [h.name for h in layout.hospitals] == ["Mercy General", "St. Luke's", "Desert Valley"]
    for hospital in layout.hospitals:
        assert 33.2 < hospital.lat < 33.8
        assert -112.4 < hospital.lon < -111.8
    assert [h.id for h in layout.hospitals if h.helipad] == ["mercy"]


def test_all_ids_are_ascii_and_unique(layout: Layout) -> None:
    """§10.5 pitfall: ids that cross a file boundary must be plain ASCII."""
    groups = {
        "room": list(layout.rooms),
        "door": [d.id for d in layout.doors],
        "bed": [b.id for b in layout.beds],
        "seat/spot": [s.id for s in layout.seats] + [s.id for s in layout.spots],
        "prop": [p.id for p in layout.props],
        "node": [n.id for n in layout.graph.nodes],
        "hospital": [h.id for h in layout.hospitals],
    }
    pattern = re.compile(r"^[A-Za-z0-9_-]+$")
    for group, ids in groups.items():
        assert len(ids) == len(set(ids)), f"duplicate {group} ids"
        for value in ids:
            assert pattern.match(value), f"{group} id {value!r} is not plain ASCII"


def test_committed_file_is_exactly_what_the_generator_produces() -> None:
    assert LAYOUT_PATH.read_text(encoding="utf-8") == build_layout.render(build_layout.build_layout())


def test_cli_writes_and_checks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "out" / "layout.json"
    assert build_layout.main(["--check", "--path", str(target)]) == 1
    assert build_layout.main(["--path", str(target)]) == 0
    assert load_layout(target) == load_layout()
    assert build_layout.main(["--check", "--path", str(target)]) == 0
    target.write_text("{}", encoding="utf-8")
    assert build_layout.main(["--check", "--path", str(target)]) == 1
    assert "out of date" in capsys.readouterr().err
