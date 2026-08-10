"""SQLite schema used by the DCMF flight recorder."""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    started_monotonic_ns INTEGER NOT NULL,
    started_utc_ns INTEGER NOT NULL,
    ended_monotonic_ns INTEGER,
    ended_utc_ns INTEGER,
    status TEXT NOT NULL DEFAULT 'recording'
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL,
    utc_ns INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_experiment_time
ON events(experiment_id, monotonic_ns);

CREATE INDEX IF NOT EXISTS idx_events_source_kind
ON events(source, kind);

CREATE TABLE IF NOT EXISTS controller_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL,
    utc_ns INTEGER NOT NULL,
    device_name TEXT NOT NULL,
    axes_json TEXT NOT NULL,
    buttons_json TEXT NOT NULL,
    hats_json TEXT NOT NULL,
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_controller_experiment_time
ON controller_samples(experiment_id, monotonic_ns);

CREATE TABLE IF NOT EXISTS mavlink_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL,
    utc_ns INTEGER NOT NULL,
    direction TEXT,
    message_name TEXT,
    message_id INTEGER,
    system_id INTEGER,
    component_id INTEGER,
    raw_hex TEXT,
    decoded_json TEXT,
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mavlink_experiment_time
ON mavlink_messages(experiment_id, monotonic_ns);

CREATE TABLE IF NOT EXISTS sdr_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL,
    utc_ns INTEGER NOT NULL,
    record_kind TEXT NOT NULL,
    center_frequency_hz INTEGER,
    sample_rate_hz INTEGER,
    gain_db REAL,
    power_dbfs REAL,
    iq_file TEXT,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sdr_experiment_time
ON sdr_records(experiment_id, monotonic_ns);
"""
