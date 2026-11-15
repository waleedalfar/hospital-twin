"""A list of Gemini models to try in order (`GEMINI_MODEL=a,b,c`). Free-tier models are not always available (daily
quota, overload, a name that does not exist for this key), so a failing model is skipped for a while and the next
one is used; only when every model fails does the caller fall back to the rules engine."""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from google.genai.errors import APIError

logger = logging.getLogger(__name__)

QUOTA_COOLDOWN_S = 900.0  # 429: the daily or per-minute quota is used up
MISSING_COOLDOWN_S = 3600.0  # 404: this key has no such model
DEFAULT_COOLDOWN_S = 60.0  # overload, timeouts, bad replies
MAX_TRIES = 4


def cooldown_for(error: Exception) -> float:
    code = error.code if isinstance(error, APIError) else None
    if code == 429:
        return QUOTA_COOLDOWN_S
    if code in (400, 403, 404):
        return MISSING_COOLDOWN_S
    return DEFAULT_COOLDOWN_S


@dataclass
class ModelChain:
    models: list[str]
    clock: Callable[[], float] = time.monotonic
    failed_until: dict[str, float] = field(default_factory=dict)
    last_used: str | None = None

    @staticmethod
    def parse(spec: str | None) -> "ModelChain":
        """`"a, b ,c"` -> [a, b, c]; blanks and duplicates are dropped."""
        seen: list[str] = []
        for part in (spec or "").split(","):
            name = part.strip().removeprefix("models/")
            if name and name not in seen:
                seen.append(name)
        return ModelChain(seen)

    def order(self) -> list[str]:
        """Models that are not cooling down first (in the configured order), then the cooling ones: a model whose
        cooldown has not ended is still tried last rather than never."""
        now = self.clock()
        ready = [m for m in self.models if self.failed_until.get(m, 0.0) <= now]
        return ready + [m for m in self.models if m not in ready]

    async def run[T](self, call: Callable[[str], Awaitable[T]], retry_on: tuple[type[Exception], ...], max_tries: int = MAX_TRIES) -> T:
        """Call with each model in turn until one works. Raises the last error if all fail."""
        last: Exception | None = None
        for model in self.order()[:max_tries]:
            try:
                result = await call(model)
            except retry_on as error:
                self.failed_until[model] = self.clock() + cooldown_for(error)
                logger.warning("Gemini model %s failed (%s: %s); trying the next one", model, type(error).__name__, str(error)[:200])
                last = error
                continue
            self.failed_until.pop(model, None)
            if model != self.last_used:
                logger.info("Gemini model in use: %s", model)
            self.last_used = model
            return result
        if last is None:
            raise ValueError("No Gemini model is configured")
        raise last
