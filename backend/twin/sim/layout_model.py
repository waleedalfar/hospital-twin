"""Typed model of `shared/layout.json`, the single source of truth for the building (PROMPT.md §3).

Axes: +x east, +z south (street side), y up. Units are meters. `rotation` is radians about y, as three.js
uses it: 0 faces +z (south), pi faces north.
"""

import json
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from twin.common.config import REPO_ROOT

LAYOUT_PATH = REPO_ROOT / "shared" / "layout.json"
LAYOUT_VERSION = 1

Facing = Literal["north", "south", "east", "west"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rect(Model):
    x1: float
    x2: float
    z1: float
    z2: float

    def contains(self, x: float, z: float, margin: float = 0.0) -> bool:
        return self.x1 - margin <= x <= self.x2 + margin and self.z1 - margin <= z <= self.z2 + margin


class Building(Model):
    footprint: Rect
    levels: int
    floor_height: float
    slab: float
    wall_height: float
    corridor: Rect
    stairs: Rect
    elevator: Rect


class Hospital(Model):
    id: str
    name: str
    lat: float
    lon: float
    helipad: bool


class Unit(Model):
    id: str
    name: str
    clinical: bool
    capacity: int


class Room(Model):
    id: str
    name: str
    floor: int
    unit: str
    kind: Literal["room", "corridor", "elevator", "outside", "roof"]
    rect: Rect
    color: str
    label_x: float
    label_z: float


class Door(Model):
    """A gap in a wall. The wall runs along `axis` at coordinate `at`; the gap spans `start`..`end`."""

    id: str
    floor: int
    rooms: tuple[str, str]
    wall: str
    axis: Literal["x", "z"]
    at: float
    start: float
    end: float
    kind: Literal["door", "opening", "entrance", "elevator"]
    node: str


class Floor(Model):
    level: int
    name: str
    rooms: list[Room]
    doors: list[Door]


class Bed(Model):
    id: str
    room: str
    floor: int
    unit: str
    x: float
    z: float
    rotation: float
    head: Facing
    spot: str


class Seat(Model):
    id: str
    room: str
    floor: int
    kind: Literal["waiting", "triage", "lounge", "desk"]
    x: float
    z: float
    facing: Facing
    rotation: float
    node: str


class Spot(Model):
    """A place where a person stands, works, prays or (for tables) lies."""

    id: str
    room: str
    floor: int
    kind: Literal["bedside", "station", "table", "prayer", "standing", "helipad", "unload", "curb"]
    x: float
    z: float
    facing: Facing
    rotation: float
    bed: str | None = None
    node: str


class Prop(Model):
    """Furniture and fixtures. `w` is the size along x and `d` along z, before rotation."""

    id: str
    type: str
    room: str
    floor: int
    x: float
    z: float
    w: float
    d: float
    rotation: float = 0.0
    blocks: bool = True
    target: str | None = None

    @property
    def footprint(self) -> Rect:
        return Rect(x1=self.x - self.w / 2, x2=self.x + self.w / 2, z1=self.z - self.d / 2, z2=self.z + self.d / 2)


class AmbulanceSlot(Model):
    id: str
    x: float
    z: float
    rotation: float
    spot: str


class Outside(Model):
    ambulance_bay: Rect
    ambulance_slots: list[AmbulanceSlot]
    street_z: float
    street_width: float
    entrance_node: str
    curb_spot: str


class Roof(Model):
    level: int
    helipad_x: float
    helipad_z: float
    helipad_size: float
    helicopter_x: float
    helicopter_z: float
    helipad_spot: str


class Node(Model):
    id: str
    floor: int
    x: float
    z: float
    room: str


class Edge(Model):
    a: str
    b: str
    kind: Literal["walk", "door", "elevator"]
    length: float


class Graph(Model):
    nodes: list[Node]
    edges: list[Edge]


class Layout(Model):
    version: int
    units: Literal["meters"]
    building: Building
    hospitals: list[Hospital]
    care_units: list[Unit]
    floors: list[Floor]
    beds: list[Bed]
    seats: list[Seat]
    spots: list[Spot]
    props: list[Prop]
    outside: Outside
    roof: Roof
    graph: Graph

    @cached_property
    def rooms(self) -> dict[str, Room]:
        return {room.id: room for floor in self.floors for room in floor.rooms}

    @cached_property
    def doors(self) -> list[Door]:
        return [door for floor in self.floors for door in floor.doors]

    @cached_property
    def nodes(self) -> dict[str, Node]:
        return {node.id: node for node in self.graph.nodes}

    @cached_property
    def beds_by_id(self) -> dict[str, Bed]:
        return {bed.id: bed for bed in self.beds}

    @cached_property
    def spots_by_id(self) -> dict[str, Spot]:
        return {spot.id: spot for spot in self.spots}

    @cached_property
    def seats_by_id(self) -> dict[str, Seat]:
        return {seat.id: seat for seat in self.seats}

    @cached_property
    def capacity(self) -> dict[str, int]:
        return {unit.id: unit.capacity for unit in self.care_units}


def load_layout(path: Path = LAYOUT_PATH) -> Layout:
    """Read and validate the layout file."""
    return Layout.model_validate(json.loads(path.read_text(encoding="utf-8")))
