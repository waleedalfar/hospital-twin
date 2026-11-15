"""`make verify-live` logic, with the client and database replaced (the real call needs a key)."""

import pytest

from tests.agent_helpers import fixture
from tests.sim_helpers import make_profiles
from twin.agent import live_check
from twin.common.config import Settings
from twin.sim.entities import PatientProfile


class Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def generate(self, prompt: str) -> str:
        return self.reply


def patch(monkeypatch: pytest.MonkeyPatch, client: object, profiles: list[PatientProfile] | None = None) -> None:
    monkeypatch.setattr(live_check, "get_settings", lambda: Settings(_env_file=None, gemini_api_key=None, gemini_model=None))
    monkeypatch.setattr(live_check, "make_client", lambda key, model: client)

    async def load(dsn: str) -> list[PatientProfile]:
        return profiles if profiles is not None else make_profiles()

    monkeypatch.setattr(live_check, "load_profiles", load)


async def test_without_a_key_it_says_so_and_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch(monkeypatch, None)
    assert await live_check.check() == 0
    assert "skipped" in capsys.readouterr().out


async def test_without_patients_it_fails_and_says_to_seed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch(monkeypatch, Client("{}"), profiles=[])
    assert await live_check.check() == 1
    assert "make seed" in capsys.readouterr().err


async def test_unparseable_answers_fail(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch(monkeypatch, Client(fixture("malformed.json")))
    assert await live_check.check() == 1
    assert "FAILED" in capsys.readouterr().err


async def test_an_answer_that_is_not_grounded_in_the_real_summary_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch(monkeypatch, Client(fixture("ungrounded_value.json")))
    assert await live_check.check() == 1
    assert "not grounded" in capsys.readouterr().err


async def test_an_empty_recommendation_set_is_a_valid_answer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch(monkeypatch, Client(fixture("empty.json")))
    assert await live_check.check() == 0
    assert "OK, 0 grounded" in capsys.readouterr().out
