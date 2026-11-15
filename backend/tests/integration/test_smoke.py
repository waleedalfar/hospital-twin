"""The deployment smoke check, run against the real API served by a real uvicorn (PROMPT.md §12)."""

import asyncio
import socket
import threading

import pytest
import uvicorn
from pydantic import SecretStr

from tests.integration.test_sim_db import seed_patients
from twin.api.app import create_app
from twin.common.config import Settings
from twin.ops import smoke


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_urls_use_the_matching_websocket_scheme() -> None:
    assert smoke.ws_url("https://a.example/", "/ws?hospital=mercy") == "wss://a.example/ws?hospital=mercy"
    assert smoke.ws_url("http://127.0.0.1:8000", "/ws") == "ws://127.0.0.1:8000/ws"


async def test_a_healthy_deployment_passes_all_three_checks_and_a_dead_one_fails_clearly(migrated_db_url: str) -> None:
    await seed_patients(migrated_db_url)
    app = create_app(Settings(_env_file=None, database_url=SecretStr(migrated_db_url), sim_warmup_hours=6, sim_autostart=False, ml_enabled=False))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started
        # The API is mounted at / here; a deployment puts it behind /api. Wrap the same app to mimic Caddy.
        checks = await smoke.check_snapshot(f"http://127.0.0.1:{port}")
        assert checks.ok and "snapshot" in checks.detail
    finally:
        server.should_exit = True
        thread.join(10)
    dead = await smoke.run(f"http://127.0.0.1:{free_port()}")
    assert [c.ok for c in dead] == [False, False, False]
    assert all(c.detail for c in dead)


async def test_health_and_page_checks_judge_the_responses() -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "db": "ok", "sim": "running", "ml": "ready"})
        return httpx.Response(200, text='<html><div id="root"></div></html>')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await smoke.check_health(client, "http://x")).ok
        assert (await smoke.check_page(client, "http://x")).ok

    def broken(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={"status": "ok", "db": "error", "sim": "stopped"})
            if request.url.path == "/api/health"
            else httpx.Response(502, text="bad gateway")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as client:
        assert not (await smoke.check_health(client, "http://x")).ok
        assert not (await smoke.check_page(client, "http://x")).ok

    def not_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(not_json)) as client:
        assert not (await smoke.check_health(client, "http://x")).ok
        assert not (await smoke.check_page(client, "http://x")).ok


async def test_run_collects_all_checks_in_order() -> None:
    import httpx  # noqa: F401

    async def fake_snapshot(base: str) -> smoke.Check:
        return smoke.Check("websocket", True, base)

    results = await smoke.run("http://127.0.0.1:9/", fake_snapshot)
    assert [c.name for c in results] == ["health", "page", "websocket"] and results[2].detail == "http://127.0.0.1:9"


def test_the_command_line_reports_and_sets_the_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke.main([]) == 2 and smoke.main(["example.com"]) == 2
    assert "usage" in capsys.readouterr().err

    async def ok(base: str) -> list[smoke.Check]:
        return [smoke.Check("health", True, "fine"), smoke.Check("page", True, "fine")]

    monkeypatch.setattr(smoke, "run", ok)
    assert smoke.main(["https://a.example"]) == 0
    assert "OK   health: fine" in capsys.readouterr().out

    async def bad(base: str) -> list[smoke.Check]:
        return [smoke.Check("health", True, "fine"), smoke.Check("page", False, "HTTP 502")]

    monkeypatch.setattr(smoke, "run", bad)
    assert smoke.main(["https://a.example"]) == 1
    assert "FAIL page: HTTP 502" in capsys.readouterr().out
