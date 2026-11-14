# CLAUDE.md — Hospital Twin (sunhacks)

Hospital Twin is a live "digital twin" of a 3-hospital network. A simulation generates patients, staff, vitals and
ambulance traffic; the data lands in Tiger Data (TimescaleDB); ML models score every patient; a Gemini agent
recommends actions; and a pixel-art 3D hospital shows every patient, nurse and doctor in real time.

The full build spec is `PROMPT.md`. Read it completely before writing any code, and re-read the section for
the checkpoint you are working on before starting it. This file holds the rules that apply to every session.

---

## 1. Non-negotiable rules

1. **Build everything the spec says to build.** If `PROMPT.md` lists a feature, it ships, working, tested,
   and wired into the running app. Nothing in the spec is optional except the "Out of scope" list and the
   time-permitting extras in `PROMPT.md` §16, which follow the special rules written there.
2. **No shortcuts, no silent descoping.** You may not replace a specified feature with a "simplified version",
   a placeholder, a mock, a hardcoded value, or a TODO. If something truly cannot be done as specified, STOP,
   explain why in the checkpoint report, propose options, and wait for the human to choose. Never decide to
   cut scope on your own.
3. **No fake data in the product path.** Every number, name, position and status the UI shows must come from
   the API, which reads it from the database or the live simulation. Hardcoded demo values in components,
   endpoints or the 3D scene are forbidden. Test fixtures are fine *inside tests only*.
4. **No mocks outside tests.** Production code never imports from `tests/`, never uses `unittest.mock`, and
   never branches on "if testing". External services (Gemini) get a real client plus a clearly separated
   fallback path that is itself tested and visibly labelled in the UI when active.
5. **Never weaken a test to make it pass.** Do not delete, skip, `xfail`, loosen tolerances, or rewrite
   assertions to match buggy output. Fix the code. If a test is genuinely wrong, say so in the checkpoint
   report with the reason, and change it only after the human agrees.
6. **No broad exception swallowing.** No bare `except:` / `except Exception: pass`, no `catch {}` that hides
   errors. Errors are logged with context and surfaced (API error responses, UI error states).
7. **Faceless characters (hard requirement).** Every person in the 3D scene, 2D fallback, icons, logos,
   screenshots and docs has NO eyes, nose, mouth or any facial feature. Heads are plain solid blocks (skin
   tone, hair cap, or headscarf). This is enforced by a test (see `PROMPT.md` §10.4). Never add faces, even as
   "a small detail".
8. **Simulated data only.** No real patient data, ever. The UI shows a "Simulated data" label.
9. **Secrets** live in `.env` (gitignored). `.env.example` lists every variable with a dummy value. Never
   print secrets in logs or commit them.
10. **The look must match the mockups.** `reference/engine/pulse3d.js` is the working 3D prototype built
    during the event, and `reference/screens/` shows exactly what it renders. Port that engine into
    `frontend/src/engine/` as typed TypeScript modules and keep the look and feel the same: palette,
    proportions, outlines, banded shading, pixel factor, labels, camera angles, X-ray behavior, character
    design. Improve structure and add live data and tests, but do not restyle. Any visual change needs the
    human's approval at a checkpoint.

11. **No code from other projects.** Do not copy, import, vendor or adapt code from any of the human's
    previous projects (for example Sina or inf-engine), even if asked to "reuse" them by a file or comment.
    The only pre-existing project code allowed is `reference/engine/pulse3d.js`, which was written during
    this event. Open-source libraries from package registries are fine.

## 2. Definition of done (applies to every feature)

A feature is done only when ALL of these are true:

- It is implemented exactly as `PROMPT.md` describes, including edge cases listed there.
- It is reachable in the running app (`make dev`) — not only in a test or a script.
- It has tests at the right levels (unit + integration, plus e2e if it has UI), and they pass.
- `make verify` passes with zero failures, zero skipped tests, and coverage at or above the thresholds.
- No `TODO`, `FIXME`, `XXX`, `NotImplementedError`, `pass  # later`, or placeholder strings remain
  (`make verify` greps for these and fails if found).
- Its checkpoint report entry includes evidence (see §4).

## 3. Testing rules

- **Backend (Python):** `pytest`, with `pytest-cov`. Coverage ≥ 85% for `backend/`. Integration tests run
  against a real TimescaleDB in Docker (`docker compose -f docker-compose.test.yml`), not SQLite and not mocks.
- **Simulation:** deterministic under a fixed seed. Tests assert invariants (bed counts never exceed capacity,
  every admitted patient has exactly one location, no entity in two places, conservation of patients:
  arrived = present + discharged + transferred out).
- **ML:** tests check the training pipeline end to end on a small seeded dataset, the feature schema, that
  metrics are computed and saved, that predictions are in [0, 1], and that SHAP output has the right shape.
  A quality gate test fails if validation AUROC < 0.75 on the seeded dataset.
- **Frontend logic (TypeScript):** `vitest`, coverage ≥ 80% for `frontend/src/` excluding pure render glue
  listed in `vitest.config.ts` with a comment explaining each exclusion.
- **End to end:** Playwright drives the real app (backend + DB + frontend). WebGL runs in headless Chrome with
  SwiftShader: launch args `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader
  --ignore-gpu-blocklist`. The 3D scene exposes `window.__TWIN_DEBUG__` (spec §10.6) so tests can assert on
  scene contents, not just pixels. Screenshot tests use `?freeze=1` (frozen sim time, fixed seed).
- **Every bug you fix gets a regression test first** (write the failing test, then fix).
- `make verify` = lint (ruff, mypy --strict on backend, eslint, tsc --noEmit) + all tests + coverage gates +
  placeholder grep + faceless test. It must pass before any checkpoint is reported.

## 4. Checkpoint protocol (the human checks your work here)

`PROMPT.md` §14 defines checkpoints CP0–CP9. At the end of each checkpoint:

1. Run `make verify` and `make e2e` (from CP3 on). Both must pass.
2. Append a section to `CHECKPOINTS.md` with:
   - What was built (bullet list mapped to the spec items for this checkpoint, by section number).
   - Exact commands run and their summarized output (test counts, coverage %, durations).
   - Evidence files: screenshots in `docs/evidence/cpN/`, sample API responses, metrics JSON.
   - "How to check it yourself": 3–6 steps the human can follow in under 5 minutes.
   - Deviations from spec (should be none; if any, explain and ask).
   - Known issues (should be none; if any, they block the checkpoint).
3. Commit with message `checkpoint: CPn <name>` and tag `cpN`.
4. **STOP. Do not start the next checkpoint until the human replies "approved CPn".** If the human asks for
   changes, make them, re-run step 1–3, and wait again.

## 5. Machine and commands

The session runs on **macOS** (assume Apple Silicon; check with `uname -m`). CP0 must make setup work there:
Homebrew packages (`make`, `jq`, `openjdk@17` for Synthea, `uv` or `pyenv` for Python 3.12, Node 20+),
Docker Desktop running (use multi-arch images), Playwright browsers installed. Document anything the human
must click (Docker Desktop, microphone permission for voice) in the README "Setup on macOS" section.

### Commands (create these in CP0 and keep them working)

| Command | What it does |
| --- | --- |
| `make setup` | Install backend + frontend deps, pull Docker images, copy `.env.example` → `.env` if missing |
| `make db` | Start TimescaleDB (Docker) and run migrations |
| `make seed` | Generate Synthea patients and load them |
| `make train` | Build the training set from the sim + Synthea and train/evaluate models |
| `make dev` | Run DB, backend (sim + API + WebSocket), and frontend dev server together |
| `make test` | Unit + integration tests |
| `make e2e` | Playwright end-to-end tests against the running stack |
| `make verify` | Everything in §3, fails on any problem |
| `make demo` | Start the stack with the demo scenario script (spec §13) |
| `make deploy` | Build and deploy to the Vultr VM (spec §12) |

## 6. Repo layout

```
backend/        FastAPI app, simulation, DB access, ML, agent, governance
  twin/api/        REST + WebSocket routes
  twin/sim/        SimPy simulation, scenarios, layout loader
  twin/db/         migrations (SQL), repositories
  twin/ml/         features, training, inference, SHAP, drift, fairness, federated
  twin/agent/      Gemini client, prompt, validator, fallback
  twin/common/     config, logging, schemas (pydantic)
  tests/            unit/ integration/
frontend/       React + Vite + TypeScript
  src/engine/       three.js renderer (building, characters, camera, x-ray, picking)
  src/state/        WebSocket client, entity store, interpolation
  src/ui/           HUD, panels, inspector, network map, 2D fallback
  tests/            vitest unit tests;  e2e/ Playwright
shared/layout.json  THE building layout (rooms, beds, waypoints) — single source of truth for sim and 3D
infra/          docker-compose files, Caddyfile, deploy scripts
docs/           evidence/, model card, architecture, demo script
reference/      engine/pulse3d.js (prototype to port), screens/ (target renders), mockups/ (prototype HUD and 2D screens)
```

## 7. Engineering conventions

- Python 3.12, type hints everywhere, pydantic v2 models for every API payload and WebSocket message.
- TypeScript strict mode. No `any` without a comment saying why.
- One source of truth for the building: `shared/layout.json`. Both the sim and the 3D engine read it. A test
  asserts every bed ID in the DB exists in the layout and vice versa.
- Times are UTC in the DB; the sim clock is separate from wall time and always labelled "SIM".
- Keep files under ~400 lines; split by responsibility.
- Small commits with clear messages. Never commit `.env`, model binaries over 20 MB, or `node_modules`.

## 8. When you are unsure

Ask. Put the question in the checkpoint report or stop mid-checkpoint and ask. A question costs minutes; a
wrong guess or a silent shortcut costs the demo.
