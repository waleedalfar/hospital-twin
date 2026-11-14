-- Continuous aggregates (PROMPT.md §4.2). Dashboards read these, not the raw hypertables.
--
-- materialized_only = false: a query also includes rows newer than the last refresh, so readers always
-- see current numbers. Refresh policies have open-ended windows (NULL offsets) because sim time runs
-- faster than wall time, so sim timestamps are usually ahead of now().

-- Beds occupied per unit per hospital per 15 minutes: the average over the bed snapshots in the bucket.
CREATE MATERIALIZED VIEW occupancy_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '15 minutes', bs.time) AS bucket,
       bs.hospital_id,
       b.unit,
       count(*) FILTER (WHERE bs.state = 'occupied')::double precision / count(DISTINCT bs.time) AS occupied_avg,
       count(DISTINCT bs.bed_id) AS beds,
       count(DISTINCT bs.time) AS snapshots
FROM bed_state bs
JOIN beds b ON b.hospital_id = bs.hospital_id AND b.bed_id = bs.bed_id
GROUP BY 1, 2, 3
WITH NO DATA;

-- Minutes from arrival to an ER bay: one 'er_admit' event per patient, payload.wait_min.
CREATE MATERIALIZED VIEW er_wait_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '15 minutes', time) AS bucket,
       hospital_id,
       avg((payload ->> 'wait_min')::double precision) AS avg_wait_min,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY (payload ->> 'wait_min')::double precision) AS p90_wait_min,
       count(*) AS patients
FROM events
WHERE kind = 'er_admit'
GROUP BY 1, 2
WITH NO DATA;

-- Arrivals per hospital per hour by mode (walk_in, ambulance, air).
CREATE MATERIALIZED VIEW arrivals_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
       hospital_id,
       payload ->> 'mode' AS mode,
       count(*) AS arrivals
FROM events
WHERE kind = 'arrival'
GROUP BY 1, 2, 3
WITH NO DATA;

-- Risk alerts per hospital per hour by level.
CREATE MATERIALIZED VIEW alerts_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
       hospital_id,
       payload ->> 'level' AS level,
       count(*) AS alerts
FROM events
WHERE kind = 'alert'
GROUP BY 1, 2, 3
WITH NO DATA;

-- Per-patient 5-minute averages (inspector sparkline).
CREATE MATERIALIZED VIEW vitals_5m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '5 minutes', time) AS bucket,
       patient_id,
       hospital_id,
       avg(hr) AS hr,
       avg(spo2) AS spo2,
       avg(sbp) AS sbp,
       avg(dbp) AS dbp,
       avg(temp) AS temp,
       avg(rr) AS rr,
       count(*) AS samples
FROM vitals
GROUP BY 1, 2, 3
WITH NO DATA;

SELECT add_continuous_aggregate_policy('occupancy_15m', start_offset => NULL, end_offset => NULL,
                                       schedule_interval => INTERVAL '1 minute');
SELECT add_continuous_aggregate_policy('er_wait_15m', start_offset => NULL, end_offset => NULL,
                                       schedule_interval => INTERVAL '1 minute');
SELECT add_continuous_aggregate_policy('arrivals_hourly', start_offset => NULL, end_offset => NULL,
                                       schedule_interval => INTERVAL '1 minute');
SELECT add_continuous_aggregate_policy('alerts_hourly', start_offset => NULL, end_offset => NULL,
                                       schedule_interval => INTERVAL '1 minute');
SELECT add_continuous_aggregate_policy('vitals_5m', start_offset => NULL, end_offset => NULL,
                                       schedule_interval => INTERVAL '1 minute');
