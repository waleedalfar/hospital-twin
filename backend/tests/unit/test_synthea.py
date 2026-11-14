import hashlib
import http.server
import itertools
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from twin.db import synthea
from twin.db.synthea import SyntheaError

JAR_BYTES = b"not really a jar, just bytes for the checksum test\n" * 100
JAR_SHA = hashlib.sha256(JAR_BYTES).hexdigest()


@pytest.fixture
def file_server(tmp_path: Path) -> Iterator[str]:
    """A real HTTP server on this machine serving one file, to test the download without the internet."""
    root = tmp_path / "www"
    root.mkdir()
    (root / "synthea.jar").write_bytes(JAR_BYTES)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(root), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def fake_java(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-java"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def test_pinned_release() -> None:
    assert synthea.SYNTHEA_VERSION in synthea.JAR_URL
    assert synthea.JAR_URL.startswith("https://github.com/synthetichealth/synthea/releases/download/")
    assert len(synthea.JAR_SHA256) == 64


def test_command_is_phoenix_with_a_fixed_seed(tmp_path: Path) -> None:
    command = synthea.build_command("java", tmp_path / "s.jar", tmp_path / "out", 3000, 42)
    assert command[:3] == ["java", "-jar", str(tmp_path / "s.jar")]
    assert command[-2:] == ["Arizona", "Phoenix"]
    pairs = dict(itertools.pairwise(command))
    assert pairs["-s"] == "42"
    assert pairs["-cs"] == "42"
    assert pairs["-p"] == "3000"
    assert pairs["-r"] == "20261114"
    assert pairs["-e"] == "20261114"
    assert "--exporter.fhir.export=true" in command
    assert f"--exporter.baseDirectory={tmp_path / 'out'}" in command


def test_download_verifies_checksum_and_is_skipped_when_present(tmp_path: Path, file_server: str) -> None:
    target = tmp_path / "data" / "synthea.jar"
    url = f"{file_server}/synthea.jar"
    assert synthea.ensure_jar(target, url, JAR_SHA) == target
    assert target.read_bytes() == JAR_BYTES
    assert not target.with_suffix(".part").exists()
    # Present with the right checksum: no download is attempted, so a dead URL is fine.
    assert synthea.ensure_jar(target, "https://127.0.0.1:1/unused.jar", JAR_SHA) == target


def test_download_with_wrong_checksum_is_rejected(tmp_path: Path, file_server: str) -> None:
    target = tmp_path / "synthea.jar"
    with pytest.raises(SyntheaError, match="Checksum mismatch"):
        synthea.ensure_jar(target, f"{file_server}/synthea.jar", "0" * 64)
    assert not target.exists()
    assert not target.with_suffix(".part").exists()


def test_corrupt_local_jar_is_downloaded_again(tmp_path: Path, file_server: str) -> None:
    target = tmp_path / "synthea.jar"
    target.write_bytes(b"corrupt")
    synthea.ensure_jar(target, f"{file_server}/synthea.jar", JAR_SHA)
    assert target.read_bytes() == JAR_BYTES


def test_download_errors_are_reported(tmp_path: Path, file_server: str) -> None:
    with pytest.raises(SyntheaError, match="Could not download"):
        synthea.ensure_jar(tmp_path / "a.jar", f"{file_server}/missing.jar", JAR_SHA)
    with pytest.raises(SyntheaError, match="non-HTTPS"):
        synthea.ensure_jar(tmp_path / "b.jar", "http://example.com/synthea.jar", JAR_SHA)
    with pytest.raises(SyntheaError, match="non-HTTPS"):
        synthea.ensure_jar(tmp_path / "c.jar", "file:///etc/hosts", JAR_SHA)


def test_find_java_prefers_the_configured_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    java = fake_java(tmp_path, "exit 0\n")
    assert synthea.find_java(java) == java
    with pytest.raises(SyntheaError, match="does not exist"):
        synthea.find_java(str(tmp_path / "nope"))

    home = tmp_path / "jdk"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "java").write_text("", encoding="utf-8")
    monkeypatch.setenv("JAVA_HOME", str(home))
    assert synthea.find_java() == str(home / "bin" / "java")


def test_find_java_falls_back_to_path_then_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr(synthea, "JAVA_CANDIDATES", (str(tmp_path / "missing"),))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    java = bin_dir / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    java.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    assert synthea.find_java() == str(java)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(SyntheaError, match="brew install openjdk@17"):
        synthea.find_java()


def test_generate_runs_the_command_and_writes_a_marker(tmp_path: Path) -> None:
    out = tmp_path / "out"
    stale = out / "fhir" / "stale.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    java = fake_java(
        tmp_path,
        f'mkdir -p "{out}/fhir" && echo "$@" > "{out}/args.txt" && echo "{{}}" > "{out}/fhir/p1.json"\n',
    )
    assert not synthea.is_generated(out, 5, 7)
    fhir_dir = synthea.generate(java, tmp_path / "s.jar", out, 5, 7)
    assert fhir_dir == out / "fhir"
    assert [p.name for p in fhir_dir.iterdir()] == ["p1.json"]  # the stale bundle was removed first
    assert "-p 5" in (out / "args.txt").read_text(encoding="utf-8")
    assert json.loads((out / synthea.MARKER_NAME).read_text(encoding="utf-8"))["population"] == 5
    assert synthea.is_generated(out, 5, 7)
    assert not synthea.is_generated(out, 6, 7)
    assert not synthea.is_generated(out, 5, 8)


def test_generate_reports_failures(tmp_path: Path) -> None:
    failing = fake_java(tmp_path, 'echo "boom: out of memory" >&2\nexit 3\n')
    with pytest.raises(SyntheaError, match="code 3: boom: out of memory"):
        synthea.generate(failing, tmp_path / "s.jar", tmp_path / "out", 5, 7)
    assert not synthea.is_generated(tmp_path / "out", 5, 7)
    silent = fake_java(tmp_path, "exit 0\n")
    with pytest.raises(SyntheaError, match="wrote no bundles"):
        synthea.generate(silent, tmp_path / "s.jar", tmp_path / "out2", 5, 7)
