"""Smoke check of a running deployment (PROMPT.md §12): `python -m twin.ops.smoke https://example.com`.

Three checks against the public URL: `/api/health` says the database and the simulation are fine, the front page
loads, and a WebSocket to a hospital sends a snapshot. Exit code 0 only if all three pass."""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import websockets

TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def ws_url(base: str, path: str) -> str:
    scheme = "wss" if base.startswith("https://") else "ws"
    return f"{scheme}://{base.split('://', 1)[1].rstrip('/')}{path}"


async def check_health(client: httpx.AsyncClient, base: str) -> Check:
    try:
        response = await client.get(f"{base}/api/health")
        body = response.json()
    except (httpx.HTTPError, ValueError) as error:
        return Check("health", False, f"{type(error).__name__}: {error}")
    ok = response.status_code == 200 and body.get("status") == "ok" and body.get("db") == "ok" and body.get("sim") == "running"
    return Check("health", ok, f"status={body.get('status')} db={body.get('db')} sim={body.get('sim')} ml={body.get('ml')}")


async def check_page(client: httpx.AsyncClient, base: str) -> Check:
    try:
        response = await client.get(f"{base}/")
    except httpx.HTTPError as error:
        return Check("page", False, f"{type(error).__name__}: {error}")
    ok = response.status_code == 200 and 'id="root"' in response.text
    return Check("page", ok, f"HTTP {response.status_code}, {len(response.text)} bytes")


async def check_snapshot(base: str, hospital: str = "mercy") -> Check:
    url = ws_url(base, f"/ws?hospital={hospital}")
    try:
        async with websockets.connect(url, open_timeout=TIMEOUT_S) as socket:
            message = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT_S))
    except (OSError, TimeoutError, websockets.WebSocketException, ValueError) as error:
        return Check("websocket", False, f"{type(error).__name__}: {error}")
    ok = message.get("type") == "snapshot" and bool(message.get("entities"))
    return Check("websocket", ok, f"first message {message.get('type')} with {len(message.get('entities', []))} entities")


async def run(base: str, snapshot: Callable[[str], Awaitable[Check]] = check_snapshot) -> list[Check]:
    base = base.rstrip("/")
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
        return [await check_health(client, base), await check_page(client, base), await snapshot(base)]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].startswith(("http://", "https://")):
        print("usage: python -m twin.ops.smoke https://your-domain", file=sys.stderr)
        return 2
    checks = asyncio.run(run(args[0]))
    for c in checks:
        print(f"{'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
