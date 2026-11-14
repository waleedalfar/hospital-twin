"""The building tables from PROMPT.md §3, as data. `build_layout.py` turns them into `shared/layout.json`.

Positions that §3 does not give (work spots, furniture sizes, walking lanes) follow the prototype
`reference/engine/pulse3d.js`, so the generated layout matches the approved look.
"""

from dataclasses import dataclass

from twin.sim.layout_model import Facing

FOOTPRINT = (-20.0, 20.0, -14.0, 14.0)
LEVELS = 3
FLOOR_HEIGHT = 3.4
SLAB = 0.3
WALL_HEIGHT = 3.0
CORRIDOR = (-20.0, 17.0, -2.0, 2.0)
STAIRS = (-20.0, -17.0, -2.0, 2.0)
ELEVATOR = (17.0, 20.0, -2.0, 2.0)
ROOF_LEVEL = 3
FLOOR_NAMES = ("Ground", "Wards", "Critical care and support", "Roof")

# Fictional hospitals placed at Phoenix coordinates (PROMPT.md §5.2).
HOSPITALS = (
    ("mercy", "Mercy General", 33.4484, -112.0740, True),
    ("stlukes", "St. Luke's", 33.5106, -112.0296, False),
    ("desert", "Desert Valley", 33.3942, -112.1513, False),
)

# (id, name, clinical). Capacity is counted from the generated beds, seats and tables.
UNITS = (
    ("ER", "Emergency", True),
    ("WARD", "Ward", True),
    ("REC", "Recovery", True),
    ("ICU", "Intensive care", True),
    ("OR", "Surgery", True),
    ("TRIAGE", "Triage", True),
    ("WAITING", "Waiting", False),
    ("IMAGING", "Imaging", False),
    ("PHARMACY", "Pharmacy", False),
    ("RECEPTION", "Reception", False),
    ("LAB", "Lab", False),
    ("STAFF", "Staff lounge", False),
    ("PRAYER", "Prayer room", False),
    ("ADMIN", "Admin", False),
    ("CORRIDOR", "Corridor", False),
    ("ELEVATOR", "Elevator", False),
    ("OUTSIDE", "Outside", False),
    ("ROOF", "Roof", False),
)


@dataclass(frozen=True)
class RoomDef:
    id: str
    name: str
    floor: int
    unit: str
    rect: tuple[float, float, float, float]
    color: str
    doors: tuple[tuple[float, float], ...]
    label: tuple[float, float]
    # Walking lanes: east-west lines (z values) that people walk along inside the room. Lane 0 is the one
    # the corridor doors lead to. `links` join two lanes at an x position: (x, lane a, lane b).
    lanes: tuple[float, ...]
    links: tuple[tuple[float, int, int], ...] = ()


ROOMS = (
    # Floor 0 - Ground
    RoomDef("ER", "ER", 0, "ER", (-20, -4, -14, -2), "ER", ((-13, -10),), (-12, -8), (-9.6,)),
    RoomDef("IMAGING", "Imaging", 0, "IMAGING", (-4, 8, -14, -2), "IMG", ((0, 3),), (2, -8), (-4.5,)),
    RoomDef(
        "PHARMACY", "Pharmacy", 0, "PHARMACY", (8, 20, -14, -2), "PHARM", ((12, 14.5),), (14, -8), (-5.0,)
    ),
    RoomDef("TRIAGE", "Triage", 0, "TRIAGE", (-20, -4, 2, 14), "TRIAGE", ((-13, -10),), (-12, 8), (3.6,)),
    RoomDef(
        "WAITING",
        "Waiting",
        0,
        "WAITING",
        (-4, 8, 2, 14),
        "WAIT",
        ((-2, 4),),
        (2, 8),
        (4.4, 8.5),
        ((-3.4, 0, 1),),
    ),
    RoomDef(
        "RECEPTION",
        "Reception",
        0,
        "RECEPTION",
        (8, 20, 2, 14),
        "RECEP",
        ((10, 13),),
        (14, 8),
        (4.5, 7.0),
        ((14.0, 0, 1),),
    ),
    # Floor 1 - Wards
    RoomDef(
        "WARD_A", "Ward A", 1, "WARD", (-20, 6, -14, -2), "WARD", ((-14, -11), (-1, 2)), (-7, -8), (-9.6,)
    ),
    RoomDef("OR", "Surgery (OR-1)", 1, "OR", (6, 20, -14, -2), "OR", ((10, 13),), (13, -8), (-4.5,)),
    RoomDef("WARD_B", "Ward B", 1, "WARD", (-20, 6, 2, 14), "WARD", ((-14, -11), (-1, 2)), (-7, 8), (9.6,)),
    RoomDef("RECOVERY", "Recovery", 1, "REC", (6, 20, 2, 14), "RECOV", ((10, 13),), (13, 8), (9.6,)),
    # Floor 2 - Critical care and support
    RoomDef("ICU", "ICU", 2, "ICU", (-20, 6, -14, -2), "ICU", ((-14, -11), (-1, 2)), (-7, -8), (-9.6,)),
    RoomDef("LAB", "Lab", 2, "LAB", (6, 20, -14, -2), "LAB", ((10, 13),), (13, -8), (-4.2,)),
    RoomDef(
        "STAFF",
        "Staff lounge",
        2,
        "STAFF",
        (-20, -4, 2, 14),
        "STAFF",
        ((-13, -10),),
        (-12, 8),
        (5.0, 10.3),
        ((-14.5, 0, 1),),
    ),
    RoomDef(
        "PRAYER",
        "Prayer room",
        2,
        "PRAYER",
        (-4, 6, 2, 14),
        "PRAY",
        ((0, 3),),
        (1, 8),
        (3.8, 7.5),
        ((5.3, 0, 1),),
    ),
    RoomDef(
        "ADMIN",
        "Admin",
        2,
        "ADMIN",
        (6, 20, 2, 14),
        "ADMIN",
        ((10, 13),),
        (13, 8),
        (4.5, 9.2, 13.1),
        ((11.0, 0, 1), (15.5, 1, 2)),
    ),
)


@dataclass(frozen=True)
class BedRow:
    room: str
    prefix: str
    first: int
    count: int
    x0: float
    dx: float
    z: float
    head: Facing


BED_ROWS = (
    BedRow("ER", "ER", 1, 6, -18.0, 2.6, -12.4, "north"),
    BedRow("WARD_A", "WARD", 1, 8, -18.5, 2.9, -12.4, "north"),
    BedRow("WARD_B", "WARD", 9, 6, -18.5, 3.0, 12.4, "south"),
    BedRow("RECOVERY", "REC", 1, 3, 9.0, 3.5, 12.4, "south"),
    BedRow("ICU", "ICU", 1, 6, -18.5, 3.6, -12.4, "north"),
)
BED_WIDTH = 1.1
BED_LENGTH = 2.1
# Where a nurse stands at a bed: beside it, on the side away from the monitor, in bed-local coordinates.
BEDSIDE_OFFSET_X = -0.95
BEDSIDE_OFFSET_Z = 0.2


@dataclass(frozen=True)
class SeatDef:
    id: str
    room: str
    kind: str
    x: float
    z: float
    facing: Facing
    lane: int = 0
    chair: bool = True


@dataclass(frozen=True)
class SpotDef:
    id: str
    room: str
    kind: str
    x: float
    z: float
    facing: Facing
    lane: int = 0


@dataclass(frozen=True)
class PropDef:
    id: str
    type: str
    room: str
    x: float
    z: float
    w: float
    d: float
    blocks: bool = True


WAITING_SEATS = tuple(
    SeatDef(f"W-{row * 6 + k + 1}", "WAITING", "waiting", -2.5 + 1.7 * k, z, "north", lane=row)
    for row, z in enumerate((7.0, 10.0))
    for k in range(6)
)
ADMIN_DESKS = ((9.0, 7.0, 1), (13.0, 7.0, 1), (17.0, 7.0, 1), (9.0, 11.0, 2), (13.0, 11.0, 2))
PRAYER_RUGS = tuple((-2.6 + 2.2 * col, 6.0 + 3.0 * row, row) for row in range(2) for col in range(4))

SEATS = (
    *WAITING_SEATS,
    SeatDef("T-1", "TRIAGE", "triage", -16.0, 9.0, "north"),
    SeatDef("T-2", "TRIAGE", "triage", -14.5, 9.0, "north"),
    *(
        SeatDef(f"LOUNGE-{i + 1}", "STAFF", "lounge", x, 11.4, "north", lane=1, chair=False)
        for i, x in enumerate((-13.4, -12.47, -11.53, -10.6))
    ),
    *(
        SeatDef(f"ADMIN-{i + 1}", "ADMIN", "desk", x, z + 1.0, "north", lane=lane)
        for i, (x, z, lane) in enumerate(ADMIN_DESKS)
    ),
)

SPOTS = (
    SpotDef("ER-ws-7", "ER", "station", -8.0, -5.5, "north"),
    SpotDef("ER-ws-8", "ER", "station", -6.5, -5.5, "north"),
    SpotDef("IMAGING-table", "IMAGING", "table", 2.0, -8.2, "north"),
    SpotDef("IMAGING-ws-1", "IMAGING", "station", 3.2, -8.2, "west"),
    SpotDef("IMAGING-ws-2", "IMAGING", "station", -2.0, -6.0, "east"),
    SpotDef("PHARMACY-ws-1", "PHARMACY", "station", 12.3, -9.0, "west"),
    SpotDef("PHARMACY-ws-2", "PHARMACY", "station", 15.3, -9.0, "west"),
    SpotDef("PHARMACY-ws-3", "PHARMACY", "station", 18.3, -9.0, "west"),
    SpotDef("PHARMACY-ws-4", "PHARMACY", "station", 15.6, -3.6, "south"),
    SpotDef("TRIAGE-ws-1", "TRIAGE", "station", -12.0, 5.0, "south"),
    SpotDef("TRIAGE-ws-2", "TRIAGE", "station", -10.0, 8.0, "west"),
    SpotDef("WAITING-ws-1", "WAITING", "standing", -3.4, 12.0, "north", lane=1),
    SpotDef("WAITING-ws-2", "WAITING", "standing", 7.0, 12.0, "north", lane=1),
    SpotDef("RECEPTION-ws-1", "RECEPTION", "station", 19.2, 8.0, "west"),
    SpotDef("RECEPTION-ws-2", "RECEPTION", "standing", 16.9, 8.0, "east", lane=1),
    SpotDef("WARD_A-ws-9", "WARD_A", "station", -6.0, -5.0, "north"),
    SpotDef("WARD_A-ws-10", "WARD_A", "station", -4.5, -5.0, "north"),
    SpotDef("OR-1", "OR", "table", 13.0, -8.0, "north"),
    SpotDef("OR-ws-1", "OR", "station", 11.9, -8.0, "east"),
    SpotDef("OR-ws-2", "OR", "station", 14.1, -8.4, "west"),
    SpotDef("OR-ws-3", "OR", "station", 13.0, -6.3, "north"),
    SpotDef("OR-ws-4", "OR", "station", 16.5, -8.4, "north"),
    SpotDef("WARD_B-ws-7", "WARD_B", "station", -6.0, 5.0, "south"),
    SpotDef("WARD_B-ws-8", "WARD_B", "station", -4.5, 5.0, "south"),
    SpotDef("RECOVERY-ws-4", "RECOVERY", "station", 17.0, 5.0, "south"),
    SpotDef("ICU-ws-7", "ICU", "station", -6.0, -5.0, "north"),
    SpotDef("ICU-ws-8", "ICU", "station", -4.5, -5.0, "north"),
    *(
        SpotDef(f"LAB-ws-{i + 1}", "LAB", "station", x, -5.0, "north")
        for i, x in enumerate((8.5, 11.0, 13.5, 16.0))
    ),
    SpotDef("STAFF-ws-1", "STAFF", "standing", -18.0, 11.5, "south", lane=1),
    SpotDef("STAFF-ws-2", "STAFF", "standing", -12.0, 7.9, "south"),
    SpotDef("STAFF-ws-3", "STAFF", "standing", -9.5, 9.0, "west"),
    *(
        SpotDef(f"PRAYER-{i + 1}", "PRAYER", "prayer", x, z, "north", lane=row)
        for i, (x, z, row) in enumerate(PRAYER_RUGS)
    ),
)

PROPS = (
    *(PropDef(f"ER-curtain-{i + 1}", "curtain", "ER", -16.7 + 2.6 * i, -12.2, 0.05, 2.4) for i in range(5)),
    PropDef("IMAGING-scanner", "ct_scanner", "IMAGING", 2.0, -10.0, 2.8, 1.0),
    PropDef("IMAGING-ct-table", "ct_table", "IMAGING", 2.0, -8.2, 0.8, 3.2),
    *(
        PropDef(f"PHARMACY-shelf-{i + 1}", "shelf", "PHARMACY", x, -9.0, 1.0, 4.0)
        for i, x in enumerate((11.0, 14.0, 17.0))
    ),
    PropDef("TRIAGE-desk", "triage_desk", "TRIAGE", -12.0, 6.0, 3.0, 0.9),
    PropDef("RECEPTION-desk", "reception_desk", "RECEPTION", 18.0, 8.0, 1.0, 4.2),
    PropDef("RECEPTION-plant-1", "plant", "RECEPTION", 9.2, 13.0, 0.9, 0.9),
    PropDef("RECEPTION-plant-2", "plant", "RECEPTION", 9.2, 3.0, 0.9, 0.9),
    PropDef("OR-table", "or_table", "OR", 13.0, -8.0, 1.0, 2.4),
    PropDef("OR-lamp", "or_lamp", "OR", 13.0, -8.0, 1.4, 1.4, blocks=False),
    PropDef("OR-anesthesia", "anesthesia_machine", "OR", 16.5, -9.5, 0.8, 0.8),
    *(
        PropDef(f"ICU-glass-{i + 1}", "glass_partition", "ICU", -16.7 + 3.6 * i, -12.3, 0.06, 2.6)
        for i in range(5)
    ),
    PropDef("LAB-bench-1", "lab_bench", "LAB", 13.0, -9.0, 12.0, 1.0),
    PropDef("LAB-bench-2", "lab_bench", "LAB", 13.0, -6.0, 12.0, 1.0),
    PropDef("STAFF-couch", "couch", "STAFF", -12.0, 11.65, 4.0, 1.5),
    PropDef("STAFF-table", "coffee_table", "STAFF", -12.0, 9.0, 1.8, 1.0),
    PropDef("STAFF-vending", "vending_machine", "STAFF", -18.0, 12.8, 1.2, 0.8),
    *(
        PropDef(f"PRAYER-rug-{i + 1}", "prayer_rug", "PRAYER", x, z, 1.4, 2.4, blocks=False)
        for i, (x, z, _) in enumerate(PRAYER_RUGS)
    ),
    PropDef("PRAYER-shoe-shelf", "shoe_shelf", "PRAYER", 4.6, 12.8, 2.4, 0.5),
    *(
        PropDef(f"ADMIN-desk-{i + 1}", "admin_desk", "ADMIN", x, z, 2.2, 1.0)
        for i, (x, z, _) in enumerate(ADMIN_DESKS)
    ),
    *(
        PropDef(f"ROOF-hvac-{i + 1}", "hvac", "ROOF", x, z, 3.0, 2.0)
        for i, (x, z) in enumerate(((-14.0, -8.0), (-14.0, 6.0), (-8.0, -8.0)))
    ),
    PropDef("ROOF-machine-room", "elevator_machine_room", "ROOF", 18.5, 0.0, 3.0, 4.0),
    PropDef("ROOF-helipad", "helipad", "ROOF", 6.0, 0.0, 12.0, 12.0, blocks=False),
    PropDef("ROOF-helicopter", "helicopter", "ROOF", 6.0, 0.0, 2.0, 3.2),
)

# Ground-floor openings that are not corridor doors.
WAITING_OPENING = {"x": 8.0, "z1": 5.0, "z2": 9.0}
ENTRANCE = {"z": 14.0, "x1": 12.0, "x2": 16.0}
ELEVATOR_DOOR = {"x": 17.0, "z1": -1.0, "z2": 1.0}

# Outside (PROMPT.md §3): ambulance bay centered (14, 20); street along z = 28.
OUTSIDE_RECT = (-60.0, 60.0, 14.0, 32.0)
AMBULANCE_BAY = (7.0, 21.0, 15.5, 24.5)
AMBULANCE_SLOT_XS = (8.6, 11.4, 16.6, 19.4)
AMBULANCE_SLOT_Z = 20.6
UNLOAD_Z = 17.4
OUTSIDE_LANE_Z = 16.6
CURB = (14.0, 24.6)
STREET_Z = 28.0
STREET_WIDTH = 8.0

# Roof: helipad 12 x 12 centered (6, 0), helicopter parked on it.
HELIPAD = (6.0, 0.0, 12.0)
HELIPAD_SPOT = (9.2, 0.0)

CORRIDOR_WEST_X = -16.5
CORRIDOR_EAST_X = 16.0
ELEVATOR_X = 18.5
