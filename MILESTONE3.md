# DCMF Milestone 3 — Persistent Experiment Recording

Milestone 3 adds an asynchronous SQLite flight recorder.

Database:
`data/dcmf.sqlite3`

Recorded tables:

- `experiments`
- `events`
- `controller_samples`
- `mavlink_messages`
- `sdr_records`

The MAVLink and SDR tables are created now so their acquisition modules can
plug into the same schema in later milestones.

## Test without hardware

1. Launch DCMF.
2. Enter an experiment name such as `database_test`.
3. Click Start Experiment.
4. Add several Mark Event entries.
5. Click Stop.
6. Close DCMF.

Inspect the database:

```bash
sqlite3 data/dcmf.sqlite3
```

Then:

```sql
.headers on
.mode column
SELECT id, name, operator, status FROM experiments;
SELECT source, kind, payload_json FROM events;
.quit
```

You should see the experiment and the START/MARKER/STOP events.
