# mouse-bluesky

Logbook-driven planning and Bluesky plans for MOUSE. This repository provides:

- **Bluesky plans**: atomic measurement, public measurement wrapper, configuration application scaffold, and snapshotting.
- **Protocol registry**: map `protocol` strings to either single-plan or generator-style compilers.
- **Planner**: compile logbook entries → schedule (barrier-aware collation) → insert config changes → validate → enqueue to Queue Server.
- **Documentation** under `design_documentation/`.

## Key concepts

- **Single-plan protocols**: queued as one Queue Server item; runnable interactively.
- **Generator protocols**: compile to many measurement runs; reorderable within contiguous `collate=ALLOW` blocks.
- **One measurement = one run** persisted to Tiled.
- **apply_config only on change**: planner inserts config changes as needed.
- **Debug snapshot per measurement**: emitted inside each measurement run (stream `snapshot`). Baseline is configured at the RunEngine level.

## Directory layout (expected)

```
src/mouse_bluesky/
  plans/
  protocols/
  planner/
design_documentation/
tests/
```

## Quick start (developer)

1) Create and activate a virtualenv, then install:

```bash
pip install -e .
```

2) Run unit tests:

```bash
pytest
```

3) Read design docs:

- `design_documentation/architecture.md`
- `design_documentation/design_decisions.md`
- `design_documentation/operations.md`
- `design_documentation/contracts.md`
- `design_documentation/testing.md`

## Beamline deployment (separate repo)

This package intentionally does **not** include:
- RunEngine creation and baseline config,
- device instantiation,
- Queue Server startup,
- TiledWriter configuration.

Those belong in the beamline startup/profile repository.

## License

Add your preferred license file (e.g., BSD-3-Clause) and update this section.
