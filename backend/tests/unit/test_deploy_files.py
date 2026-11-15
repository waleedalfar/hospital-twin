"""The deployment files (PROMPT.md §12): the script's plan, the compose file and the Caddyfile."""

import os
import subprocess
from pathlib import Path

from twin.common.config import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "deploy.sh"


def run_script(**env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DEPLOY_", "DOMAIN"))}
    clean["DEPLOY_ENV_FILE"] = "/nonexistent/.env.deploy"  # never read the developer's real settings in a test
    # Run from a temp-free copy of the environment; .env.deploy in the repo (if any) is read by the script itself.
    # Runs the repository's own script in dry-run mode.
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        capture_output=True,
        text=True,
        env={**clean, **env},
        cwd=REPO_ROOT,
        check=False,
        timeout=60,
    )


def test_a_dry_run_lists_every_step_in_order_without_touching_anything() -> None:
    result = run_script(DRY_RUN="1", DEPLOY_HOST="203.0.113.10", DOMAIN="example.org", DEPLOY_USER="deploy")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    steps = [
        "==> Checking the VM (deploy@203.0.113.10)",
        "==> Copying the project",
        "==> Building and starting the stack",
        "==> Migrations",
        "==> Smoke check of https://example.org",
    ]
    positions = [out.index(s) for s in steps]
    assert positions == sorted(positions)
    assert "docker compose -f infra/docker-compose.prod.yml --env-file .env up -d --build" in out
    assert "python -m twin.db.migrate" in out and "python -m twin.ops.smoke https://example.org" in out
    assert "--exclude=.env" in out and "--exclude=.git/" in out  # secrets and git history never leave the machine


def test_it_refuses_to_run_without_a_host_or_a_domain() -> None:
    missing_host = run_script(DRY_RUN="1", DOMAIN="example.org")
    assert missing_host.returncode != 0 and "DEPLOY_HOST" in missing_host.stderr
    missing_domain = run_script(DRY_RUN="1", DEPLOY_HOST="203.0.113.10")
    assert missing_domain.returncode != 0 and "DOMAIN" in missing_domain.stderr


def test_the_production_stack_serves_https_for_the_domain_and_proxies_api_and_websockets() -> None:
    compose = (REPO_ROOT / "infra" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "DOMAIN: ${DOMAIN:?" in compose and '"443:443"' in compose and "env_file: ../.env" in compose
    assert "timescaledb" not in compose  # the database is Tiger Cloud, not a container
    caddy = (REPO_ROOT / "infra" / "Caddyfile").read_text(encoding="utf-8")
    assert "{$DOMAIN}" in caddy and "uri strip_prefix /api" in caddy and "handle /ws*" in caddy
    assert "reverse_proxy backend:8000" in caddy and "try_files {path} /index.html" in caddy


def test_secrets_are_not_part_of_what_is_copied_or_built() -> None:
    ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and ".env.*" in ignore and ".git" in ignore
    example = (REPO_ROOT / ".env.deploy.example").read_text(encoding="utf-8")
    assert "PASSWORD" in example and "GEMINI_API_KEY=..." in example  # dummy values only
    assert ".env.*" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert Path(SCRIPT).stat().st_mode & 0o111  # executable
