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

**Approved by the human on 2026-11-14. The 48-hour clock started at 14:42 MST that day.**

---

## CP1 — Data layer (2026-11-14, hour 0.6 of 48; target hour 5)

Spec: PROMPT.md §3, §4.

### What was built

| Spec | What | Where |
| --- | --- | --- |
| §3 | `shared/layout.json` generated by a script from the §3 tables: 3 floors + roof, 15 rooms, corridor and elevator per floor, 23 doors and openings, 29 beds, 23 seats, 77 work spots, 69 props, the three hospitals at Phoenix coordinates, ambulance bay, helipad, and a waypoint graph (278 nodes, 282 edges) | `backend/twin/sim/build_layout.py`, `layout_tables.py`, `layout_parts.py`, `layout_graph.py`, `layout_model.py` |
| §3 | Test of the generated file against the §3 tables. The expected numbers are typed into the test by hand, not imported from the generator | `backend/tests/unit/test_layout_spec.py` |
| §3 | Waypoint graph tests: connected; floors joined only by the elevator; every node inside its room; no edge through a wall except at a door; no edge through a bed or furniture | `backend/tests/unit/test_layout_graph.py` |
| §4.1 | Reference tables `hospitals`, `units`, `rooms`, `beds`, `staff`, `patients`, `encounters` | `backend/twin/db/migrations/0002_reference_tables.sql` |
| §4.1 | Hypertables `vitals`, `events`, `bed_state`, `risk_scores`, `forecasts`, `agent_recs`, `audit_log`, `drift`, with (patient_id, time DESC) and (hospital_id, time DESC) indexes | `0003_hypertables.sql` |
| §4.2 | Continuous aggregates `occupancy_15m`, `er_wait_15m`, `arrivals_hourly`, `alerts_hourly`, `vitals_5m`, each with a refresh policy | `0004_continuous_aggregates.sql` |
| §4.2 | Compression on `vitals` and `events` for chunks older than 1 day | `0005_compression.sql` |
| §4.1, CLAUDE.md §7 | Reference tables filled from `layout.json` on every `make db`; test that bed ids in the DB and the layout match in both directions (87 = 3 hospitals x 29) | `backend/twin/db/reference.py`, `backend/tests/integration/test_reference.py` |
| §4.3 | `make seed`: downloads the pinned Synthea 3.3.0 jar (SHA-256 verified), generates patients for Phoenix, Arizona with seed 20261114, loads Patient + Condition resources, extracts age, sex, conditions and comorbidity count | `backend/twin/db/synthea.py`, `fhir.py`, `seed.py` |

### Commands run and results

| Command | Result |
| --- | --- |
| `make seed` | "Synthea patients loaded: 3000 (3923 bundles read, 923 deceased patients left out)". Generation took 132 s; a re-run that reuses the files takes 15 s |
| `make verify` | Exit 0. Lint and type checks clean (42 Python files). Backend: **120 passed, 0 skipped, coverage 99.9%** (gate 85%), 10 s. Frontend: **26 passed, 0 skipped, coverage 100%** (gate 80%). Placeholder check passed |
| `make e2e` | Exit 0. **2 passed, 0 skipped** |

Integration tests run on the real TimescaleDB container, one new database per test. They cover:

- migrations on an empty database, table columns, hypertables on `time`;
- each continuous aggregate against a small hand-made dataset after a manual refresh, with the expected
  numbers worked out by hand (for example p90 of 10, 20, 30, 40, 100 minutes = 76);
- a refresh policy job materializing data stamped 30 days in the future;
- the compression job compressing a 3-day-old chunk, with the data still readable;
- constraints rejecting invalid rows; no column named after the latent severity (§5.4);
- the seed loader, including a second run and a changed patient set.

### Evidence

- `docs/evidence/cp1/layout.png` — top-down drawing of all floors from `layout.json`: rooms, doors, beds,
  furniture, seats, work spots and the walking graph.
- `docs/evidence/cp1/schema.txt` — migrations, hypertables, continuous aggregates, policy jobs, beds per
  hospital and unit, patient count, read from the development database.
- `docs/evidence/cp1/patients_summary.txt` — patient count, age range, sex split, comorbidity
  distribution and the most common conditions.

### How to check it yourself (under 5 minutes)

1. Open `docs/evidence/cp1/layout.png` and compare the rooms and beds with the tables in PROMPT.md §3.
2. `make seed` — the last line says "Synthea patients loaded: 3000". The first run on a machine without
   `data/synthea/` downloads the jar and generates for about 2 minutes.
3. `docker compose -f infra/docker-compose.yml exec db psql -U twin -d twin -c "SELECT id, age, sex, comorbidity_count, conditions[1:2] FROM patients LIMIT 5"`
4. Same `psql` with `-c "SELECT view_name FROM timescaledb_information.continuous_aggregates"` — five views.
5. `env -u VIRTUAL_ENV uv run --directory backend python -m twin.sim.build_layout --check` — "is up to date".
6. `make verify` — ends with "make verify: all checks passed".

### Decisions made where the spec leaves room (please confirm or correct)

1. **`patients.fhir` holds a FHIR Bundle with the Patient and all Condition resources, not the whole
   Synthea bundle.** A whole bundle is 1 to 5 MB per patient (encounters, observations, claims). The
   table is 20 MB this way.
2. **Synthea options:** adults only (`-a 18-90`), because the fairness bands in §8 start at 18; one year
   of history exported (active conditions of any age are still exported), which cuts the generated files
   from about 22 GB to 3.8 GB. Deceased patients are not loaded. One patient is 17 on the sim start
   date (18th birthday the next day).
3. **Comorbidity count** = number of chronic disease groups (14 groups such as diabetes, hypertension,
   heart failure, chronic kidney disease, cancer) matched by the patient's active conditions. Social
   findings that Synthea records as conditions (employment, education, stress) are left out of
   `conditions`.
4. **`bed_state` is a snapshot table:** the simulation will write the state of every bed at each snapshot
   time, and `occupancy_15m` is the average number of occupied beds over the snapshots in the bucket.
5. **`er_wait_15m` reads `events` rows of kind `er_admit`** with `payload.wait_min`; `arrivals_hourly`
   reads kind `arrival` with `payload.mode`; `alerts_hourly` reads kind `alert` with `payload.level`.
   The simulation in CP2 writes these.
6. **Keys:** `beds` primary key is (hospital_id, bed_id), since all three hospitals share bed ids;
   patient ids are `P-0001` to `P-3000`; `hospitals.status` is one of open, diverting, offline.
7. **Positions the spec does not give** (work spots, the two triage seats, lounge seats, furniture sizes,
   ambulance slots) follow the prototype `reference/engine/pulse3d.js` where it has them. `layout.json`
   also lists furniture, so the 3D engine reads positions from it instead of hardcoding them.

### Deviations from spec

None beyond the decisions listed above.

### Known issues

None that block the checkpoint. One consequence to be aware of:

- The compression policy compresses chunks older than 1 day **by the wall clock**. Sim time starts today
  and runs faster than real time, so chunks written by the live sim are in the future and will not be
  compressed during the event. The policy is installed and tested with old data. If you want judges to see
  compressed chunks in the live demo, the options are a manual `compress_chunk` step in the demo script
  or loading a block of past history; say which you prefer and I will add it to CP9.

**Waiting for "approved CP1" before starting CP2.**
