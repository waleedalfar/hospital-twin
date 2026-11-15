"""A* routes and the elevator (PROMPT.md §5.5)."""

import math

import pytest

from twin.sim.config import WALK_SPEED_M_PER_MIN
from twin.sim.layout_model import load_layout
from twin.sim.pathing import ElevatorSchedule, NoRouteError, Router, ride_minutes, stream, timeline


@pytest.fixture(scope="module")
def router() -> Router:
    return Router(load_layout())


def length(router: Router, path: list[str]) -> float:
    layout = load_layout()
    return sum(
        math.hypot(layout.nodes[a].x - layout.nodes[b].x, layout.nodes[a].z - layout.nodes[b].z)
        for a, b in zip(path, path[1:], strict=False)
        if layout.nodes[a].floor == layout.nodes[b].floor
    )


def test_path_between_two_rooms_on_one_floor(router: Router) -> None:
    layout = load_layout()
    path = router.path(layout.spots_by_id["ICU-ws-1"].node, layout.spots_by_id["LAB-ws-1"].node)
    assert path[0] == layout.spots_by_id["ICU-ws-1"].node
    assert path[-1] == layout.spots_by_id["LAB-ws-1"].node
    assert {layout.nodes[n].floor for n in path} == {2}
    assert any(layout.nodes[n].room == "CORR-2" for n in path)


def test_path_is_shortest(router: Router) -> None:
    """Compare with a brute-force shortest path (Dijkstra) over the same graph."""
    import heapq

    layout = load_layout()
    adj: dict[str, list[tuple[str, float]]] = {n.id: [] for n in layout.graph.nodes}
    for e in layout.graph.edges:
        adj[e.a].append((e.b, e.length))
        adj[e.b].append((e.a, e.length))
    src, dst = layout.spots_by_id["ER-ws-7"].node, layout.spots_by_id["PHARMACY-ws-3"].node
    dist = {src: 0.0}
    heap = [(0.0, src)]
    while heap:
        d, n = heapq.heappop(heap)
        if d > dist[n]:
            continue
        for m, w in adj[n]:
            if d + w < dist.get(m, 1e9):
                dist[m] = d + w
                heapq.heappush(heap, (d + w, m))
    path = router.path(src, dst)
    total = sum(next(e.length for e in layout.graph.edges if {e.a, e.b} == {a, b}) for a, b in zip(path, path[1:], strict=False))
    assert total == pytest.approx(dist[dst], abs=1e-6)


def test_path_to_self_and_caching(router: Router) -> None:
    assert router.path("f0-ELEV", "f0-ELEV") == ["f0-ELEV"]
    a = router.path("f0-ELEV", "f2-ELEV")
    assert router.path("f0-ELEV", "f2-ELEV") is a


def test_floor_change_goes_through_the_elevator(router: Router) -> None:
    layout = load_layout()
    path = router.path(layout.spots_by_id["CURB"].node, layout.spots_by_id["ICU-ws-3"].node)
    floors = [layout.nodes[n].floor for n in path]
    assert floors[0] == 0 and floors[-1] == 2
    for a, b in zip(path, path[1:], strict=False):
        if layout.nodes[a].floor != layout.nodes[b].floor:
            assert a.endswith("ELEV") and b.endswith("ELEV")


def test_no_route_error() -> None:
    from twin.sim.layout_model import Layout

    layout = load_layout()
    broken = Layout.model_validate({**layout.model_dump(), "graph": {"nodes": layout.model_dump()["graph"]["nodes"], "edges": []}})
    with pytest.raises(NoRouteError):
        Router(broken).path("f0-ELEV", "f1-ELEV")


def test_timeline_uses_walking_speed(router: Router) -> None:
    layout = load_layout()
    path = router.path(layout.spots_by_id["ICU-ws-1"].node, layout.spots_by_id["ICU-ws-6"].node)
    nodes, times = timeline(router, path, 100.0, ElevatorSchedule())
    assert nodes == path
    assert times[0] == 100.0
    assert times[-1] - times[0] == pytest.approx(length(router, path) / WALK_SPEED_M_PER_MIN)
    assert times == sorted(times)


def test_elevator_ride_takes_time_and_busy_car_makes_walkers_wait(router: Router) -> None:
    elevator = ElevatorSchedule()
    layout = load_layout()
    path = router.path(layout.spots_by_id["CURB"].node, layout.spots_by_id["ICU-ws-3"].node)
    _, first = timeline(router, path, 0.0, elevator)
    nodes2, second = timeline(router, path, 0.0, elevator)  # leaves at the same time: must wait for the car
    assert second[-1] > first[-1]
    assert len(nodes2) > len(path) - 1
    assert ride_minutes(2) > ride_minutes(1) > 0


def test_elevator_booking_never_overlaps() -> None:
    elevator = ElevatorSchedule()
    starts = [elevator.book(0.0, 0.5) for _ in range(5)]
    assert starts == sorted(starts)
    assert all(b - a >= 0.5 - 1e-9 for a, b in zip(starts, starts[1:], strict=False))
    assert elevator.book(100.0, 0.5) == 100.0


def test_streams_are_reproducible_and_independent() -> None:
    assert stream(1, "a").random() == stream(1, "a").random()
    assert stream(1, "a").random() != stream(1, "b").random()
    assert stream(1, "a").random() != stream(2, "a").random()
