"""Runs federated training in a child process and streams its progress to the browsers (PROMPT.md §7.6).

The Flower simulation (Ray, PyTorch) runs as `python -m twin.ml.fed_cli --json` so it cannot slow or crash the API.
Each JSON line it prints becomes a `federated` WebSocket message; when it finishes the comparison is on disk.
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from twin.api.hub import Hub
from twin.common.ws import FederatedMessage
from twin.ml.fed_cli import TRAIN_ROWS
from twin.ml.model import MODELS_DIR

logger = logging.getLogger(__name__)


class FederatedError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class FederatedService:
    hub: Hub
    audit: Any  # async (action, payload, actor) -> None
    rows_path: Path = TRAIN_ROWS
    models_dir: Path = MODELS_DIR
    command: list[str] = field(default_factory=lambda: [sys.executable, "-m", "twin.ml.fed_cli", "--json"])
    state: FederatedMessage = field(default_factory=lambda: FederatedMessage(status="idle", round=0, rounds=0, val_auroc=[]))
    task: asyncio.Task[None] | None = None

    def publish(self, **changes: Any) -> None:
        self.state = self.state.model_copy(update=changes)
        self.hub.publish_network(self.state.model_dump_json())

    async def start(self, actor: str = "user") -> FederatedMessage:
        if self.state.status == "running":
            raise FederatedError("Federated training is already running", 409)
        if not self.rows_path.is_file():
            raise FederatedError("No training rows yet. Run `make train` first.", 409)
        self.publish(status="running", round=0, rounds=0, val_auroc=[], error=None)
        await self.audit("federated_run_start", {}, actor)
        self.task = asyncio.create_task(self.run(actor), name="federated-run")
        return self.state

    async def run(self, actor: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(*self.command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            assert process.stdout is not None  # noqa: S101 - PIPE was requested above
            problems: list[str] = []
            error: str | None = None
            async for line in process.stdout:
                event = self.parse(line)
                if event is None:
                    continue
                if event["event"] == "round":
                    auroc = event.get("auroc")
                    self.publish(
                        round=event["round"],
                        rounds=event["rounds"],
                        val_auroc=[*self.state.val_auroc, *([float(auroc)] if auroc is not None else [])],
                    )
                elif event["event"] == "error":
                    error = str(event["message"])
                elif event["event"] == "done":
                    problems = list(event.get("problems", []))
            _, stderr = await process.communicate()
            code = process.returncode
            if error is not None or (code not in (0, 1)):
                message = error or stderr.decode("utf-8", "replace")[-300:] or f"exit code {code}"
                logger.error("Federated training failed: %s", message)
                self.publish(status="failed", error=message)
                await self.audit("federated_run_failed", {"error": message}, actor)
                return
            self.publish(status="done", error="; ".join(problems) if problems else None)
            await self.audit("federated_run_done", {"gates_ok": not problems, "problems": problems, "rounds": self.state.rounds}, actor)
        except OSError as os_error:
            logger.exception("Could not start federated training")
            self.publish(status="failed", error=str(os_error))
            await self.audit("federated_run_failed", {"error": str(os_error)}, actor)

    def parse(self, line: bytes) -> dict[str, Any] | None:
        text = line.decode("utf-8", "replace").strip()
        if not text.startswith("{"):
            return None  # library log lines
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Unreadable federated progress line: %s", text[:200])
            return None
        return event if isinstance(event, dict) and "event" in event else None

    def result(self, deterioration_version: str) -> dict[str, Any] | None:
        path = self.models_dir / deterioration_version / "federated.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
