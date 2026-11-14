# Hospital Twin

A live digital twin of a three-hospital network, built for sunhacks. A simulation generates patients,
staff, vitals and ambulance traffic; the data lands in Tiger Data (TimescaleDB); ML models score every
patient; a Gemini agent recommends actions; and a pixel-art 3D hospital shows every patient, nurse and
doctor in real time.

All data is simulated. No real patient data is used anywhere.

The build spec is [PROMPT.md](PROMPT.md), the working rules are [CLAUDE.md](CLAUDE.md), and progress is
recorded checkpoint by checkpoint in [CHECKPOINTS.md](CHECKPOINTS.md).

## Status

Done so far (details and evidence in [CHECKPOINTS.md](CHECKPOINTS.md)):

- **CP0 Scaffold:** repo layout, Makefile, Docker database, API with `/health`, frontend shell, lint, tests,
  coverage gates and CI.
- **CP1 Data layer:** `shared/layout.json` generated from the building tables, the full Tiger Data schema
  (hypertables, continuous aggregates, compression), and 3,000 Synthea patients for Phoenix.

The simulation, 3D scene, models and agent are built in CP2-CP9 as listed in PROMPT.md §14.

## Setup on macOS

Tested on Apple Silicon (arm64).

1. Install the tools with Homebrew:

   ```sh
   brew install make jq uv openjdk@17 node@20
   ```

   `uv` downloads Python 3.12 for the project by itself. `openjdk@17` is used by Synthea (`make seed`).
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and **start it** (click the
   Docker icon and wait until it says "running"). The database runs in Docker.
3. Install everything else:

   ```sh
   make setup
   ```

   This installs backend and frontend dependencies, downloads the Chromium build used by the end-to-end
   tests, pulls the TimescaleDB image, and creates `.env` from `.env.example` if you do not have one.
4. Start the app:

   ```sh
   make dev
   ```

   Open http://127.0.0.1:5173. The page shows the backend and database status read live from the API.
   Press Ctrl-C to stop the backend and frontend. `make db-down` stops the database.
5. Load the patients (once):

   ```sh
   make seed
   ```

   This downloads the Synthea 3.3.0 jar (183 MB, checksum verified), generates 3,000 living patients for
   Phoenix, Arizona with a fixed seed (about 2 minutes, 3.8 GB in `data/synthea/`, not committed) and loads
   them. Running it again reuses the generated files and takes about 15 seconds.

Ports used on your machine: 5173 (frontend), 8000 (backend), 5433 (development database),
5434 (test database).

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | Install backend + frontend deps, pull Docker images, copy `.env.example` → `.env` if missing |
| `make db` | Start TimescaleDB (Docker), run migrations, copy the building from `shared/layout.json` into the reference tables |
| `make dev` | Run DB, backend and frontend dev server together |
| `make test` | Unit + integration tests (integration tests use a real TimescaleDB in Docker) |
| `make e2e` | Playwright end-to-end tests against the running stack |
| `make verify` | Lint, type checks, all tests, coverage gates, skipped-test check, placeholder check |
| `make seed` | Generate Synthea patients and load them; prints the number loaded |
| `make train` | Train and evaluate the models (built in CP5) |
| `make demo` | Start the stack with the demo scenario (built in CP9) |
| `make deploy` | Build and deploy to the Vultr VM (built in CP8) |

A command marked "built in CPn" stops with an error message until that checkpoint is done.

## Repo layout

```
backend/        FastAPI app, simulation, DB access, ML, agent, governance (Python 3.12, uv)
frontend/       React + Vite + TypeScript, three.js 0.149.0
shared/         layout.json and ws_schema.json (generated)
infra/          docker-compose files, deploy files
docs/           evidence per checkpoint, model card, demo script
reference/      the 3D prototype, target renders and mockups made during the event
scripts/        checks used by make verify
```

## Configuration

Settings come from environment variables or `.env` (never committed). `.env.example` lists every
variable. Secrets are removed from log output.
