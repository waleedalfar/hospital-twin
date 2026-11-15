"""The timed demo helper (`make demo`, PROMPT.md §13): runs next to the stack and drives the simulation through the
3-minute walkthrough in docs/demo_script.md. It prints each cue as it happens and only does what a presenter could do
by hand: set the speed and press "Flu surge". Everything else on screen is live."""

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

HOSPITAL = "mercy"


@dataclass(frozen=True)
class Beat:
    at_s: float
    cue: str
    request: tuple[str, str, dict[str, object]] | None = None  # (method, path, json body)


BEATS: tuple[Beat, ...] = (
    Beat(0, "0:00 Network map: three hospitals, one simulated day.", ("POST", "/api/sim/speed", {"speed": 4})),
    Beat(20, "0:20 Open Mercy General in 3D."),
    Beat(35, "0:35 X-ray, then the ICU close-up preset."),
    Beat(55, "0:55 Click the highest-risk ICU patient; read the top three reasons."),
    Beat(75, "1:15 FLU SURGE at Mercy, 8x speed.", ("POST", "/api/scenario", {"name": "flu_surge", "hospital_id": HOSPITAL})),
    Beat(76, "1:16 Speed 8x.", ("POST", "/api/sim/speed", {"speed": 8})),
    Beat(95, "1:35 The waiting room fills."),
    Beat(110, "1:50 Governance, Drift: SpO2 and respiratory rate are red."),
    Beat(120, "2:00 Agent panel: read the cited numbers."),
    Beat(135, "2:15 Approve the diversion; look at the network map."),
    Beat(150, "2:30 Ask: who is most likely to crash tonight?"),
    Beat(165, "2:45 Governance, Federated training and the model switch."),
    Beat(180, "3:00 Model card. Done.", ("POST", "/api/sim/speed", {"speed": 1})),
)


async def wait_until_ready(client: httpx.AsyncClient, base: str, sleep: Callable[[float], Awaitable[None]], attempts: int = 120) -> None:
    for _ in range(attempts):
        try:
            health = (await client.get(f"{base}/health")).json()
            if health.get("sim") == "running":
                return
        except (httpx.HTTPError, ValueError):
            pass
        await sleep(2)
    raise TimeoutError("The simulation did not start; is `make dev` running and the database seeded (make seed)?")


async def run(
    base: str = "http://127.0.0.1:8000",
    beats: tuple[Beat, ...] = BEATS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    out: Callable[[str], None] = print,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[str]:
    """Wait for the stack, un-freeze and un-pause the simulation, then fire each beat at its time. Returns the cues."""
    cues: list[str] = []
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        await wait_until_ready(client, base, sleep)
        start: list[tuple[str, dict[str, object]]] = [("/sim/freeze", {"frozen": False}), ("/sim/pause", {"paused": False})]
        for path, body in start:
            (await client.post(f"{base}{path}", json=body)).raise_for_status()
        clock = 0.0
        for beat in beats:
            await sleep(max(0.0, beat.at_s - clock))
            clock = max(clock, beat.at_s)
            if beat.request is not None:
                method, path, body = beat.request
                path = path.removeprefix("/api")
                (await client.request(method, f"{base}{path}", json=body)).raise_for_status()
            cues.append(beat.cue)
            out(beat.cue)
    return cues


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base = args[0] if args else "http://127.0.0.1:8000"
    try:
        asyncio.run(run(base))
    except (TimeoutError, httpx.HTTPError) as error:
        print(f"demo helper stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
