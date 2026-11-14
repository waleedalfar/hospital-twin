-- Time-series tables (PROMPT.md §4.1). Every one is a hypertable on `time`, in one-day chunks.
-- Sim time is stored as real UTC timestamps (§5.1).

CREATE TABLE vitals (
    time        timestamptz NOT NULL,
    patient_id  text NOT NULL,
    hospital_id text NOT NULL,
    hr          double precision NOT NULL,
    spo2        double precision NOT NULL,
    sbp         double precision NOT NULL,
    dbp         double precision NOT NULL,
    temp        double precision NOT NULL,
    rr          double precision NOT NULL
);
SELECT create_hypertable('vitals', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX vitals_patient_idx ON vitals (patient_id, time DESC);
CREATE INDEX vitals_hospital_idx ON vitals (hospital_id, time DESC);

-- kind: move, arrival, er_admit, discharge, transfer, alert, scenario, agent_rec, ambulance, ...
CREATE TABLE events (
    time        timestamptz NOT NULL,
    hospital_id text NOT NULL,
    kind        text NOT NULL,
    entity_id   text,
    payload     jsonb NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('events', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX events_hospital_idx ON events (hospital_id, time DESC);
CREATE INDEX events_kind_idx ON events (kind, time DESC);
CREATE INDEX events_entity_idx ON events (entity_id, time DESC);

-- One row per bed per snapshot: the simulation writes the state of every bed at each snapshot time.
CREATE TABLE bed_state (
    time        timestamptz NOT NULL,
    bed_id      text NOT NULL,
    hospital_id text NOT NULL,
    patient_id  text,
    state       text NOT NULL CHECK (state IN ('occupied', 'cleaning', 'open', 'blocked')),
    CHECK ((state = 'occupied') = (patient_id IS NOT NULL))
);
SELECT create_hypertable('bed_state', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX bed_state_hospital_idx ON bed_state (hospital_id, time DESC);
CREATE INDEX bed_state_bed_idx ON bed_state (hospital_id, bed_id, time DESC);

CREATE TABLE risk_scores (
    time          timestamptz NOT NULL,
    patient_id    text NOT NULL,
    hospital_id   text NOT NULL,
    model_version text NOT NULL,
    score         double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
    level         text NOT NULL CHECK (level IN ('low', 'medium', 'high')),
    top_factors   jsonb NOT NULL DEFAULT '[]'
);
SELECT create_hypertable('risk_scores', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX risk_scores_patient_idx ON risk_scores (patient_id, time DESC);
CREATE INDEX risk_scores_hospital_idx ON risk_scores (hospital_id, time DESC);

CREATE TABLE forecasts (
    time          timestamptz NOT NULL,
    hospital_id   text NOT NULL,
    model_version text NOT NULL,
    horizon_h     smallint NOT NULL CHECK (horizon_h >= 0),
    metric        text NOT NULL,
    value         double precision NOT NULL
);
SELECT create_hypertable('forecasts', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX forecasts_hospital_idx ON forecasts (hospital_id, metric, time DESC);

CREATE TABLE agent_recs (
    time        timestamptz NOT NULL,
    id          text NOT NULL,
    hospital_id text NOT NULL,
    source      text NOT NULL CHECK (source IN ('gemini', 'rules')),
    payload     jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'dismissed', 'expired'))
);
SELECT create_hypertable('agent_recs', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE UNIQUE INDEX agent_recs_id_idx ON agent_recs (id, time);
CREATE INDEX agent_recs_hospital_idx ON agent_recs (hospital_id, time DESC);

CREATE TABLE audit_log (
    time    timestamptz NOT NULL,
    actor   text NOT NULL,
    action  text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('audit_log', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX audit_log_action_idx ON audit_log (action, time DESC);

CREATE TABLE drift (
    time        timestamptz NOT NULL,
    hospital_id text NOT NULL,
    feature     text NOT NULL,
    psi         double precision NOT NULL CHECK (psi >= 0)
);
SELECT create_hypertable('drift', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX drift_hospital_idx ON drift (hospital_id, feature, time DESC);
