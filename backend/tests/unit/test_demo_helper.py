"""The timed demo helper (docs/demo_script.md)."""

import httpx
import pytest

from twin.ops import demo


def make_transport(calls: list[tuple[str, str, str]], healthy_after: int = 0) -> httpx.MockTransport:
    state = {"health": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            state["health"] += 1
            return httpx.Response(200, json={"sim": "running" if state["health"] > healthy_after else "starting"})
        calls.append((request.method, request.url.path, request.read().decode()))
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


async def test_the_beats_are_fired_in_order_at_their_times() -> None:
    calls: list[tuple[str, str, str]] = []
    slept: list[float] = []
    cues_out: list[str] = []

    async def sleep(s: float) -> None:
        slept.append(s)

    cues = await demo.run("http://x", sleep=sleep, out=cues_out.append, transport=make_transport(calls))
    assert cues == cues_out == [b.cue for b in demo.BEATS]
    paths = [(m, p) for m, p, _ in calls]
    assert paths[:2] == [("POST", "/sim/freeze"), ("POST", "/sim/pause")]  # the sim is running before the show starts
    assert ("POST", "/scenario") in paths and paths.count(("POST", "/sim/speed")) == 3
    scenario = next(body for m, p, body in calls if p == "/scenario")
    assert '"flu_surge"' in scenario and '"mercy"' in scenario
    assert sum(slept) == pytest.approx(demo.BEATS[-1].at_s)  # the whole walkthrough is about three minutes
    assert demo.BEATS[-1].at_s == 180 and all(a.at_s <= b.at_s for a, b in zip(demo.BEATS, demo.BEATS[1:], strict=False))


async def test_it_waits_for_the_simulation_to_start() -> None:
    calls: list[tuple[str, str, str]] = []
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    await demo.run("http://x", beats=(demo.Beat(0, "go"),), sleep=sleep, out=lambda _: None, transport=make_transport(calls, healthy_after=3))
    assert waits[:3] == [2, 2, 2]


async def test_it_gives_up_with_a_helpful_message_when_the_stack_never_starts() -> None:
    async def sleep(s: float) -> None:
        return None

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(TimeoutError, match="make seed"):
            await demo.wait_until_ready(client, "http://x", sleep, attempts=3)


def test_the_command_line_reports_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def failing(base: str) -> list[str]:
        raise TimeoutError("did not start")

    monkeypatch.setattr(demo, "run", failing)
    assert demo.main(["http://x"]) == 1
    assert "did not start" in capsys.readouterr().err

    async def fine(base: str) -> list[str]:
        return []

    monkeypatch.setattr(demo, "run", fine)
    assert demo.main([]) == 0
