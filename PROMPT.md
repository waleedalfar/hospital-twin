# PROMPT.md — Build Hospital Twin

You are building **Hospital Twin**, a live digital twin of a three-hospital network, for the sunhacks hackathon.
Read `CLAUDE.md` first: its rules (no shortcuts, tests, checkpoints, faceless characters) apply to
everything below. Build in the checkpoint order in §14 and stop for human approval after each checkpoint.

Section numbers matter: checkpoint reports must map work to them (for example "§6.3 done").

---

## 1. What we are building

A judge opens Hospital Twin and sees a pixel-art city with three hospitals and ambulances driving between them.
They click **Mercy General** and fly into a pixel-art 3D model of the hospital: three floors plus a roof
helipad, with faceless voxel patients, nurses, doctors, EMTs and visitors moving through it in real time.
They turn on **X-ray** and see through every wall. Every person is a live record: click a patient in an ICU
bed and see live vitals, a risk score, and the top reasons the model flagged them. They press **Flu surge**:
the waiting room fills, ambulances queue, the drift monitor fires, and the Gemini agent recommends diverting
ambulances to St. Luke's, citing exact numbers. They approve it and watch the ambulances reroute.

Everything shown is produced by a running simulation, stored in Tiger Data, scored by models trained during
the event, and streamed to the browser. Nothing on screen is hardcoded.

### Prize tracks this must satisfy
- **Tiger Data:** all time-series (vitals, events, bed state, risk scores) in hypertables; dashboards read
  continuous aggregates; compression policy on vitals. Production uses a Tiger Cloud service.
- **Gemini API:** the operations agent (§9) uses Gemini with structured output.
- **Vultr:** production runs on a Vultr VM (§12).
- **GoDaddy Registry:** production is served on a registered domain over HTTPS.
- README has a section per track describing exactly how it is used, with file paths.

## 2. Architecture

```
 Synthea (FHIR bundles) ──► loader ──► Tiger Data (TimescaleDB)
                                          ▲      │
 SimPy simulation (3 hospitals) ──writes──┘      │ continuous aggregates
   │  ▲                                          ▼
   │  └── actions (approved agent recs, scenarios) ◄── FastAPI ──► REST
   │                                                 │  WebSocket /ws  (snapshot + events)
   ├─► ML inference (deterioration, ER forecast) ────┤
   └─► Governance (audit, drift, fairness) ──────────┤
       Gemini ops agent (+ rules fallback) ──────────┘
                                                     ▼
                         React + three.js frontend (network map, 3D hospital, panels)
```

One backend process runs the simulation loop, inference, agent scheduling and the API (asyncio). The sim
advances in ticks; after each tick the backend writes to the DB and broadcasts to WebSocket clients.

**Stack:** Python 3.12, FastAPI, SimPy, asyncpg + SQL migrations, LightGBM, SHAP, scikit-learn, pandas,
PyTorch (CPU) + Flower (`flwr`) for federated learning, google-genai SDK; React 18 + Vite + TypeScript, three.js **pinned to 0.149.0** (the version the prototype
uses; later versions change color management and would shift every color), zustand; Playwright, pytest, vitest; Docker
Compose; Caddy.

## 3. The building layout (`shared/layout.json`)

All three hospitals use the same building template (different staffing and demand). Units are meters.
The footprint is x ∈ [-20, 20], z ∈ [-14, 14]. +z is south (street side). Floor height 3.4 m, slab 0.3 m,
wall height 3.0 m. A corridor runs east–west on every floor at z ∈ [-2, 2], x ∈ [-20, 17]. Stairs occupy
x ∈ [-20, -17] in the corridor; the elevator shaft is x ∈ [17, 20], z ∈ [-2, 2].

`layout.json` must contain: floors → rooms (id, name, unit, rectangle, floor color key), doors (wall,
interval), beds (id, room, x, z, rotation), seats (id, room, x, z, facing), work spots (id, room, x, z),
and the waypoint graph (nodes with x, z, floor; edges). Generate it with a script (`backend/twin/sim/
build_layout.py`) from the tables below; a test checks the generated file against these tables.

### Floor 0 — Ground
| Room | Rect (x1,x2,z1,z2) | Door gap | Contents |
| --- | --- | --- | --- |
| ER | -20,-4,-14,-2 | north corridor wall x -13..-10 | 6 bays ER-1..ER-6 at x = -18 + 2.6·i, z = -12.4, head north; curtains between bays |
| Imaging | -4,8,-14,-2 | x 0..3 | CT scanner + table centered (2, -9) |
| Pharmacy | 8,20,-14,-2 | x 12..14.5 | 3 shelf units at x = 11, 14, 17 |
| Triage | -20,-4,2,14 | south corridor wall x -13..-10 | desk (-12, 6), 2 seats |
| Waiting | -4,8,2,14 | x -2..4 | 12 seats: x = -2.5 + 1.7·k (k=0..5), z = 7 and 10, facing north |
| Reception | 8,20,2,14 | x 10..13; opening to Waiting in wall x=8 at z 5..9 | desk along x = 18; main entrance in south exterior wall x 12..16 |

Outside: ambulance bay centered (14, 20); street along z = 28.

### Floor 1 — Wards
| Room | Rect | Doors | Contents |
| --- | --- | --- | --- |
| Ward A | -20,6,-14,-2 | x -14..-11 and -1..2 | WARD-1..8 at x = -18.5 + 2.9·i, z = -12.4, head north |
| Surgery (OR-1) | 6,20,-14,-2 | x 10..13 | operating table (13, -8), lamp, anesthesia machine |
| Ward B | -20,6,2,14 | x -14..-11 and -1..2 | WARD-9..14 at x = -18.5 + 3.0·i, z = 12.4, head south |
| Recovery | 6,20,2,14 | x 10..13 | REC-1..3 at x = 9 + 3.5·i, z = 12.4, head south |

### Floor 2 — Critical care and support
| Room | Rect | Doors | Contents |
| --- | --- | --- | --- |
| ICU | -20,6,-14,-2 | x -14..-11 and -1..2 | ICU-1..6 at x = -18.5 + 3.6·i, z = -12.4, glass partitions between beds |
| Lab | 6,20,-14,-2 | x 10..13 | two benches (z = -9, -6) with equipment |
| Staff lounge | -20,-4,2,14 | x -13..-10 | couch, table, vending machine |
| Prayer room | -4,6,2,14 | x 0..3 | 8 prayer rugs in 2 rows, shoe shelf |
| Admin | 6,20,2,14 | x 10..13 | 5 desks with monitors and chairs |

Roof: helipad (12 × 12) centered (6, 0); helicopter parked on it; HVAC units; elevator machine room.

Capacity per hospital: ER 6, Ward 14, Recovery 3, ICU 6 (29 beds), OR 1, Waiting 12 seats, Triage 2.

## 4. Data layer (Tiger Data)

### 4.1 Tables (migrations in `backend/twin/db/migrations/*.sql`, applied in order, idempotent)
Reference tables: `hospitals(id, name, lat, lon, status)`, `units`, `rooms`, `beds(bed_id, hospital_id,
room_id, unit, floor, x, z, rotation)`, `staff(id, hospital_id, role, unit, name_code)`,
`patients(id, synthea_id, fhir jsonb, age, sex, comorbidity_count, conditions text[])`,
`encounters(id, patient_id, hospital_id, arrived_at, mode, esi, disposition, ended_at)`.

Hypertables (time column `time`, timestamptz):
- `vitals(time, patient_id, hospital_id, hr, spo2, sbp, dbp, temp, rr)`
- `events(time, hospital_id, kind, entity_id, payload jsonb)` — moves, arrivals, transfers, alerts, scenario changes
- `bed_state(time, bed_id, hospital_id, patient_id, state)` — state ∈ occupied, cleaning, open, blocked
- `risk_scores(time, patient_id, hospital_id, model_version, score, level, top_factors jsonb)`
- `forecasts(time, hospital_id, model_version, horizon_h, metric, value)`
- `agent_recs(time, id, hospital_id, source, payload jsonb, status)`
- `audit_log(time, actor, action, payload jsonb)`
- `drift(time, hospital_id, feature, psi)`

Indexes on (patient_id, time DESC) and (hospital_id, time DESC) where queried.

### 4.2 Continuous aggregates (with refresh policies)
- `occupancy_15m` — beds occupied per unit per hospital per 15 min
- `er_wait_15m` — avg and p90 minutes from arrival to ER bay
- `arrivals_hourly` — arrivals per hospital per hour by mode (walk-in, ambulance, air)
- `alerts_hourly` — risk alerts per hospital per hour by level
- `vitals_5m` — per-patient 5-minute averages (used by the inspector sparkline)

Compression policy on `vitals` and `events` for chunks older than 1 day (sim time maps to real timestamps;
see §5.1). Tests verify each aggregate returns correct values for a seeded dataset after manual refresh.

### 4.3 Synthea
`make seed` downloads the Synthea release jar, generates ~3,000 patients for Phoenix, Arizona with a fixed
seed, and loads Patient + Condition resources into `patients` (raw bundle in `fhir`, extracted age, sex,
conditions, comorbidity_count). The simulation draws arriving patients from this pool, so every sim
patient has a real FHIR record. The inspector shows `FHIR Patient/<id>`.

Local dev uses the `timescale/timescaledb` Docker image. Production uses a Tiger Cloud service via
`DATABASE_URL`. The same migrations run on both.

## 5. Simulation (`backend/twin/sim/`)

### 5.1 Clock and control
- One tick = 1 sim minute. Speeds: 1x = 1 tick per real second, 4x, 8x, plus pause. Speed and pause are
  controlled over the API and shown in the UI.
- Sim time starts at a fixed date (2026-11-14 08:00 local) and is stored as real timestamps.
- Deterministic: a seed fixes all randomness. Same seed + same actions ⇒ identical event stream (tested).
- `?freeze=1` / `POST /sim/freeze` holds time for screenshot tests.

### 5.2 Hospitals and city
Three hospitals on a city grid: Mercy General, St. Luke's, Desert Valley (fictional, placed in Phoenix
coordinates in `layout.json`). Different staffing levels and baseline demand (Mercy busiest). Ambulances
(4 per hospital) and one helicopter (Mercy roof) exist as entities.

### 5.3 Patient flow
Arrivals: non-homogeneous Poisson by hour of day per hospital, split walk-in / ambulance. Each arrival
gets a Synthea patient, an ESI level (1–5) and a hidden severity process. Journey:
`arrive → waiting seat → triage → ER bay → disposition`, where disposition is discharge, admit to ward,
admit to ICU, surgery (OR → recovery → ward), or transfer to another hospital. When the needed bed is full
the patient waits (boarding), which drives ER wait times. Discharges free beds after a cleaning period.
Visitors arrive with some admitted patients and sit in the waiting room.

### 5.4 Physiology and deterioration
Each patient has a latent severity s(t) following a mean-reverting random walk with occasional
deterioration episodes (more likely with age, comorbidities, ESI 1–2, and during flu surge for respiratory
cases). Vitals are generated from s(t) plus noise every 5 sim minutes for admitted patients and every
15 minutes in the waiting room. A **critical event** (escalation to ICU or rapid response) fires when s(t)
crosses a threshold; it moves the patient to ICU if a bed is free. These events are the ML labels.
**The latent severity is never written to the DB or exposed by the API** (a test checks the API payloads
and DB columns).

### 5.5 Staff behavior
Nurse ratios: ICU 1:2, ward 1:5, ER 1:3, recovery 1:2; doctors round on their units; surgeons run the OR;
EMTs ride ambulances and wheel patients from the bay to the ER. Staff move between rooms to do tasks (vitals,
meds, admissions). Moves are real sim state: every move has an origin, a destination, a path through the
waypoint graph (A* over `layout.json`; elevator for floor changes) and a duration from path length at
1.3 m/s. Staff go to the staff lounge on breaks and to the prayer room at scheduled times.

### 5.6 Scenarios (`POST /scenario`)
- **Flu surge:** arrivals ×2.5 for 3 sim hours, mostly respiratory, higher deterioration rate.
- **Mass casualty:** 12 trauma arrivals over 20 sim minutes at the nearest hospital, plus 1 helicopter
  air transfer to the Mercy roof (helicopter animates in 3D).
- **Staff shortage:** −30% nurses at one hospital for 4 sim hours.
- **Hospital offline:** one hospital stops taking ambulances; ambulances reroute.
Each scenario writes an event, shows in the UI, and can be stopped.

### 5.7 Actions the sim accepts
Applied when a human approves an agent recommendation: divert ambulances (hospital, duration), expedite
discharge (patient ids), move patient (patient, bed), call in staff (hospital, unit, count), hold bed
(bed, minutes). Each produces visible changes and an audit entry.

### 5.8 Invariants (tested every tick in tests, and asserted in debug mode)
No bed holds two patients; every present patient has exactly one location; patients are conserved
(arrived = present + discharged + transferred out); bed counts never exceed capacity; staff locations are
valid layout spots.

## 6. Streaming API (`backend/twin/api/`)

### 6.1 WebSocket `/ws?hospital=<id>` — message schema version 1
On connect: a `snapshot`. Then after every tick: an `events` message. Pydantic models generate a JSON
Schema at `shared/ws_schema.json`; the frontend types are generated from it (tested to be in sync).

```json
{ "v": 1, "type": "snapshot", "sim_time": "2026-11-14T14:32:00Z", "speed": 4, "paused": false,
  "hospital": { "id": "mercy", "name": "Mercy General", "status": "open" },
  "entities": [
    { "id": "P-0412", "kind": "patient", "location": { "floor": 2, "room": "ICU", "bed": "ICU-3", "spot": null },
      "appearance": { "skin": 1, "hair": 3, "headscarf": false },
      "risk": { "score": 0.81, "level": "high", "top_factors": [["SpO2 drop, 2h", 0.21], ["HR trend", 0.14], ["Resp. rate", 0.09]] },
      "vitals": { "hr": 118, "spo2": 88, "sbp": 104, "dbp": 66, "temp": 38.4, "rr": 24 } },
    { "id": "N-14", "kind": "nurse", "location": { "floor": 2, "room": "ICU", "bed": null, "spot": "ICU-ws-2" },
      "appearance": { "skin": 3, "hair": 0, "headscarf": true } }
  ],
  "beds": [ { "id": "ICU-3", "patient_id": "P-0412", "state": "occupied" } ],
  "kpis": { "census": 22, "capacity": 29, "er_wait_min": 41, "waiting": 7, "alerts": 1 } }
```

```json
{ "v": 1, "type": "events", "sim_time": "2026-11-14T14:33:00Z",
  "events": [
    { "kind": "move", "entity_id": "N-14", "from": {...}, "to": {...}, "path": ["f2-icu-door", "f2-c-3", "f2-c-6"], "depart": "...", "arrive": "..." },
    { "kind": "vitals", "patient_id": "P-0412", "vitals": {...} },
    { "kind": "risk", "patient_id": "P-0412", "score": 0.83, "level": "high", "top_factors": [...] },
    { "kind": "bed", "bed_id": "WARD-3", "patient_id": null, "state": "cleaning" },
    { "kind": "arrival" | "discharge" | "transfer" | "alert" | "scenario" | "agent_rec" | "ambulance", ... }
  ], "kpis": {...} }
```

A separate `/ws/network` stream carries the city view: hospital statuses and occupancy, and ambulance and
helicopter positions and routes.

### 6.2 REST (all JSON, all typed)
`GET /health`, `GET /hospitals`, `GET /hospitals/{id}/state`, `GET /patients/{id}` (FHIR id, encounter,
latest vitals, risk), `GET /patients/{id}/vitals?window=6h` (from `vitals_5m`),
`GET /patients/{id}/risk?window=6h`, `GET /kpis/{hospital}` (from continuous aggregates),
`POST /sim/speed`, `POST /sim/pause`, `POST /sim/freeze`, `POST /scenario`, `DELETE /scenario/{id}`,
`GET /agent/recs`, `POST /agent/recs/{id}/approve`, `POST /agent/recs/{id}/dismiss`,
`GET /governance/drift`, `GET /governance/fairness`, `GET /governance/audit`, `GET /models`.

## 7. Machine learning (`backend/twin/ml/`) — trained live at the event

### 7.1 Training data
`make train` runs the sim headless and fast (no sleeping): 30 sim days × 3 hospitals with a fixed seed,
then writes a feature table (parquet) with one row per patient per 30 sim minutes. Label: a critical event
within the next 6 sim hours.

### 7.2 Deterioration model
- Features: latest vitals; 1h and 2h deltas; rolling min/max of SpO2, HR, RR over 2h; NEWS2 score; age;
  sex; comorbidity count; unit; hours since admission; ESI. No latent severity, no future information
  (a leakage test builds features at time t and asserts no row uses data after t).
- Model: LightGBM classifier with isotonic calibration. Time-based train/validation/test split.
- Metrics saved to `models/<version>/metrics.json`: AUROC, AUPRC, Brier score, calibration curve, and the
  same metrics for **NEWS2 alone as a baseline**. Quality gates (tests): AUROC ≥ 0.75, and the model beats
  NEWS2 AUROC.
- Explanations: SHAP TreeExplainer; top 3 factors per prediction with human-readable names and signed
  contributions.
- Levels: high ≥ 0.70, medium ≥ 0.45, else low. Alert events on entering high.
- Model card generated to `docs/model_card.md` (data, features, metrics, limits, fairness results).

### 7.3 ER arrivals forecast and capacity projection
- LightGBM regression on hourly arrivals per hospital (hour-of-day, day-of-week, lags 1–24h, rolling means,
  active scenario flag). Horizon: next 6 hours. Must beat a seasonal-naive baseline on validation MAE
  (gate test).
- Capacity projection per unit: current occupancy + forecast admissions × historical admit rate −
  expected discharges, giving "hours until full" per unit. Stored in `forecasts`. Shown in the UI and used
  by the agent.

### 7.4 Live inference
Every 5 sim minutes, score every admitted or waiting patient; write `risk_scores`; emit `risk` and `alert`
events. Forecasts refresh every 15 sim minutes. The model version in use shows in the UI.

### 7.5 Length-of-stay model
- Predicts remaining hours until discharge for every admitted patient, scored every 15 sim minutes.
- Features: the §7.2 features plus unit, ESI, admission reason category, hours since admission, and
  current risk score. LightGBM regression on log hours; training data from the same headless sim run.
- Gate tests: validation MAE beats the baseline (median remaining LOS by unit and hours-since-admission
  bucket) by at least 10%.
- Used by the capacity projection: expected discharges in §7.3 come from LOS predictions instead of
  historical rates (a test asserts the projection changes when LOS predictions change).
- Shown in the inspector ("Expected discharge in ~14 h") and used by the agent to choose discharge
  candidates.

### 7.6 Federated learning across the three hospitals
- Story: hospitals can't pool patient records, so each one trains on its own data and only model weights
  leave the building.
- Implementation: Flower simulation with 3 clients (one per hospital, each with only its own rows) training
  a PyTorch MLP (2 hidden layers) on the §7.2 features, FedAvg, 25 rounds, fixed seeds.
- Comparison saved to `models/<version>/federated.json`: (a) federated MLP, (b) centralized MLP on pooled
  data, (c) each hospital's local-only MLP, all on the same held-out test set, plus per-round validation
  AUROC.
- Gate tests: federated AUROC within 0.03 of centralized, and higher than the average local-only AUROC.
  A test asserts that the data passed into each client contains only that hospital's patients and that
  only parameters (no rows) cross the client boundary.
- UI (governance drawer → "Federated training"): per-round AUROC chart, the three-way comparison, a
  "Run federated training" button that runs it in the background with live round-by-round progress over
  the WebSocket, and a switch for which deterioration model is live (LightGBM central or federated MLP).
  Switching writes the audit log, and the active model version shows everywhere scores appear.
- `make fed-train` runs the same thing from the command line.

## 8. Governance (`backend/twin/ml/governance.py` + UI panel)
- **Audit log:** every inference batch (counts, model version), alert, agent recommendation, approval or
  dismissal, scenario and sim control action.
- **Drift:** PSI per feature per hospital, comparing the last 2 sim hours to the training distribution,
  every 15 sim minutes. PSI > 0.2 raises a drift alert. A test runs the flu surge and asserts that drift
  is detected on respiratory features.
- **Fairness:** AUROC and calibration by age band (18–39, 40–64, 65+) and sex on the most recent labeled
  window, refreshed hourly in sim time. Gaps > 0.05 AUROC are flagged.
- **Panel:** drift heatmap (feature × hospital), fairness table, audit log list with filters, link to the
  model card.

## 9. Gemini operations agent (`backend/twin/agent/`)
- **When it runs:** every 15 sim minutes per hospital, immediately when a scenario starts, and on any
  unit projected full within 4 hours.
- **Input:** a compact structured summary built from the DB: occupancy and hours-until-full per unit,
  ER wait, waiting count, forecasts, high-risk patients with top factors, staffing vs ratio, incoming
  ambulances, network status of the other hospitals.
- **Output:** Gemini structured output validated by pydantic:
  `recommendations: [{ id, hospital_id, action: divert_ambulances | expedite_discharge | move_patient |
  call_in_staff | hold_bed, targets: [...], params: {...}, rationale: str, cited_metrics: [{name, value}] }]`.
- **Grounding check:** every `cited_metrics` value must equal a value in the input summary (after
  rounding), and every target id must exist and be valid for the action (for example, expedite_discharge
  only for patients whose risk level is low). Failing output is retried once with the validation errors in
  the prompt, then dropped.
- **Fallback:** if Gemini errors, times out (10 s), or fails validation twice, a deterministic rules engine
  produces recommendations in the same schema. The UI labels them "Rules engine — Gemini unavailable".
  Both paths are tested.
- **Approve / dismiss** in the UI calls the API; approval applies the action to the sim (§5.7) and writes
  the audit log. "Why?" shows the rationale and cited metrics.
- Config: `GEMINI_API_KEY`, `GEMINI_MODEL` (read from env; do not hardcode a model name). Tests use
  recorded response fixtures inside `tests/` only. `make verify-live` (not part of `make verify`) runs a
  real call when a key is present.

### 9.1 Voice questions ("Ask Hospital Twin")
- A push-to-talk mic button in the 3D view (hold Space while the canvas has focus, or click and hold). It
  uses the browser Web Speech API (`SpeechRecognition`, Chrome on macOS) and shows the live transcript.
  A text box offers the same feature for typing, and for browsers without speech support (shown
  automatically).
- `POST /agent/ask {question, hospital_id}` → Gemini with function calling over a fixed, read-only tool set:
  `list_high_risk_patients(hospital, unit?, limit)`, `get_occupancy(hospital, unit?)`,
  `get_forecast(hospital, unit?)`, `find_patient(patient_id)`, `get_er_wait(hospital)`,
  `get_staffing(hospital, unit?)`. Tools query the DB through the same repositories as the REST API.
- Response: `{answer_text, entity_ids, cited_metrics}`. The grounding check from §9 applies: numbers and
  ids in the answer must come from tool results.
- The frontend speaks the answer (`speechSynthesis`), shows it in a dialog, highlights the returned
  entities in the 3D view (pulsing ring + X-ray marker), and offers "Fly to" for each.
- Fallback without Gemini: a deterministic intent parser covering those six tools ("who is most likely to
  crash", "how full is the ICU", "when will the ER be full", "where is P-0412", "ER wait", "how many
  nurses"), labelled as fallback.
- Tests: each tool (integration), the intent parser (unit, at least 30 phrasings), the grounding check,
  the speech adapter behind an interface with a fake recognizer (unit), and an e2e test using the typed
  path that asks "who is most likely to crash in the ICU" and checks that the answer lists the
  highest-risk ICU patient from the API and highlights them in `__TWIN_DEBUG__`.

## 10. Frontend (`frontend/`)

### 10.1 Screens
1. **Network map:** top-down pixel-art city (canvas, crisp pixels), the three hospitals with capacity
   tags and status pills (OK, BUSY, CRITICAL, OFFLINE — text, not only color), live ambulances on roads,
   the active diversion route highlighted, and a side panel (hospitals, incoming ambulances, agent card).
   Click a hospital to open its 3D view.
2. **Hospital 3D view (main screen):** see §10.2–10.6. Side panels: KPI strip, live feed, patient
   inspector, agent recommendations, governance drawer; scenario and speed controls.
3. **2D floor plan fallback:** top-down per-floor plan driven by the same entity store, toggled from the
   3D view. It must stay fully working, so it can be used if WebGL fails.
Visual targets: `reference/screens/*.png` (3D; `11-isometric-floor2-default-view.png` is the default look), and `reference/mockups/NetworkMap.dc.html`,
`FloorPlan.dc.html`, `Classic3D.dc.html`, `XrayIso.dc.html` for the HUD, network map and 2D layouts. The
`.dc.html` files use a design-tool template syntax (`{{ }}`, `<sc-for>`): read them for layout, colors,
fonts (Pixelify Sans, VT323) and copy, not as runnable code.
The prototypes say "PULSE" in the header; the product name is **Hospital Twin**: use it everywhere.

### 10.2 3D look ("classic pixel") — port the prototype

Start CP3 by porting `reference/engine/pulse3d.js` into `frontend/src/engine/` (modules such as
`palette.ts`, `materials.ts`, `building.ts`, `characters.ts`, `props.ts`, `labels.ts`, `camera.ts`,
`xray.ts`, `picking.ts`, `scene.ts`). The prototype already implements the building in §3, faceless
characters, toon shading, outlines, tile textures, four styles, presets, cutaway, exploded view, X-ray
and picking. Port three of its styles: `iso` (used by the isometric camera, the default view), `classic`
(used by the free-fly camera) and `neon` (night mode, for either camera). Do **not** port the `gameboy`
style; the human decided to skip it. What it does NOT do, and you must add: reading `shared/layout.json` instead of hardcoded
coordinates, creating and removing characters from live entities, moving them along server paths, the
elevator carrying real riders, typed APIs, the debug API, and tests. Its patient list is demo data and must
be removed from the product path.

**Visual parity check (CP3 and CP4 evidence):** render the same presets as `reference/screens/` (same
camera, `?freeze=1`) and save them side by side with the references in `docs/evidence/cp3/parity/`. Unit
tests pin the palette constants, the pixel factor default (2), toon steps, outline color, and the camera
angles to the prototype's values.

- three.js scene rendered to a canvas at 1/pixel-factor resolution (default factor 2; user can choose
  1–4) and upscaled with `image-rendering: pixelated`; antialias off.
- Toon shading with a 3–4 step gradient map (NearestFilter); black outlines on boxes via `EdgesGeometry`;
  16 px checker floor textures per room color (NearestFilter, repeat to room size).
- Palette: the classic pixel palette from the reference images (sky #8fd3ff, grass #6fbf5a, walls
  #f6f2e8, exterior #e9dcc6 with a glass window band #8fd0f0, outline #1d1a2c, risk low #3fb68b, medium
  #f0a830, high #e5484d). A night palette (§10.5) is a toggle.
- Building per §3 with exterior window bands, room furniture as listed, stairs, a glass elevator shaft and
  a moving car, a roof with helipad and helicopter, street, ambulance bay, parking, trees.
- Room labels as sprites with live counts (for example "ICU 5/6"), rendered on 512×128 canvases.

### 10.3 Characters (voxel, faceless)
- Built from boxes: two legs, torso, two arms with hands, head block. Hair = a cap box plus a back box;
  or a headscarf = a box around the head with a plain skin-colored front panel. **No eyes, nose, mouth,
  eyebrows or any facial detail.**
- Role colors: nurse teal scrubs (#2fa39a), doctor white coat with dark trousers, surgeon green scrubs,
  EMT orange, patient light-blue gown, visitors varied. Appearance comes from the entity's `appearance`.
- Poses: walking (leg and arm swing), standing idle, seated, lying in bed (head on pillow, blanket).
- Patients in beds: bedside monitor whose screen shows the risk color; it blinks when high, and a red "!"
  sprite bobs above the bed.

### 10.4 Faceless enforcement test
`characterFactory` exposes the list of part names it builds. A vitest test asserts the part set is a
subset of `{legL, legR, torso, armL, armR, handL, handR, head, hairCap, hairBack, scarf, scarfDrape,
facePanel}`, that `facePanel` is one box with one material color equal to the skin color, and that no part
other than `facePanel` sits on the front face of the head. The e2e debug API exposes `faceAudit()`, and a
Playwright test calls it for every character in the scene.

### 10.5 Views and modes
- **Camera:** isometric orthographic (the default view, decided by the human; it renders with the `iso` style; azimuth 45°, elevation 26.565°; drag rotates, WASD pans,
  E/Q raise/lower, wheel zooms) and free-fly perspective (rendered with the `classic` style; drag looks, WASD moves, E/Q up/down, Shift
  faster, wheel dollies). Keyboard handlers are attached to the canvas, not the window.
- **Presets:** Outside, Ground floor, Floor 2, Floor 3, Exploded, Side view, ICU close-up, Helipad, Front
  door. Camera moves are eased (≈1.2 s).
- **Floor cutaway:** choosing a floor hides the floors above it and the roof, and shows that floor's
  labels. **Exploded:** floors separate vertically with a gap of 6 m and animate apart and back.
- **X-ray:** walls become 7% opacity, floors 55%, outlines faint; shell meshes stop casting shadows;
  floors spread 3.5 m apart when viewing all floors; a marker sprite (always visible, `depthTest: false`)
  floats over every person in role color, and over every bedded patient in risk color. A legend appears.
- **Night mode:** night palette with lit windows and glowing monitors.
- **Picking:** clicking a patient (head or blanket) selects them: a ring appears around the bed and the
  inspector shows id, bed, age, live vitals, a 6-hour risk sparkline (`/patients/{id}/risk`), a vitals
  sparkline (`/patients/{id}/vitals`), top factors, FHIR id, and "Fly to this bed". Clicking staff shows
  role, unit and current task.
- **Pitfalls already found while prototyping (each one needs a regression test):**
  - Clamp the frame delta to ≥ 0. The first `requestAnimationFrame` timestamp can be earlier than
    `performance.now()`; a negative clock crashed the elevator code on frame one and nothing rendered.
  - Never key objects by non-ASCII strings that cross a file boundary without UTF-8 guaranteed (the "·" in
    preset names broke lookups once). Use ASCII ids and keep display labels separate.
  - X-ray with all floors stacked is unreadable unless floors spread apart (3.5 m) and walls drop to ~7%.
  - Pixel factor 4 looked blurry to the human; 2 is the approved default.
  - Label canvases at 256×64 were illegible; use 512×128.
  - Transparent shell materials need `depthWrite: false` and no shadow casting.

### 10.6 Live binding and the debug API
- The entity store (zustand) applies the snapshot, then events. Moves animate along the server-provided
  path between `depart` and `arrive` sim times, mapped to real time by the current speed. Patients in beds
  are placed exactly at their bed. Seated people use seat coordinates. Floor changes use the elevator car
  (the rider is visible inside it).
- Reconnects with backoff and resyncs from a fresh snapshot. A "Disconnected" banner shows while offline.
- `window.__TWIN_DEBUG__` (always present; read-only): `entities()` → id, kind, floor, room, bed and world
  position for every rendered character; `counts()` by kind; `beds()` → bed id → patient id rendered;
  `view()`; `xray()`; `selected()`; `faceAudit()`; `frameStats()`.

### 10.7 UI accessibility basics
Real buttons with labels, keyboard focus on the canvas, text contrast ≥ 4.5:1 in panels, status shown by
text plus color.

## 11. Testing plan (on top of `CLAUDE.md` §3)
- **Unit:** layout generator, A* pathing, sim processes, invariants, vitals generator, features, NEWS2,
  PSI, fairness metrics, agent validator, rules fallback, WebSocket schema models, entity store reducers,
  path interpolation, camera math, character factory, x-ray material swap.
- **Integration (real TimescaleDB):** migrations on an empty DB, continuous aggregate correctness,
  compression policy present, the sim writing a seeded hour and the API reading it back, agent approve →
  sim action → audit row.
- **End to end (Playwright, SwiftShader):**
  1. Network map loads; three hospitals render; clicking Mercy opens the 3D view.
  2. `__TWIN_DEBUG__.counts()` equals the counts from `GET /hospitals/mercy/state`.
  3. Every occupied bed from the API has a lying patient at that bed (`beds()`).
  4. X-ray toggles: markers become visible and shell opacity changes.
  5. Clicking ICU-3's patient opens the inspector with the same id as the API.
  6. Floor presets hide and show the right floors.
  7. Flu surge: within N ticks, waiting count rises, a drift alert appears, and a recommendation appears
     (rules fallback in tests); approving it writes an audit entry and changes ambulance routing.
  8. `faceAudit()` passes for every character.
  9. Screenshot checks at `?freeze=1` for Outside, Ground floor, X-ray ICU close-up; saved to
     `docs/evidence/`.
  10. Killing the backend shows the Disconnected banner; restarting resyncs.
  11. Typed "Ask Hospital Twin" question highlights the right patient (§9.1).
  12. Federated training run from the UI streams round progress and the model switch changes the
      model version shown in the inspector.

## 12. Deployment
- `infra/docker-compose.prod.yml`: backend container, Caddy serving the built frontend and proxying
  `/api` and `/ws`, automatic HTTPS for the domain. The DB is the Tiger Cloud service (`DATABASE_URL`).
- `make deploy`: build, push to the Vultr VM over SSH, run migrations, restart, then run a smoke check
  (`/health`, a WebSocket snapshot, one page load) against the public URL.
- Domain registered through GoDaddy Registry; DNS A record to the VM.

## 13. Demo
- `docs/demo_script.md`: a 3-minute walkthrough. Network map → Mercy 3D → X-ray → click the high-risk
  ICU patient and explain the top factors → Flu surge → waiting room fills, drift alert fires → Gemini
  recommends diversion with cited numbers → approve → ambulances reroute on the map → hold the mic and ask "who is most likely to
  crash tonight?" → camera flies to them → governance panel: drift, fairness, the federated vs centralized
  comparison, and the model card.
- `make record`: a Playwright script that performs the demo and records a video to `docs/demo.webm` (the
  backup if the live demo fails).
- README: setup, architecture diagram, prize-track sections, screenshots, team.

## 14. Checkpoints (stop after each one for "approved CPn")
The event is 48 hours and this session builds the whole project. CP0–CP4 produce a complete working MVP
early on purpose, so a working demo exists even if something goes wrong later. That ordering is a safety
net, not permission to rush: every checkpoint after CP4 is required and gets the same rigor. Target hours
include time for the human's review.

| CP | Name | Spec | Target hour | Must be true to pass |
| --- | --- | --- | --- | --- |
| CP0 | Scaffold | CLAUDE.md §5–6 | 2 | Repo layout, Makefile targets, Docker DB up, lint + test + placeholder grep running in `make verify`, CI workflow, `.env.example` |
| CP1 | Data layer | §3, §4 | 5 | `layout.json` generated and tested against §3; migrations on empty DB; hypertables, continuous aggregates, compression; Synthea patients loaded (count shown) |
| CP2 | Simulation + stream | §5, §6 | 11 | Sim runs at all speeds, deterministic with seed, invariants tested, scenarios and actions work, DB writes, REST and WebSocket per schema, schema file generated |
| CP3 | 3D scene | §10.2–10.5 | 16 | Building, characters (faceless test passing), cameras, presets, cutaway, exploded, x-ray, night mode, picking, rendered from a recorded snapshot fixture **in tests only**; screenshots in evidence |
| CP4 | Live end to end | §10.1, §10.6, §11 e2e 1–6, 8, 10 | 21 | 3D view driven by the live sim; moves animate along paths; inspector live; 2D fallback; network map live; e2e passing. **This is the "it works end to end" gate.** |
| CP5 | ML | §7.1–7.4 | 26 | Models trained live via `make train`; gates met (report metrics vs NEWS2 and the naive baseline); live scores, SHAP factors and forecasts in the UI; model card |
| CP6 | Agent + governance | §8, §9 | 31 | Gemini recommendations with grounding check, rules fallback, approve → sim action → audit; drift, fairness and audit panels; e2e 7 passing |
| CP7 | LOS, federated, voice | §7.5, §7.6, §9.1 | 37 | LOS model past its gate and feeding capacity projection; federated run past its gates with UI progress and model switch; voice + typed questions with tools, fallback and highlighting; e2e 11–12 passing |
| CP8 | Deploy | §12 | 40 | Live on the domain over HTTPS on Vultr with Tiger Cloud; smoke check passing against the public URL; voice works on the public HTTPS site |
| CP9 | Demo ready | §13, §11 e2e 9 | 43 | Demo script, `make record` video, README with prize sections, screenshot tests, final `make verify` and `make e2e` green on a clean clone |

Hours 43–48 are buffer for fixes the human asks for, polish, and rehearsing the demo.

For every checkpoint, follow `CLAUDE.md` §4 exactly: evidence, how-to-check steps, commit, tag, STOP.

### 14.1 What the human must provide (ask for these at the checkpoint before they are needed)
You cannot create accounts. Ask the human, in the CP2 report, to prepare: a Gemini API key (needed at
CP6), a Tiger Cloud service connection string (CP8), a Vultr VM with SSH access (CP8), and the registered
domain with DNS access (CP8). Until then, local Docker TimescaleDB and the rules fallback are used, and the
UI says so.

## 15. Out of scope (do not build)
Real patient data or any PHI · user accounts or login · Solana or MongoDB integrations · native mobile
apps. If you believe one of these is needed, ask first.

## 16. Time-permitting extras (only if there is enough time)

These are wanted, but only after everything above is finished. They never come at the expense of §1–§14.

### 16.1 Rules for extras
1. Do not start any extra until CP9 is approved by the human.
2. Before starting one, check the time left. Start it only if the remaining time is at least its estimate
   plus 2 hours. Otherwise ask the human whether to start it, or stop and polish.
3. Build each extra on its own branch (`extra/X<n>-<name>`). Merge into `main` only when it is complete
   per its spec, `make verify` and `make e2e` pass, and the human approves its mini-checkpoint. The main
   branch must stay demo-ready at all times.
4. An extra is all or nothing. A partly built extra is never merged, never shown as working in the UI, and
   never described as done. If time runs out mid-extra, leave the branch unmerged and say so in
   `CHECKPOINTS.md`. That is the correct outcome, not a shortcut.
5. Each extra has the same requirements as core features: CLAUDE.md rules, tests, evidence and a
   mini-checkpoint report (`Xn` in `CHECKPOINTS.md`, tag `xN`), then STOP for "approved Xn".
6. Default order is below (best value for time first). The human may reorder at any checkpoint.

### 16.2 The extras

| # | Extra | Est. | What "done" means |
| --- | --- | --- | --- |
| X1 | Nurse alert pop-ups | 2 h | Every admitted patient has an assigned nurse (sim). When a patient goes high risk, a pop-up appears addressed to that nurse ("N-14: P-0412 in ICU-3") with the top 3 SHAP reasons and Acknowledge / Escalate buttons. In 3D the nurse's marker pulses and the sim sends them to the bed. Time-to-acknowledge is stored, shown on the governance panel, and audited. Tests: assignment invariants, alert routing, ack flow e2e. |
| X2 | Readmission risk model | 3 h | The sim brings some discharged patients back (probability depends on age, comorbidities, LOS, discharge risk). Label: return within 30 sim days. LightGBM model scored at discharge time; shown in the inspector and used by the agent so it does not recommend early discharge for high-readmission patients. Gate: AUROC ≥ 0.70 and beats a LACE-index baseline. Leakage test as in §7.2. |
| X3 | Model registry and rollback | 2 h | Every trained model is a version with metrics and timestamp. The governance panel lists versions and has a Roll back button. Automatic rollback proposal when live AUROC on recent labeled data drops > 0.05 below validation, or drift on more than 3 features > 0.3; the human confirms in the UI. Rollback swaps the live model without restarting and writes the audit log. Tests: swap under load, audit, proposal trigger. |
| X4 | Per-hospital fairness | 1 h | The §8 fairness metrics computed per hospital as well as network-wide, with a hospital filter in the panel. Tests on seeded data. |
| X5 | Overflow beds action | 2 h | `layout.json` gains overflow spots (corridor and recovery stretchers) per floor. New agent action `open_overflow_beds(hospital, floor, count)`: the sim adds temporary beds, the 3D view shows stretchers appearing, capacity and KPIs update, and closing them returns patients to real beds first. Grounding and audit like other actions. |
| X6 | Staff shift changes | 2 h | 07:00 and 19:00 sim-time shift changes: outgoing staff walk to the exit, incoming staff arrive through the entrance, a 15-minute handoff overlap, and staffing never drops below ratio during handoff unless the staff shortage scenario is active. Invariant tests. |
| X7 | AI patient placement | 3 h | Each incoming ambulance patient is assigned a hospital by a scoring model (travel time, projected capacity per unit, acuity, OR/ICU availability) instead of nearest-with-space. The network map shows the choice and its top reasons. Compare against nearest-hospital routing on the same seeded day: report average wait, boarding hours and critical events; gate is better on at least two of three. |
| X8 | Different hospital sizes | 5 h | Three building templates in `layout.json`: Mercy (current, 3 floors + helipad), St. Luke's (smaller: 2 floors, no OR, no helipad), Desert Valley (larger: 4 floors, two ICUs, imaging + cath lab). Different equipment changes which patients each can treat; Synthea populations differ by age mix per hospital. The 3D engine renders every template, and all §11 e2e checks run against all three. |
| X9 | HAPI FHIR server | 4 h | HAPI FHIR server in Docker. `make seed` loads Synthea bundles into HAPI; the sim reads arriving patients from HAPI's FHIR API; encounters and vital-sign Observations are written back to HAPI as the sim runs. The inspector's FHIR link opens the real resource. The Tiger Data copy stays as the analytics store. Integration tests against the HAPI container. |
| X10 | Differential privacy for federated learning | 3 h | DP-SGD (Opacus) inside each Flower client, with per-client privacy budget reporting (ε, δ). Privacy-vs-accuracy curve for ε ∈ {1, 3, 8, ∞} saved and shown in the federated panel. Gate: AUROC at ε = 8 within 0.05 of non-private federated. |
| X11 | Redpanda event streaming | 5 h | Redpanda (Kafka API) in Docker. The sim publishes every event to topics (`vitals`, `moves`, `beds`, `events`); separate consumers write to Tiger Data, run inference, and feed the WebSocket broadcaster. Consumers survive restart without losing or duplicating events (offset tests). The browser still uses WebSockets. All earlier tests pass unchanged. |
| X12 | Chest X-ray model (multimodal) | 6 h | A pretrained chest X-ray model from TorchXRayVision scores real public X-ray images (a small subset of NIH ChestX-ray14 that the human downloads; ask for it at the X12 start). The sim attaches an image to respiratory patients, matched by finding. Image-model probabilities become features in a second deterioration model; report with- vs without-image metrics. The inspector shows the image and its findings. |
| X13 | Reinforcement learning for operations | 8 h | A Gymnasium environment wrapping the sim (actions: bed assignment, diversion, call-in staff). Train PPO (stable-baselines3) during the event. Evaluate against the rules baseline on 20 seeded days: average ER wait, boarding hours, critical events. A UI toggle runs the RL policy live, labelled as such. Gate: better than baseline on at least two of three, with confidence intervals. |

Report at CP9 which extras fit in the remaining time, in this order, and ask the human to confirm before
starting X1.
