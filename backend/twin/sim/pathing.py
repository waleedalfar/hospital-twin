"""Walking routes: A* over the layout's waypoint graph, timed at walking speed, with the elevator for floor
changes (PROMPT.md §5.5)."""

import hashlib
import heapq
import math
import random
from dataclasses import dataclass, field

from twin.sim.config import ELEVATOR_DOOR_S, ELEVATOR_S_PER_FLOOR, WALK_SPEED_M_PER_MIN
from twin.sim.layout_model import Layout


class NoRouteError(Exception):
    """Two waypoints are not connected."""


def stream(seed: int, *names: str) -> random.Random:
    """An independent random stream for one purpose. The same seed and names always give the same stream,
    on every machine (Python's own hash() is salted per process, so it is not used)."""
    digest = hashlib.sha256(f"{seed}|{'|'.join(names)}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class Router:
    def __init__(self, layout: Layout) -> None:
        self._layout = layout
        self._floor_height = layout.building.floor_height
        self._adjacent: dict[str, list[tuple[str, float, str]]] = {n.id: [] for n in layout.graph.nodes}
        for edge in layout.graph.edges:
            self._adjacent[edge.a].append((edge.b, edge.length, edge.kind))
            self._adjacent[edge.b].append((edge.a, edge.length, edge.kind))
        for neighbours in self._adjacent.values():
            neighbours.sort()
        self._cache: dict[tuple[str, str], list[str]] = {}

    def _heuristic(self, a: str, b: str) -> float:
        na, nb = self._layout.nodes[a], self._layout.nodes[b]
        return math.hypot(na.x - nb.x, na.z - nb.z) + abs(na.floor - nb.floor) * self._floor_height

    def path(self, start: str, goal: str) -> list[str]:
        """Shortest path from `start` to `goal` as a list of node ids, both ends included."""
        key = (start, goal)
        if key in self._cache:
            return self._cache[key]
        if start == goal:
            return [start]
        best: dict[str, float] = {start: 0.0}
        came: dict[str, str] = {}
        frontier: list[tuple[float, str]] = [(self._heuristic(start, goal), start)]
        while frontier:
            _, node = heapq.heappop(frontier)
            if node == goal:
                route = [goal]
                while route[-1] != start:
                    route.append(came[route[-1]])
                route.reverse()
                self._cache[key] = route
                return route
            for nxt, length, _ in self._adjacent[node]:
                cost = best[node] + length
                if cost < best.get(nxt, math.inf):
                    best[nxt] = cost
                    came[nxt] = node
                    heapq.heappush(frontier, (cost + self._heuristic(nxt, goal), nxt))
        raise NoRouteError(f"No route from {start} to {goal}")

    def is_elevator_hop(self, a: str, b: str) -> bool:
        return self._layout.nodes[a].floor != self._layout.nodes[b].floor

    def walk_minutes(self, a: str, b: str) -> float:
        na, nb = self._layout.nodes[a], self._layout.nodes[b]
        return math.hypot(na.x - nb.x, na.z - nb.z) / WALK_SPEED_M_PER_MIN


@dataclass
class ElevatorSchedule:
    """One car per building. Rides are booked so that two rides never overlap; a walker who reaches the
    door while the car is busy waits for it."""

    busy: list[tuple[float, float]] = field(default_factory=list)

    def book(self, ready: float, duration: float) -> float:
        """Reserve the car for `duration` minutes at the first free moment at or after `ready`; return the
        start time of the ride."""
        start = ready
        for a, b in sorted(self.busy):
            if start + duration <= a:
                break
            if b > start:
                start = b
        self.busy.append((start, start + duration))
        horizon = start - 120.0
        self.busy = [(a, b) for a, b in self.busy if b > horizon]
        return start


def ride_minutes(floors: int) -> float:
    return (ELEVATOR_DOOR_S + ELEVATOR_S_PER_FLOOR * floors) / 60.0


def timeline(router: Router, path: list[str], depart: float, elevator: ElevatorSchedule) -> tuple[list[str], list[float]]:
    """Times at which a walker who leaves at `depart` reaches each node of `path`. A run of floor changes is
    one elevator ride; if the car is busy the walker waits at the door, which shows as the door node
    repeated with a later time."""
    nodes = [path[0]]
    times = [depart]
    now = depart
    i = 1
    while i < len(path):
        prev, cur = path[i - 1], path[i]
        if router.is_elevator_hop(prev, cur):
            j = i
            while j + 1 < len(path) and router.is_elevator_hop(path[j], path[j + 1]):
                j += 1
            start = elevator.book(now, ride_minutes(j - i + 1))
            if start > now:
                nodes.append(prev)
                times.append(start)
            now = start + ride_minutes(j - i + 1)
            nodes.append(path[j])
            times.append(now)
            i = j + 1
            continue
        now += router.walk_minutes(prev, cur)
        nodes.append(cur)
        times.append(now)
        i += 1
    return nodes, times
