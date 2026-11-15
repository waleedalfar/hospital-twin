"""The waypoint graph in `shared/layout.json`: reachable, inside the rooms, and never through a wall,
a bed or furniture."""

import math
from collections import deque

import pytest

from twin.sim.layout_graph import GraphBuilder, LayoutGraphError
from twin.sim.layout_model import Layout, Node, Rect, load_layout

BED_HALF_WIDTH = 0.55
BED_HALF_LENGTH = 1.05
EPS = 1e-6


@pytest.fixture(scope="module")
def layout() -> Layout:
    return load_layout()


def neighbours(layout: Layout, kinds: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {node.id: set() for node in layout.graph.nodes}
    for edge in layout.graph.edges:
        if edge.kind in kinds:
            result[edge.a].add(edge.b)
            result[edge.b].add(edge.a)
    return result


def reachable(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        for nxt in adjacency[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def segment_hits_rect(a: Node, b: Node, rect: Rect) -> bool:
    """True if the segment a-b passes through the inside of `rect` (Liang-Barsky clipping)."""
    t0, t1 = 0.0, 1.0
    dx, dz = b.x - a.x, b.z - a.z
    for p, q in ((-dx, a.x - rect.x1), (dx, rect.x2 - a.x), (-dz, a.z - rect.z1), (dz, rect.z2 - a.z)):
        if abs(p) < EPS:
            if q <= EPS:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return t1 - t0 > EPS


def test_graph_is_connected(layout: Layout) -> None:
    adjacency = neighbours(layout, {"walk", "door", "elevator"})
    start = layout.graph.nodes[0].id
    assert reachable(start, adjacency) == set(adjacency)


def test_each_floor_is_connected_without_the_elevator(layout: Layout) -> None:
    adjacency = neighbours(layout, {"walk", "door"})
    for floor in range(4):
        ids = {node.id for node in layout.graph.nodes if node.floor == floor}
        assert reachable(next(iter(sorted(ids))), adjacency) == ids, f"floor {floor}"


def test_floors_are_joined_only_by_elevator_edges(layout: Layout) -> None:
    elevator_edges = [e for e in layout.graph.edges if e.kind == "elevator"]
    assert len(elevator_edges) == 3  # ground-1, 1-2, 2-roof
    for edge in layout.graph.edges:
        a, b = layout.nodes[edge.a], layout.nodes[edge.b]
        if edge.kind == "elevator":
            assert abs(a.floor - b.floor) == 1
            assert (a.x, a.z) == (b.x, b.z) == (18.5, 0)
            assert edge.length == layout.building.floor_height
        else:
            assert a.floor == b.floor


def test_edge_lengths_match_node_positions(layout: Layout) -> None:
    for edge in layout.graph.edges:
        if edge.kind == "elevator":
            continue
        a, b = layout.nodes[edge.a], layout.nodes[edge.b]
        assert edge.length == pytest.approx(math.hypot(a.x - b.x, a.z - b.z), abs=1e-3)
        assert edge.length > 0


def test_every_node_is_inside_its_room(layout: Layout) -> None:
    for node in layout.graph.nodes:
        room = layout.rooms[node.room]
        assert room.floor == node.floor, node.id
        assert room.rect.contains(node.x, node.z, margin=EPS), node.id


def test_every_bed_seat_and_spot_has_a_node_at_its_position(layout: Layout) -> None:
    for bed in layout.beds:
        spot = layout.spots_by_id[bed.spot]
        assert spot.bed == bed.id
        assert spot.kind == "bedside"
        assert 0.9 <= math.hypot(spot.x - bed.x, spot.z - bed.z) <= 1.1
    targets = [(s.id, s.node, s.x, s.z, s.floor, s.room) for s in layout.seats]
    targets += [(s.id, s.node, s.x, s.z, s.floor, s.room) for s in layout.spots]
    for target_id, node_id, x, z, floor, room in targets:
        node = layout.nodes[node_id]
        assert (node.x, node.z, node.floor, node.room) == (x, z, floor, room), target_id
    for door in layout.doors:
        node = layout.nodes[door.node]
        along, across = (node.x, node.z) if door.axis == "x" else (node.z, node.x)
        assert across == door.at
        assert door.start < along < door.end


def test_no_edge_passes_through_a_wall(layout: Layout) -> None:
    """An edge may cross a room boundary only inside a door gap on that wall."""
    for edge in layout.graph.edges:
        a, b = layout.nodes[edge.a], layout.nodes[edge.b]
        if edge.kind == "elevator":
            continue
        for room in layout.rooms.values():
            if room.floor != a.floor or room.kind in ("outside", "roof"):
                continue
            r = room.rect
            walls = (
                ("x", r.z1, r.x1, r.x2),
                ("x", r.z2, r.x1, r.x2),
                ("z", r.x1, r.z1, r.z2),
                ("z", r.x2, r.z1, r.z2),
            )
            for axis, at, lo, hi in walls:
                a_across, b_across = (a.z, b.z) if axis == "x" else (a.x, b.x)
                a_along, b_along = (a.x, b.x) if axis == "x" else (a.z, b.z)
                if (a_across - at) * (b_across - at) > 0 or abs(a_across - b_across) < EPS:
                    continue  # both ends on one side, or the edge runs along the wall line
                where = a_along + (b_along - a_along) * (at - a_across) / (b_across - a_across)
                if not lo - EPS <= where <= hi + EPS:
                    continue
                gaps = [d for d in layout.doors if d.floor == a.floor and d.axis == axis and d.at == at]
                assert any(d.start < where < d.end for d in gaps), f"edge {edge.a} - {edge.b} crosses the wall of {room.id} at {axis}={where:.2f}"


def test_no_edge_passes_through_furniture_or_beds(layout: Layout) -> None:
    obstacles = [(p.id, p.floor, p.footprint) for p in layout.props if p.blocks]
    for bed in layout.beds:
        footprint = Rect(
            x1=bed.x - BED_HALF_WIDTH,
            x2=bed.x + BED_HALF_WIDTH,
            z1=bed.z - BED_HALF_LENGTH,
            z2=bed.z + BED_HALF_LENGTH,
        )
        obstacles.append((bed.id, bed.floor, footprint))
    for edge in layout.graph.edges:
        a, b = layout.nodes[edge.a], layout.nodes[edge.b]
        if edge.kind == "elevator":
            continue
        for obstacle_id, floor, footprint in obstacles:
            if floor != a.floor:
                continue
            # A seat is on its chair or couch, and a table spot is on its table: those ends are allowed.
            if footprint.contains(a.x, a.z) or footprint.contains(b.x, b.z):
                continue
            assert not segment_hits_rect(a, b, footprint), f"edge {edge.a} - {edge.b} passes through {obstacle_id}"


def test_segment_helper_detects_crossings() -> None:
    box = Rect(x1=0, x2=2, z1=0, z2=2)

    def node(x: float, z: float) -> Node:
        return Node(id="n", floor=0, x=x, z=z, room="r")

    assert segment_hits_rect(node(-1, 1), node(3, 1), box)
    assert segment_hits_rect(node(-1, -1), node(3, 3), box)
    assert not segment_hits_rect(node(-1, 3), node(3, 3), box)
    assert not segment_hits_rect(node(-1, 0), node(3, 0), box)  # along the edge only
    assert not segment_hits_rect(node(-2, 1), node(-1, 1), box)


def test_spec_example_ids_exist(layout: Layout) -> None:
    """PROMPT.md §6.1 uses these in its example messages."""
    assert "ICU-ws-2" in layout.spots_by_id
    assert layout.spots_by_id["ICU-ws-2"].bed == "ICU-2"
    assert "ICU-3" in layout.beds_by_id
    assert any(node.id.startswith("f2-c-") for node in layout.graph.nodes)


def test_builder_rejects_bad_graphs() -> None:
    g = GraphBuilder()
    g.add_lane("A", 0, 0, 0.0, "f0-A")
    with pytest.raises(LayoutGraphError, match="no lane"):
        g.lane("A", 1, 0.0)
    g.node("n1", 0, 1.0, 1.0, "A")
    with pytest.raises(LayoutGraphError, match="Duplicate node id"):
        g.node("n1", 0, 2.0, 2.0, "A")

    same_place = GraphBuilder()
    same_place.node("a", 0, 1.0, 1.0, "A")
    same_place.node("b", 0, 1.0, 1.0, "A")
    with pytest.raises(LayoutGraphError, match="same position"):
        same_place.build(3.4)

    loop = GraphBuilder()
    loop.node("a", 0, 1.0, 1.0, "A")
    loop.connect("a", "a")
    with pytest.raises(LayoutGraphError, match="itself"):
        loop.build(3.4)

    stairs = GraphBuilder()
    stairs.node("a", 0, 1.0, 1.0, "A")
    stairs.node("b", 1, 1.0, 1.0, "A")
    stairs.connect("a", "b")
    with pytest.raises(LayoutGraphError, match="changes floor"):
        stairs.build(3.4)

    unknown = GraphBuilder()
    unknown.node("a", 0, 1.0, 1.0, "A")
    unknown.connect("a", "missing")
    with pytest.raises(LayoutGraphError, match="Unknown node"):
        unknown.build(3.4)

    clash = GraphBuilder()
    clash.add_lane("A", 0, 0, 0.0, "f0-A")
    clash.lane("A", 0, 1.0)
    clash.node("f0-A-1", 0, 5.0, 5.0, "A")
    with pytest.raises(LayoutGraphError, match="Duplicate node id"):
        clash.build(3.4)
