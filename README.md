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
- **apply_config before every measurement**: planner re-applies the requested config ahead of each `measure_yzstage` run.
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

## Beamline deployment

The core library remains deployment-agnostic, but this repository also ships a
reference Queue Server startup profile under
`qserver_profile/profile_mouse/startup/`.

Production beamlines may still keep their operational startup in a separate
repository. In that case, this repo remains the source for plans, planner
logic, and a working reference profile.

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
- `tests/unit/interactive_scans/`
- `tests/integration/interactive_scans/`

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

- `qserver_profile/profile_mouse/startup/00_plans.py`

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

- Replay TiledWriter backup files into Tiled after a Tiled outage:

```bash
mouse-bluesky tiled-replay ~/data/tiled_backup_buffer \
  --uri https://tiled.scicat65.ddnss.de --api-key-file ~/.tiled_api.key
```

  See [Replaying backups after a Tiled outage](design_documentation/operations.md#replaying-backups-after-a-tiled-outage).

  The CLI now normalizes Queue Server responses before reporting failures, so tuple-
  shaped replies (e.g. `(success, message, traceback)`) or objects with `success`
  attributes are handled gracefully and their messages are surfaced when requests
  fail.

Vacuum scripts `./evacuate.sh` and `./ventilate.sh` require an idle Queue Server
with an open worker environment. They insert the plan at the front followed by
a `queue_stop` instruction, then start the queue. The queue stops after the plan,
leaving existing measurements in their original order. If the queue is not idle,
the command refuses without adding anything. `--prioritize` and `--position front`
are accepted; `--position back` requires `--enqueue-only`. Use `--enqueue-only`
to enqueue without adding a stop or starting the queue; this defaults to the back
and supports `--position` and `--prioritize` as before. After deploying, close and
reopen the Queue Server environment to load the new plans.

`./start-mouse-http-server.sh` provides authenticated read-only queue access for
the remote dashboard. See [HTTP server operations](design_documentation/operations.md#http-server-read-only-queue-access)
for environment setup, TLS, screen sessions and API keys.

To change the sample rack:

```bash
qserver queue stop
# Wait until the current measurement finishes and the manager is idle.
./ventilate.sh
# Wait for ventilation to finish, then change the rack.
./evacuate.sh
# Wait for evacuation to finish, then continue the measurements.
qserver queue start
```

If a vacuum plan fails or is aborted, the queue stops and Queue Server puts the
plan back at the front, still followed by the `queue_stop` instruction. The next
start retries the plan and then stops again. To skip the retry, remove both the
plan and the instruction. A plan ended with `qserver re stop` counts as
finished and is not put back, so only the instruction stays at the front and
the next start stops immediately.

Evacuation leaves the pump (`do6`) on, including after a failure once pumping
has started. Ventilation closes `do7` when its valve sequence ends, including
on failure, timeout, stop or abort. Shutter closes are best-effort: faults warn
and execution continues, with safety provided by the interlocks. A worker
crash or power loss prevents the finalizer from running, so `do7` may stay
open. See [vacuum operations](design_documentation/operations.md#vacuum-plans).
