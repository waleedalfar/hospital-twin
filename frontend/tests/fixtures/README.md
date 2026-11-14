# Test fixtures

`snapshot_mercy.json` is a snapshot of the real simulation (seeded, test patient pool) recorded by
`backend/tests/record_fixture.py`. Risk scores are fixed fake values added by that script, because the models
do not exist yet. These files are used by tests only and are never imported by `src/` (CLAUDE.md §1.3-§1.4).
