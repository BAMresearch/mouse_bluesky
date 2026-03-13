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

## mouse_bluesky interactive scans

Interactive helpers are available in `mouse_bluesky.interactive` and are
designed for `qserver-console` / `qserver-qtconsole` workflows with live fits.

Available scans:

- `peak_scan`
- `valley_scan`
- `edge_scan`
- `capillary_scan`

All scans support a minimal call and a short extended call:

- Minimal: `scan_fn(motor, start, stop)`
- Extended: `scan_fn(motor, start, stop, num, exposure_time)`

Examples:

```python
from mouse_bluesky.interactive import peak_scan, edge_scan

# Minimal usage
res_peak = peak_scan(motor, -1.0, 1.0)

# Extended usage
res_edge = edge_scan(motor, -0.5, 0.5, 41, 0.2)
```

### Contents

- `src/mouse_bluesky/interactive/`
- `tests/unit/interactive/`
- `tests/integration/interactive/`

### Defaults

- `num=10`
- `exposure_time=1.0`
- default detector resolved from interactive `eiger`
- default RunEngine resolved from interactive `RE`
- live table on by default
- live plot off by default
- `peak_scan`/`valley_scan` default model profile: `gaussian`
- `edge_scan` default model: sigmoidal (`StepModel`)

### Runtime behavior

- Scans run as standard Bluesky `scan(...)` plans with callbacks (`LiveFit`,
  optional `LiveTable`, optional `LivePlot`).
- `exposure_time` sets detector timing before the scan; it is not an inter-step sleep.
- Current exposure configuration is deterministic for Eiger-like detectors via:
  - `det.cam.acquire_time`
  - `det.cam.acquire_period`
  - Code marker: `TODO: check` in `interactive/exposure.py` for final IOC verification.

### Returned result

Each helper returns `ScanResult` with consistent fields:

- `uid`, `kind`, `detector_field`, `motor_field`
- fit status: `fit_success`, `fit_message`
- fit outputs: `fit_center`, `width`
- convenience stats where applicable: `com`, `cen`
- raw callback artifacts: `fit_result`, `peak_stats`, `livefit`
- extra metadata in `extra`

For capillary scans, center is the fitted `mid_center` and width is
`abs(left_center - right_center)`.

### Queue Server startup exposure

Interactive scans are imported in Queue Server startup:

- `qserver_profile/startup/00_plans.py`

This makes them available in both queue operations and interactive console sessions.


## License

Add your preferred license file (e.g., BSD-3-Clause) and update this section.

## Settings and defaults

This package reads default paths from environment variables:

- `MOUSE_DATA_ROOT` → default `root_path` for measurement output (default: `/data/mouse`)
- `MOUSE_CONFIG_ROOT` → default `config_root` for `{config_id}.nxs` files (default: `/data/mouse_configs`)

You can override both via CLI flags or by injecting `measurement_extra_kwargs` / `apply_config_extra_kwargs` when building `PlanSpec`s.

## CLI

After installation, a small CLI is available:

- Validate planned queue (compile logbook → specs → static validation):

```bash
mouse-bluesky validate /path/to/logbook.xlsx /path/to/projects --root-path /data/mouse --config-root /data/mouse_configs
```

- Enqueue into a running Queue Server (fails if validation issues exist):

```bash
mouse-bluesky enqueue /path/to/logbook.xlsx /path/to/projects --zmq tcp://127.0.0.1:60615 \
  --root-path /data/mouse --config-root /data/mouse_configs \
  --user mouse-bluesky --user-group primary
```

  The CLI now normalizes Queue Server responses before reporting failures, so tuple-
  shaped replies (e.g. `(success, message, traceback)`) or objects with `success`
  attributes are handled gracefully and their messages are surfaced when requests
  fail.
