"""Builds the waypoint graph. People walk along east-west lanes inside rooms and corridors; doors, beds,
seats and work spots hang off the lanes. Floors are joined only by the elevator."""

import math
from dataclasses import dataclass

from twin.sim.layout_model import Edge, Graph, Node


@dataclass(frozen=True)
class LanePoint:
    """A point at `x` on lane number `lane` of `room`. It becomes a named node when the graph is built."""

    room: str
    lane: int
    x: float


Ref = LanePoint | str


class LayoutGraphError(Exception):
    """The layout tables describe a graph that cannot be built."""


class GraphBuilder:
    def __init__(self) -> None:
        self._lanes: dict[tuple[str, int], tuple[int, float, str]] = {}
        self._lane_xs: dict[tuple[str, int], set[float]] = {}
        self._fixed: dict[str, Node] = {}
        self._pending: list[tuple[Ref, Ref, str]] = []

    def add_lane(self, room: str, lane: int, floor: int, z: float, prefix: str) -> None:
        """Declare a lane. Its nodes will be named `<prefix>-<n>`, numbered from west to east."""
        self._lanes[(room, lane)] = (floor, z, prefix)
        self._lane_xs[(room, lane)] = set()

    def lane(self, room: str, lane: int, x: float) -> LanePoint:
        if (room, lane) not in self._lanes:
            raise LayoutGraphError(f"Room {room} has no lane {lane}")
        x = round(x, 3)
        self._lane_xs[(room, lane)].add(x)
        return LanePoint(room, lane, x)

    def node(self, node_id: str, floor: int, x: float, z: float, room: str) -> str:
        if node_id in self._fixed:
            raise LayoutGraphError(f"Duplicate node id {node_id}")
        self._fixed[node_id] = Node(id=node_id, floor=floor, x=round(x, 3), z=round(z, 3), room=room)
        return node_id

    def connect(self, a: Ref, b: Ref, kind: str = "walk") -> None:
        self._pending.append((a, b, kind))

    def build(self, floor_height: float) -> Graph:
        nodes: dict[str, Node] = dict(self._fixed)
        lane_ids: dict[LanePoint, str] = {}
        edges: dict[tuple[str, str], Edge] = {}

        def add_edge(a: str, b: str, kind: str) -> None:
            if a == b:
                raise LayoutGraphError(f"Edge from {a} to itself")
            na, nb = nodes[a], nodes[b]
            if kind == "elevator":
                length = floor_height
            elif na.floor != nb.floor:
                raise LayoutGraphError(f"Edge {a} - {b} changes floor but is not an elevator edge")
            else:
                length = math.hypot(na.x - nb.x, na.z - nb.z)
            key = (a, b) if a < b else (b, a)
            edges[key] = Edge.model_validate(
                {"a": key[0], "b": key[1], "kind": kind, "length": round(length, 3)}
            )

        for (room, lane), xs in sorted(self._lane_xs.items()):
            floor, z, prefix = self._lanes[(room, lane)]
            previous: str | None = None
            for index, x in enumerate(sorted(xs), start=1):
                node_id = f"{prefix}-{index}"
                if node_id in nodes:
                    raise LayoutGraphError(f"Duplicate node id {node_id}")
                nodes[node_id] = Node(id=node_id, floor=floor, x=x, z=z, room=room)
                lane_ids[LanePoint(room, lane, x)] = node_id
                if previous is not None:
                    add_edge(previous, node_id, "walk")
                previous = node_id

        def resolve(ref: Ref) -> str:
            node_id = lane_ids[ref] if isinstance(ref, LanePoint) else ref
            if node_id not in nodes:
                raise LayoutGraphError(f"Unknown node {node_id}")
            return node_id

        for a, b, kind in self._pending:
            add_edge(resolve(a), resolve(b), kind)

        positions: dict[tuple[int, float, float], str] = {}
        for node in nodes.values():
            key = (node.floor, node.x, node.z)
            if key in positions:
                raise LayoutGraphError(f"Nodes {positions[key]} and {node.id} are at the same position")
            positions[key] = node.id

        return Graph(
            nodes=sorted(nodes.values(), key=lambda n: (n.floor, n.id)),
            edges=[edges[key] for key in sorted(edges)],
        )
