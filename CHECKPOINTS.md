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

**Approved by the human on 2026-11-14, with all seven decisions confirmed. Compression in the live demo
(the known issue above) is still open and will be settled when the data size is known.**

---

## CP2 — Simulation and stream (2026-11-14, hour 1.4 of 48; target hour 11)

Spec: PROMPT.md §5, §6. From this point the human asked to continue without stopping at checkpoints, so
this entry is a record, not a gate; CLAUDE.md's other rules still apply.

### What was built

| Spec | What | Where |
| --- | --- | --- |
| §5.1 | SimPy simulation, 1 tick = 1 sim minute, start 2026-11-14 08:00 Phoenix (15:00 UTC), speeds 1x/4x/8x, pause, freeze, fixed seed, same seed + same actions = identical event stream (tested by hashing the stream) | `backend/twin/sim/engine.py`, `world.py`, `config.py`; `backend/twin/api/runtime.py` |
| §5.2 | Three hospitals in Phoenix, different staffing and demand (Mercy busiest), 4 ambulances each, helicopter on Mercy's roof, city routes | `sim/config.py`, `sim/vehicles.py` |
| §5.3 | Walk-in arrivals (non-homogeneous Poisson by hour) and ambulance calls; journey arrive, waiting seat, triage, ER bay, discharge / ward / ICU / surgery -> recovery -> ward / transfer; boarding when a bed is full; cleaning after discharge; visitors in the waiting room; every patient is a Synthea patient | `sim/patients.py`, `arrivals.py`, `visitors.py`, `pools.py` |
| §5.4 | Hidden severity (mean-reverting random walk plus deterioration episodes, more likely with age, comorbidities, ESI 1-2, flu for respiratory cases), vitals every 5 sim min admitted and 15 waiting, critical event moves to ICU or rapid response. Never exposed (tests scan every payload and every model) | `sim/physiology.py`, `monitoring.py` |
| §5.5 | Nurse and doctor tasks, doctors round, surgeons go to the OR, EMTs wheel ambulance patients in, breaks in the lounge, prayer room at set times; every move has origin, destination, A* path over the waypoint graph, elevator for floors, duration from path length at 1.3 m/s | `sim/staff.py`, `pathing.py`, `vehicles.py` |
| §5.6 | Scenarios flu surge, mass casualty (12 trauma arrivals in 20 min plus a helicopter transfer), staff shortage (-30% nurses, 4 h), hospital offline; each writes an event, shows in the snapshot, and can be stopped | `sim/scenarios.py` |
| §5.7 | Actions divert ambulances, expedite discharge, move patient, call in staff, hold bed; invalid requests change nothing | `sim/actions.py` |
| §5.8 | Invariants checked every tick in tests and in debug mode (`SIM_DEBUG`) | `sim/invariants.py` |
| §4.1 | The simulation writes vitals, events, bed snapshots every 5 sim min, encounters and staff to Tiger Data; every control action is audited | `backend/twin/db/sim_writer.py` |
| §6.1 | WebSocket `/ws?hospital=<id>` (snapshot, then one events message per tick) and `/ws/network`; models in one file; `shared/ws_schema.json` generated from them; frontend types generated from the schema; `make verify` fails if either is stale | `backend/twin/common/ws.py`, `common/schema_gen.py`, `api/routes_ws.py`, `api/hub.py`, `frontend/src/state/wsTypes.ts` |
| §6.2 (CP2 part) | `GET /health`, `/hospitals`, `/hospitals/{id}/state`, `/patients/{id}`, `/patients/{id}/vitals` (from `vitals_5m`), `/patients/{id}/risk`, `/kpis/{hospital}` (from the continuous aggregates), `POST /sim/speed`, `/sim/pause`, `/sim/freeze`, `POST /scenario`, `DELETE /scenario/{id}` | `backend/twin/api/routes_*.py` |

The agent, governance and models endpoints (`/agent/*`, `/governance/*`, `/models`) belong to CP5 and CP6.

### Commands run and results

| Command | Result |
| --- | --- |
| `make verify` | Exit 0. Lint and `mypy --strict` clean (79 Python files). Backend **213 passed, 0 skipped, coverage 96.7%** (gate 85%), 75 s. Frontend 26 passed, coverage 100%. Schema, layout and type files up to date. Placeholder check passed |
| `make e2e` | Exit 0. 2 passed |
| 30 sim days headless, invariants checked every tick | Passes, about 8 s |
| Live API run | warm-up of 72 sim hours takes 1.2 s; snapshot of Mercy has 30 entities and 29 beds; events stream one message per tick |

### Evidence

`docs/evidence/cp2/`: `health.json`, `snapshot_mercy_excerpt.json`, `stream_sample.txt`,
`scenario_flu_surge.json`, `kpis_mercy.json`, `audit_log.txt`.

### How to check it yourself

1. `make dev`, then `curl -s localhost:8000/health` shows `"sim":"running"` and the sim time.
2. `curl -s localhost:8000/hospitals/mercy/state | python3 -m json.tool | head -60`
3. `curl -s -XPOST localhost:8000/scenario -H 'content-type: application/json' -d '{"name":"flu_surge","hospital_id":"mercy"}'`, then watch `curl -s localhost:8000/hospitals` (the waiting count and ER wait for Mercy rise over a few minutes at `-d '{"speed":8}'` to `/sim/speed`).
4. `curl -s -XPOST localhost:8000/sim/pause -H 'content-type: application/json' -d '{"paused":true}'`
5. `make verify`.

### Decisions where the spec leaves room

1. **Warm-up:** each backend start simulates 72 sim hours first (1.2 s) so the hospitals are busy at 08:00;
   the previous run's rows are removed (`SIM_RESET_ON_START`). The visible run starts at 08:00 Phoenix.
2. **Mass casualty** takes an incident location (lat, lon) and uses the nearest hospital, as agreed.
3. **Helicopter** flights take at least 3 sim minutes so short hops are visible.
4. Demand and length-of-stay numbers were tuned so each hospital stays stable over 30 sim days.
5. `kpis.alerts` is 0 until CP5 (alerts come from the risk model).

### Needed from the human for later checkpoints (PROMPT.md §14.1)

A Gemini API key (CP6), a Tiger Cloud connection string, a Vultr VM with SSH access, and the registered
domain with DNS access (CP8). Until then the local Docker database and the rules fallback are used.

### Deviations and known issues

None.

---

## CP3 — 3D scene (2026-11-14, hour 1.9 of 48; target hour 16)

Spec: PROMPT.md §10.2-§10.5, §10.4, §10.6 (debug API). Recorded as a log, not a gate (the human asked to
continue without stopping at checkpoints).

### What was built (`frontend/src/engine/`)

| Spec | What | File |
| --- | --- | --- |
| §10.2 | Palette, the three styles (`iso`, `classic`, `neon`; `gameboy` not ported), toon gradient (NearestFilter), outlines, 16 px floor textures, pixel factor 2 (1 to 4), canvas at 1/factor resolution upscaled with `image-rendering: pixelated`, antialias off | `palette.ts`, `materials.ts`, `engine.ts` |
| §3, §10.2 | Building read from `shared/layout.json`: slabs, room floors, interior walls derived from rooms and door gaps (equal to the prototype's hardcoded walls, tested), exterior walls with window bands and the entrance gap, stairs, glass elevator shaft and car, furniture, beds, roof with helipad and helicopter, street, ambulance bay, parking, trees | `building.ts`, `walls.ts`, `furniture.ts`, `beds.ts`, `scenery.ts`, `layout.ts` |
| §10.2 | Room labels (512 x 128 canvases) with live counts ("ICU 4/6"), entrance sign with the hospital name from the data | `labels.ts`, `labelsLive.ts` |
| §10.3, §10.4 | Faceless voxel characters (13 allowed parts), role colors, walking / standing / seated / lying poses, bedside monitor with risk color, blinking and "!" for high risk; `characterFactory` exposes its part names; `auditFace()` checks every character | `characters.ts`, `beds.ts` |
| §10.5 | Isometric orthographic (azimuth 45, elevation 26.565 degrees) and free-fly perspective cameras, WASD / E / Q / Shift / wheel / drag on the canvas (not the window), 9 presets eased over 1.2 s, floor cutaway, exploded (6 m gap), X-ray (walls 7%, floors 55%, outlines faint, shell stops casting shadows, floors spread 3.5 m, markers always visible), night mode, picking | `camera.ts`, `xray.ts`, `picking.ts`, `engine.ts` |
| §10.6 | Live binding: entity layer creates, updates and removes characters from entities, moves them along server paths (`motion.ts`), riders in the elevator, `window.__TWIN_DEBUG__` with `entities()`, `counts()`, `beds()`, `view()`, `xray()`, `selected()`, `faceAudit()`, `frameStats()` | `entities.ts`, `motion.ts`, `debug.ts` |
| §10.5 pitfalls | Each has a regression test: negative frame delta, ASCII preset ids with separate labels, X-ray spread and 7% walls, pixel factor 2, 512 x 128 labels, shell materials `depthWrite: false` | `tests/engine/*`, `e2e/scene.spec.ts` |

The scene is rendered from `frontend/tests/fixtures/snapshot_mercy.json`, a snapshot recorded from the real
simulation by `backend/tests/record_fixture.py` (tests only; risk scores in it are fixed fake values because
the models come in CP5). The product app does not load the fixture; the test page is
`frontend/tests/harness/`.

### Bug found and fixed on the way

The layout generator rotated beds 180 degrees compared with the prototype (head north must be rotation 0).
Found by comparing the render with the reference; fixed in `layout_parts.py`, with the layout test updated.

### Commands run and results

| Command | Result |
| --- | --- |
| `make verify` | Exit 0. Backend 213 passed, coverage 96.7%. Frontend **97 passed, 0 skipped, coverage 97.6%** (gate 80%; `engine.ts` is excluded because jsdom has no WebGL, see `vitest.config.ts`; its behavior is covered by the Playwright tests). Faceless test step passed. Lint, `mypy --strict`, eslint, tsc clean |
| `make e2e` | Exit 0. **14 passed, 0 skipped** (2 smoke + 12 scene tests) in headless Chrome with SwiftShader |

### Evidence

- `docs/evidence/cp3/parity/side-by-side-*.png`: our render next to the matching `reference/screens` image
  for all 12 reference screens (same camera presets and style, `?freeze=1`).
- `docs/evidence/cp3/outside.png`, `ground-floor.png`, `xray-icu-closeup.png`: the three required screenshots.

### How to check it yourself

1. Open `docs/evidence/cp3/parity/side-by-side-11-isometric-floor2-default-view.png` (default view) and a few others.
2. `make verify` (includes the faceless test) and `make e2e`.
3. For a live look: `cd frontend && npm run dev`, open
   http://127.0.0.1:5173/tests/harness/index.html?preset=floor2 (iso) or `&cam=free&xray=1&night=1`.
   Drag to rotate, WASD to pan, wheel to zoom (click the scene first so it has focus).

### Decisions where the spec leaves room

1. Room-label count colors: green under 60% full, amber 60-85%, red above (the prototype's were hand-picked).
2. The moving car on the street is a plain civilian car; ambulances and the helicopter come from live vehicle
   data (CP4), not from scenery.
3. Bedded patients whose risk is not scored yet show a dark monitor and a neutral gray marker.
4. Bed `rotation` in `layout.json`: 0 = head at the north end, pi = head at the south end.

### Deviations and known issues

None. Visual differences from the references are limited to people and furniture states that come from
live data (the references had hand-placed demo people), and the missing ambulance at the bay (CP4).

---

## CP4 — Live end to end (2026-11-14, hour 2.5 of 48; target hour 21)

Spec: PROMPT.md §10.1, §10.6, §11 e2e 1-6, 8, 10. Recorded as a log, not a gate.

### What was built

| Spec | What | Where |
| --- | --- | --- |
| §10.6 | Client store: applies the snapshot, then each events message (pure reducers); keeps sim time between ticks at the current speed; reconnects with backoff and resyncs from a fresh snapshot; "Disconnected" banner while offline; server and parse problems are shown, not hidden | `frontend/src/state/{reducers,store,socket,clock,feed,api}.ts`, `ui/common.tsx` |
| §10.1 screen 1 | Network map: pixel-art city on a canvas, three hospitals with capacity and status pills (OK, BUSY, CRITICAL, OFFLINE as text), live ambulances and helicopter on streets, routes of ambulances carrying patients, side panel with hospitals and incoming ambulances, click a hospital to open it | `ui/network/*` |
| §10.1 screen 2 | Hospital 3D view driven by the live sim: KPI strip, live feed, patient inspector (live vitals from the stream, 6-hour heart-rate and risk sparklines from `/patients/{id}/vitals` and `/risk`, FHIR id, top factors when a model scores them, "Fly to this bed"), presets, X-ray legend, speed and pause, scenario menu, camera mode, night, pixel factor | `ui/hospital/*` |
| §10.1 screen 3 | 2D floor plan fallback from the same store; used automatically, with a banner, if WebGL cannot start | `ui/hospital/FloorPlan.tsx` |
| §10.6 | Moves animate along the server paths between depart and arrive; walking EMTs escort ambulance patients in; ambulances park in the bay slots; the helicopter is on the roof only while home; `window.__TWIN_DEBUG__` is always present | `engine/entities.ts`, `engine/vehicles.ts`, `engine/debug.ts` |
| backend | Emergency scenes snap to a street grid through the three hospitals so ambulances drive on streets; bed and ambulance-slot rotations fixed to match the prototype | `sim/vehicles.py`, `sim/layout_parts.py` |

### Commands run and results

| Command | Result |
| --- | --- |
| `make verify` | Exit 0. Backend 214 passed, coverage 96.7%. Frontend **146 passed, 0 skipped, coverage 91%** (gate 80%). Faceless step, schema, layout and type sync checks pass |
| `make e2e` | Exit 0. **25 passed, 0 skipped** in 2.1 min: 2 smoke, 12 scene (fixture), 11 live against the real backend and database |

The live tests use no fixture: every expected value comes from the backend API. They cover e2e 1, 2, 3, 4, 5,
6, 8 and 10 from §11, plus: walkers change position frame by frame, the 2D plan matches the live state and
works with WebGL disabled, and the network map shows ambulances with their patients.

### Evidence (`docs/evidence/cp4/`)

`network-map.png`, `network-map-live.png`, `inspector.png`, `ground-floor-live.png`, `xray-floor3.png`,
`floor-plan.png`, `disconnected.png`.

### How to check it yourself

1. `make dev`, open http://127.0.0.1:5173 : the city with three hospitals; ambulances drive between them.
2. Click Mercy General: the 3D hospital. Click "Floor 3", then a patient in a bed: the inspector shows their
   id, bed, age, live vitals and charts. Press 8x to watch people walk.
3. Click "2D plan" for the floor plan. Press X-ray, Night, Free-fly camera.
4. Stop the backend (Ctrl-C the `uvicorn` process): a red "Disconnected" banner appears; start it again and it
   resyncs.
5. `make verify` and `make e2e`.

### Decisions where the spec leaves room

1. Patients walking to a bed are drawn walking until they arrive, then lying in the bed. The API marks the
   bed occupied from the start of the walk, so e2e 3 compares only patients who have arrived.
2. Time in the browser: 1x is 60 sim seconds per real second, so a 20 m walk takes about a quarter second at
   1x. That follows from "1 tick = 1 sim minute, 1 tick per real second".
3. Hospital status pill by load: CRITICAL at 90%, BUSY at 70%; OFFLINE when it takes no ambulances.
4. The agent card, recommendations and governance drawer belong to CP6 and are not on screen yet.
5. The sim restarts from the 08:00 start on every backend start (SIM_RESET_ON_START).

### Deviations and known issues

None. One test (X-ray) was seen failing once under heavy load during an earlier run; it passed on every rerun
and in the final 25-test run. Watch it if CI becomes flaky.

---

## CP5 — Machine learning (2026-11-14, hour 3.3 of 48; target hour 26)

Spec: PROMPT.md §7.1-§7.4. Recorded as a log, not a gate.

### What was built (`backend/twin/ml/`)

| Spec | What | File |
| --- | --- | --- |
| §7.1 | `make train` runs the sim headless and fast (30 sim days x 3 hospitals, seed 20261114, about 8 s) and builds one row per waiting or admitted patient per 30 sim minutes; label: a critical event in the next 6 sim hours. A few flu surges are included | `dataset.py`, `observe.py` |
| §7.2 | Features: latest vitals, 1 h and 2 h deltas, rolling min and max of SpO2, HR and RR over 2 h, NEWS2, age, sex, comorbidities, unit, hours since admission, ESI (29 in all). No latent severity, no future data; a test appends future readings and checks nothing changes, another changes the hidden physiology and checks nothing changes | `features.py` |
| §7.2 | LightGBM, isotonic calibration, time-based split (60/20/20 by sim time), metrics for the model and for NEWS2 alone: AUROC, AUPRC, Brier, calibration curve; quality gates (AUROC >= 0.75 and beats NEWS2) as tests and in `make train` | `train.py`, `metrics.py`, `model.py`, `cli.py` |
| §7.2 | SHAP TreeExplainer: top 3 factors per prediction, readable names, signed shares; levels high >= 0.70, medium >= 0.45 | `model.py` |
| §7.2 | Model card with data, features, metrics, fairness by age band and sex, limits | `card.py` -> `docs/model_card.md` |
| §7.3 | Hourly arrivals forecast for the next 6 h, must beat seasonal naive (gate); capacity projection "hours until full" per unit | `forecast.py` |
| §7.4 | Live scoring every 5 sim minutes (risk events, alert on entering high), forecasts every 15; risk scores and forecasts stored in `risk_scores` and `forecasts`; scores shown in the inspector, monitors, markers, "!" signs, ALERTS KPI; forecast panel and model badge | `inference.py`, `api/routes_ml.py`, `frontend/src/ui/hospital/MlPanels.tsx` |
| §6.2 | `GET /models` (versions, metrics, active models), `GET /forecast/{hospital}` (read from the `forecasts` table) | `api/routes_ml.py` |

The trained models are committed in `models/` (a few hundred kilobytes, plain text and JSON, no pickles), so
`make dev` scores patients without training first. `make train` rebuilds them.

### Results (`make train`, 13 s)

| | Model | NEWS2 alone |
| --- | --- | --- |
| Validation AUROC | **0.940** | 0.893 |
| Test AUROC | **0.910** | 0.845 |
| Test AUPRC | 0.351 | 0.163 |
| Test Brier | 0.0225 | 0.0263 |

Data: 120,231 rows, 2,804 positive (2.3%). Arrivals forecast MAE 0.785 against
1.036 for seasonal naive (24% better). Largest AUROC gap between groups on the
test split: 0.048.

### Commands run and results

| Command | Result |
| --- | --- |
| `make train` | Exit 0, all gates met (output above) |
| `make verify` | Exit 0. Backend **279 passed**, coverage 96.3%. Frontend 149 passed, coverage 91%. Lint, `mypy --strict`, faceless, schema and layout checks pass |
| `make e2e` | Exit 0. **26 passed, 0 skipped** (the new live test checks scores, factors, forecast, model version and alerts against the API) |

### Evidence

`models/lgbm-v1/metrics.json` (full metrics, calibration curves, fairness, feature importance),
`models/arrivals-lgbm-v1/metrics.json`, `docs/model_card.md`, `docs/evidence/cp4/risk-inspector.png`.

### How to check it yourself

1. `make train`: ends with the metrics against NEWS2 and the forecast against the baseline.
2. Open `docs/model_card.md`.
3. `make dev`, open a hospital, click a patient: score, level, model version and three factors.
   The left panel shows "Risk model lgbm-v1" and the 6-hour forecast with hours until each unit is full.
4. `curl localhost:8000/models` and `curl localhost:8000/forecast/mercy`.

### Decisions where the spec leaves room

1. Factors are shown as signed shares of the total SHAP contribution (between -1 and 1), because raw SHAP
   values are in log-odds and one factor can be 3.0.
2. Scoring starts 6 sim hours before the 08:00 start, so risk charts have history when the page opens.
3. Calibration uses the validation split (also used for early stopping); calibration and Brier are reported on the
   untouched test split.
4. The capacity projection's expected discharges use historical departure rates per occupied bed now; CP7
   replaces them with length-of-stay predictions through the `discharge_rate` argument (already tested).
5. The audit log entry per inference batch (PROMPT.md §8) comes with the governance work in CP6.

### Deviations and known issues

None.

---

## CP6 — Agent and governance

### What was built

- §9 Operations agent (`backend/twin/agent/`): summary of one hospital (flat named metrics), Gemini structured
  output, grounding validator (every cited metric must match the input, targets valid per action), one retry with
  the errors, rules-engine fallback labelled "Rules engine — Gemini unavailable". Runs every 15 sim minutes, when a
  scenario starts, and when a unit is projected full within 4 h. Recommendations are stored in `agent_recs`;
  approve applies the action to the sim and writes the audit log. `GEMINI_MODEL` comes from the environment.
- §6.2 `/agent/recs`, approve, dismiss; `/governance/drift`, `/fairness`, `/audit`, `/model-card`.
- §8 Drift (PSI per feature per hospital over 2 sim h, alert above 0.2, per-hospital baselines), fairness (hourly,
  by age band and sex), audit rows (drift alerts, fairness reports, inference batches, agent and user actions).
  Flu surge now shifts respiratory vitals so the drift test is meaningful.
- UI: Agent panel (approve / dismiss, cited metrics, fallback label), Governance drawer (drift heatmap, fairness
  table, audit log with filters, model card link), drift alerts and recommendations in the live feed.
- `make verify-live`: one real Gemini call on a live sim summary, checked for grounding (skips without a key).
- Ruff line length raised from 110 to 150 (style only).

### Commands run and results

| Command | Result |
| --- | --- |
| `make verify` | Exit 0. Backend **347 passed**, coverage 96.25%. Frontend **168 passed**, coverage 91.8%, 0 skipped |
| `make e2e` | Exit 0. **27 passed, 0 skipped**, including test 7 (flu surge, drift alert, recommendation, approve, audit) |

### Evidence

`docs/evidence/cp6/agent-panel.png`, `governance-drift.png`, `governance-audit.png`.

### How to check it yourself

1. `make dev`, open Mercy, press Scenario → Flu surge, speed 8x.
2. Within a minute the Agent panel shows recommendations with cited numbers and the rules-engine label.
3. Approve one: the sim changes (e.g. Mercy goes to DIVERTING) and the Governance → Audit log shows it.
4. Governance → Drift: respiratory cells (spo2, rr) turn red. Fairness shows AUROC by group.

### Deviations and known issues

Gemini has not been run live (no key yet): tests use recorded response fixtures and a fake client, and the
rules engine is what the app shows. Add `GEMINI_API_KEY` and `GEMINI_MODEL` to `.env` and run `make verify-live`.
