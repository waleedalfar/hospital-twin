"""Logging setup. Secrets are stripped from every record before it is written."""

import logging
import re
from collections.abc import Iterable

REDACTED = "***"
_DSN_PASSWORD = re.compile(r"(?P<head>[a-zA-Z][a-zA-Z0-9+.\-]*://[^:/@\s]+):(?P<password>[^@\s]+)@")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def redact_dsn(text: str) -> str:
    """Replace the password of any `scheme://user:password@host` URL in `text`."""
    return _DSN_PASSWORD.sub(lambda match: f"{match.group('head')}:{REDACTED}@", text)


class SecretRedactingFilter(logging.Filter):
    """Removes known secret values and URL passwords from log records."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        # Longest first, so a secret that contains another one is replaced whole.
        self._secrets = sorted({secret for secret in secrets if secret}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return redact_dsn(text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        return True


def configure_logging(level: str, secrets: Iterable[str]) -> None:
    """Configure the root logger once, with secret redaction on its handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(SecretRedactingFilter(secrets))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
