"""Queues for scarce places: beds of a unit, triage seats, the operating table."""

import heapq
import itertools

import simpy


class SlotPool:
    """Hands out slot ids to requesters in priority order (lower first, then first come). A request is a
    SimPy event whose value is the slot id."""

    def __init__(self, env: simpy.Environment, slot_ids: list[str]) -> None:
        self._env = env
        self._order = {slot: i for i, slot in enumerate(slot_ids)}
        self._free: list[str] = list(slot_ids)
        self._waiting: list[tuple[float, int, simpy.Event]] = []
        self._seq = itertools.count()

    @property
    def free(self) -> list[str]:
        return list(self._free)

    @property
    def queue_length(self) -> int:
        return len(self._waiting)

    def request(self, priority: float) -> simpy.Event:
        event = self._env.event()
        if self._free and not self._waiting:
            event.succeed(self._free.pop(0))
        else:
            heapq.heappush(self._waiting, (priority, next(self._seq), event))
        return event

    def try_take(self, slot_id: str | None = None) -> str | None:
        """Take a free slot now (a specific one if given) without queueing. Returns None if not possible."""
        if slot_id is None:
            return self._free.pop(0) if self._free else None
        if slot_id in self._free:
            self._free.remove(slot_id)
            return slot_id
        return None

    def cancel(self, event: simpy.Event) -> None:
        """Withdraw a request. If it was already granted, the slot goes back to the pool."""
        for i, (_, _, waiting) in enumerate(self._waiting):
            if waiting is event:
                self._waiting.pop(i)
                heapq.heapify(self._waiting)
                return
        if event.triggered and isinstance(event.value, str):
            self.release(event.value)

    def release(self, slot_id: str) -> None:
        if slot_id in self._free:
            raise ValueError(f"Slot {slot_id} released twice")
        if self._waiting:
            _, _, event = heapq.heappop(self._waiting)
            event.succeed(slot_id)
            return
        self._free.append(slot_id)
        self._free.sort(key=self._order.__getitem__)
