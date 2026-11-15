"""Downloads the Synthea release jar and generates FHIR patient bundles (PROMPT.md §4.3).

The release is pinned and its checksum is verified, so every machine generates the same patients.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from twin.common.config import REPO_ROOT

logger = logging.getLogger(__name__)

SYNTHEA_VERSION = "v3.3.0"
JAR_URL = f"https://github.com/synthetichealth/synthea/releases/download/{SYNTHEA_VERSION}/synthea-with-dependencies.jar"
JAR_SHA256 = "8ba04f7d73abadd5a377e41edf24c5c83935a1cb07c6d982cd5db731ef1cf445"
DATA_DIR = REPO_ROOT / "data" / "synthea"
JAR_NAME = "synthea-with-dependencies.jar"
MARKER_NAME = "generation.json"
STATE = "Arizona"
CITY = "Phoenix"
# The simulation starts on this date (§5.1); ages are computed as of it, whatever day the jar is run.
REFERENCE_DATE = "20261114"
MIN_AGE, MAX_AGE = 18, 90
JAVA_CANDIDATES = ("/opt/homebrew/opt/openjdk@17/bin/java", "/usr/local/opt/openjdk@17/bin/java")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
CHUNK = 1 << 20


class SyntheaError(Exception):
    """Synthea could not be downloaded or run."""


def find_java(configured: str | None = None) -> str:
    """Path of the Java binary to use: the configured one, JAVA_HOME, Homebrew openjdk@17, or PATH."""
    if configured:
        if not Path(configured).is_file():
            raise SyntheaError(f"SYNTHEA_JAVA points at {configured}, which does not exist")
        return configured
    candidates: list[str] = []
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(str(Path(java_home) / "bin" / "java"))
    candidates.extend(JAVA_CANDIDATES)
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    on_path = shutil.which("java")
    if on_path:
        return on_path
    raise SyntheaError("Java was not found. Install it with: brew install openjdk@17")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_jar(path: Path, url: str = JAR_URL, sha256: str = JAR_SHA256) -> Path:
    """Return `path`, downloading the jar from `url` first unless a file with the right checksum is there."""
    if path.is_file() and sha256_file(path) == sha256:
        return path
    parts = urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS):
        raise SyntheaError(f"Refusing to download from a non-HTTPS URL: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    logger.info("Downloading Synthea %s", url)
    try:
        # The scheme is checked above (https, or http to this machine only).
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out, CHUNK)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise SyntheaError(f"Could not download {url}: {error}") from error
    actual = sha256_file(partial)
    if actual != sha256:
        partial.unlink()
        raise SyntheaError(f"Checksum mismatch for {url}: expected {sha256}, got {actual}")
    partial.replace(path)
    return path


def build_command(java: str, jar: Path, out_dir: Path, population: int, seed: int) -> list[str]:
    """The exact Synthea command line. One year of history keeps bundles small; active conditions of any
    age are still exported."""
    return [
        java,
        "-jar",
        str(jar),
        "-s",
        str(seed),
        "-cs",
        str(seed),
        "-r",
        REFERENCE_DATE,
        "-e",
        REFERENCE_DATE,
        "-p",
        str(population),
        "-a",
        f"{MIN_AGE}-{MAX_AGE}",
        "--exporter.fhir.export=true",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
        "--exporter.years_of_history=1",
        f"--exporter.baseDirectory={out_dir}",
        STATE,
        CITY,
    ]


def marker_for(population: int, seed: int) -> dict[str, object]:
    return {
        "synthea": SYNTHEA_VERSION,
        "population": population,
        "seed": seed,
        "state": STATE,
        "city": CITY,
        "reference_date": REFERENCE_DATE,
    }


def is_generated(out_dir: Path, population: int, seed: int) -> bool:
    """True if `out_dir` already holds a finished run with the same parameters."""
    marker = out_dir / MARKER_NAME
    if not marker.is_file():
        return False
    return bool(json.loads(marker.read_text(encoding="utf-8")) == marker_for(population, seed))


def generate(java: str, jar: Path, out_dir: Path, population: int, seed: int) -> Path:
    """Run Synthea and return the directory holding one FHIR bundle per patient."""
    fhir_dir = out_dir / "fhir"
    shutil.rmtree(fhir_dir, ignore_errors=True)
    (out_dir / MARKER_NAME).unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(java, jar, out_dir, population, seed)
    logger.info("Running Synthea for %d patients in %s, %s (seed %d)", population, CITY, STATE, seed)
    # Arguments are built above from constants and integers; nothing comes from user input.
    result = subprocess.run(command, cwd=out_dir, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-2000:]
        raise SyntheaError(f"Synthea exited with code {result.returncode}: {tail}")
    if not any(fhir_dir.glob("*.json")):
        raise SyntheaError(f"Synthea finished but wrote no bundles to {fhir_dir}")
    (out_dir / MARKER_NAME).write_text(json.dumps(marker_for(population, seed), indent=1) + "\n", encoding="utf-8")
    return fhir_dir
