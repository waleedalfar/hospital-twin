# Checkpoints

One section per checkpoint (CLAUDE.md §4). Work on the next checkpoint starts only after the human
replies "approved CPn".

---

## CP0 — Scaffold (2026-11-14)

Spec: PROMPT.md §14 row CP0, CLAUDE.md §5–6.

### What was built

| Requirement | Where |
| --- | --- |
| Repo layout (CLAUDE.md §6) | `backend/twin/{api,sim,db,ml,agent,common}`, `backend/tests/{unit,integration}`, `frontend/src/{engine,state,ui}`, `frontend/tests`, `frontend/e2e`, `shared/`, `infra/`, `docs/`, `reference/` |
| Makefile targets (CLAUDE.md §5) | `Makefile`: `setup`, `db`, `dev`, `test`, `e2e`, `verify` work now. `seed`, `train`, `fed-train`, `verify-live`, `deploy`, `demo`, `record` exist and stop with an error naming their checkpoint (approved in the CP0 plan) |
| Docker DB up | `infra/docker-compose.yml` (dev, port 5433, volume), `infra/docker-compose.test.yml` (tests, port 5434, in-memory). Image `timescale/timescaledb:2.17.2-pg16`, arm64 and amd64 |
| Migrations runner (§4.1 "applied in order, idempotent") | `backend/twin/db/migrate.py`, first migration `backend/twin/db/migrations/0001_extensions.sql` (enables TimescaleDB). Tables arrive in CP1 |
| Backend skeleton | `twin/common/config.py` (settings from env / `.env`), `twin/common/logging.py` (secrets removed from logs), `twin/db/pool.py`, `twin/api/app.py`, `twin/api/health.py` (`GET /health`, typed, 503 with an error body when the DB check fails) |
| Frontend skeleton | React 18 + Vite + TypeScript strict, three.js pinned to exactly 0.149.0 (§2). Shell shows "Hospital Twin", the "Simulated data" label, and the backend status read from `/api/health` every 5 s |
| `make verify` (CLAUDE.md §3) | ruff check + format check, `mypy --strict`, eslint (strict, type-checked), `tsc --noEmit`, pytest with 85% coverage gate, vitest with 80% coverage gate, zero-skipped-tests checks, placeholder grep (`scripts/check_placeholders.sh`) |
| CI workflow | `.github/workflows/ci.yml`: `make setup`, `make verify`, `make e2e` on every push, pull request and `cp*` tag |
| `.env.example` | Every setting, dummy values. A test fails if a setting is missing from it |
| macOS setup (CLAUDE.md §5) | Installed `uv` and `openjdk@17` with Homebrew; Python 3.12.16 via uv. README section "Setup on macOS" |

Decisions recorded from the human before CP0: public GitHub repo; npm for the frontend; sim "local" time is
America/Phoenix (used from CP2); commits authored only by the human's own git identity.

### Commands run and results

| Command | Result |
| --- | --- |
| `make setup` | Dependencies installed, images pulled, `.env` created |
| `make verify` | Exit 0. ruff, mypy (24 files), eslint, tsc: clean. Backend: **38 passed, 0 skipped, coverage 100%** (gate 85%), 1.3 s. Frontend: **26 passed, 0 skipped, coverage 100%** (gate 80%), 0.7 s. Placeholder check passed |
| `make e2e` | Exit 0. **2 passed, 0 skipped**, 7.0 s (headless Chromium with the SwiftShader flags) |
| `make dev` + `curl` | `/api/health` through the frontend proxy → HTTP 200, `db: ok`, TimescaleDB 2.17.2, 1 migration |
| DB container stopped, `curl /health` | HTTP 503, `status: degraded`, `error: ConnectionRefusedError`; back to 200 after the DB restarts, without restarting the backend |

The checks themselves were checked: a file containing an unfinished-work marker made the placeholder check
fail, and a test marked as skipped made the pytest run exit 1. Both probe files were removed afterwards.

Integration tests use the real TimescaleDB container. Each test creates its own empty database and drops it
afterwards. They cover: migrations on an empty database, a second run applying nothing, only new
migrations being applied, a failing migration rolling back completely, an edited migration being rejected,
and `/health` in four database states.

### Evidence

- `docs/evidence/cp0/shell.png` — the running app, captured by the e2e test.
- `docs/evidence/cp0/health_ok.txt` — `/api/health` response from the running stack.
- `docs/evidence/cp0/health_db_stopped.txt` — `/health` response with the database stopped.
- CI run for the `cp0` tag: see the Actions tab of the GitHub repo.

### How to check it yourself (under 5 minutes)

1. `make verify` — ends with "make verify: all checks passed"; look for 38 and 26 passed tests.
2. `make dev`, then open http://127.0.0.1:5173 — the header says "Hospital Twin" with "Simulated data",
   and the status line says "Backend OK - TimescaleDB 2.17.2 - 1 migration applied".
3. In another terminal: `docker compose -f infra/docker-compose.yml stop db` — within 5 seconds the status
   line turns to "Backend degraded: ...". Run `make db` and it returns to OK.
4. `make e2e` (stop `make dev` first or leave it running; both work) — 2 tests pass.
5. `make seed` — stops with "the Synthea loader is built in CP1", exit code 2 from make.
6. `git log --format='%an <%ae> | %cn <%ce>%n%B' -1` — author and committer are you; no other names.

### Deviations from spec

1. **Later-checkpoint Makefile targets stop with an error** instead of working (`seed`, `train`,
   `fed-train`, `verify-live`, `deploy`, `demo`, `record`). Approved in the CP0 plan. Each becomes real in
   its checkpoint.
2. **The faceless test is not yet part of `make verify`.** `characterFactory` is built in CP3, and the
   test joins `make verify` there. Approved in the CP0 plan. No characters, icons or logos exist yet.
3. **Frontend tool versions:** Vite 5, Vitest 2, ESLint 9 and TypeScript 5.6 were chosen over the newest
   major versions because they are known to work with Node 20 and three.js 0.149 typings. The spec does
   not name versions for these.

### Known issues

None.

### Questions for the human

1. When did the 48-hour clock start? It is needed to compare progress with the target hours in §14.
2. For CP2 (no answer needed yet): §5.6 says mass casualty happens "at the nearest hospital". The plan is
   for the scenario to take an incident location on the city grid and choose the nearest hospital to it.

**Waiting for "approved CP0" before starting CP1.**
