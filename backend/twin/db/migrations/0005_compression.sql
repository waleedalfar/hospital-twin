-- Compression on the two highest-volume hypertables for chunks older than 1 day (PROMPT.md §4.2).

ALTER TABLE vitals SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'patient_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('vitals', INTERVAL '1 day');

ALTER TABLE events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'hospital_id, kind',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('events', INTERVAL '1 day');
