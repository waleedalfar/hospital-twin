import logging

import pytest

from twin.common.logging import REDACTED, SecretRedactingFilter, configure_logging, redact_dsn


@pytest.fixture
def restore_root_logger() -> object:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield None
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def test_redact_dsn_hides_only_the_password() -> None:
    assert redact_dsn("postgresql://twin:s3cret@db:5432/twin") == f"postgresql://twin:{REDACTED}@db:5432/twin"


def test_redact_dsn_inside_a_sentence() -> None:
    text = "could not connect to postgres://u:pw@h/x after 3 tries"
    assert redact_dsn(text) == f"could not connect to postgres://u:{REDACTED}@h/x after 3 tries"


def test_redact_dsn_leaves_other_text_alone() -> None:
    for text in ("no url here", "http://localhost:8000/health", "postgresql://twin@db/twin", "time 12:30@x"):
        assert redact_dsn(text) == text


def test_filter_removes_known_secrets_from_message_and_args() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "key=%s url=%s", ("abc123", "x://u:pw@h"), None)
    assert SecretRedactingFilter(["abc123"]).filter(record) is True
    assert record.getMessage() == f"key={REDACTED} url=x://u:{REDACTED}@h"


def test_filter_replaces_longer_secret_first() -> None:
    redactor = SecretRedactingFilter(["abc", "abcdef", ""])
    assert redactor.redact("value abcdef end") == f"value {REDACTED} end"


def test_configure_logging_redacts_output(restore_root_logger: object, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("debug", ["topsecret"])
    logging.getLogger("twin.test").info("token topsecret used for postgresql://a:b@c/d")
    err = capsys.readouterr().err
    assert "topsecret" not in err
    assert "a:b@" not in err
    assert f"token {REDACTED} used" in err
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_replaces_existing_handlers(restore_root_logger: object) -> None:
    configure_logging("INFO", [])
    configure_logging("WARNING", [])
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger().level == logging.WARNING
