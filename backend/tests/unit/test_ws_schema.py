"""The WebSocket schema file is generated from the models and the models validate real messages."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from tests.sim_helpers import make_sim
from twin.common import schema_gen
from twin.common.ws import EventsMessage, ServerMessage, SnapshotMessage


def test_committed_schema_is_up_to_date() -> None:
    assert schema_gen.SCHEMA_PATH.read_text(encoding="utf-8") == schema_gen.render()


def test_schema_cli_writes_and_checks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "s.json"
    assert schema_gen.main(["--check", "--path", str(target)]) == 1
    assert schema_gen.main(["--path", str(target)]) == 0
    assert schema_gen.main(["--check", "--path", str(target)]) == 0
    target.write_text("{}", encoding="utf-8")
    assert schema_gen.main(["--check", "--path", str(target)]) == 1
    assert "out of date" in capsys.readouterr().err


def test_schema_lists_the_message_types_and_event_kinds() -> None:
    schema = json.loads(schema_gen.render())
    assert schema["title"] == "ServerMessage"
    defs = schema["$defs"]
    for name in ("SnapshotMessage", "EventsMessage", "NetworkMessage", "ErrorMessage", "MoveEvent", "Entity"):
        assert name in defs
    snapshot = defs["SnapshotMessage"]["properties"]
    assert snapshot["v"]["const"] == 1
    assert snapshot["type"]["const"] == "snapshot"
    assert {"sim_time", "speed", "paused", "hospital", "entities", "beds", "kpis"} <= set(snapshot)
    assert "from" in defs["MoveEvent"]["properties"]  # serialized under the spec's field name


def test_real_messages_round_trip_through_the_models() -> None:
    sim = make_sim(5, 12)
    sim.run_until(sim.visible_start)
    adapter: TypeAdapter[SnapshotMessage | EventsMessage] = TypeAdapter(ServerMessage)  # type: ignore[arg-type]
    snap = sim.snapshot("mercy", 1, False, False)
    assert adapter.validate_json(snap.model_dump_json(by_alias=True)) == snap
    events = [i.event for i in sim.tick() for _ in [0] if i.hospital_id in ("mercy", None)]
    for _ in range(30):
        events += [i.event for i in sim.tick() if i.hospital_id in ("mercy", None)]
    message = EventsMessage(
        sim_time=sim.now,
        speed=1,
        paused=False,
        frozen=False,
        events=events,
        kpis=snap.kpis,
    )
    text = message.model_dump_json(by_alias=True)
    assert adapter.validate_json(text) == message
    kinds = {e["kind"] for e in json.loads(text)["events"]}
    assert {"move", "vitals"} <= kinds
    move = next(e for e in json.loads(text)["events"] if e["kind"] == "move")
    assert {"from", "to", "path", "depart", "arrive", "entity_id"} <= set(move)


def test_extra_fields_are_rejected() -> None:
    sim = make_sim(5, 2)
    data = json.loads(sim.snapshot("mercy", 1, False, False).model_dump_json())
    data["secret"] = 1
    with pytest.raises(ValueError, match="secret"):
        SnapshotMessage.model_validate(data)
