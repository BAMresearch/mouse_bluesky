# Operations

This document describes intended usage during development and beamtime.

## Roles & components

- **Queue Server startup profile**:
  - this repo includes a reference profile in `qserver_profile/startup`,
  - production deployments may mirror/adapt this in an operations repo.
  - startup responsibilities:
    - instantiate devices (Eiger, motors, generators),
    - configure `RunEngine`,
    - configure baseline via `SupplementalData`,
    - optionally subscribe `TiledWriter`,
    - export plans for Queue Server discovery.

- **mouse-bluesky** (this repo):
  - provides plans: `measure_yzstage`, `apply_config`, `save_config`, `snapshot_state`, atomic plans,
  - provides interactive scans: `peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`,
  - provides protocol compilers and planner that fills the Queue Server.

## Typical workflow

### 1) Author logbook entries

Each entry includes:
- `protocol: str`
- `additional_parameters: Dict[str, str]`
  - optionally with a `__json__` value containing a JSON object for typed parameters
- proposal/sample metadata as needed

### 2) Compile and schedule

- load logbook entries into `Logbook2MouseEntry` objects
- build a protocol registry (e.g., `build_default_registry()`)
- compile entries → scheduled plan items (QueuePlan list)
- insert `apply_config` on config changes

### 3) Pre-validate (static)

Before pushing items to the queue, run the static validator:
- plan names are known (plan registry or a curated allowlist),
- `config_id.nxs` exists for each used config,
- `/saxs/Saxslab` exists and contains scalar datasets.

Optional live checks (separate tool):
- read-only connectivity checks of a PV allowlist.

### 4) Populate queue via Queue Server API

Use the Queue Server ZMQ control address (default example):
- `tcp://127.0.0.1:60615`

Add items via `queue_item_add` in order produced by the planner.

### 5) Run queue

Start the queue from the Queue Server UI/CLI.

## Runtime behavior

### Baseline stream

Baseline devices are configured at RunEngine level via `SupplementalData`.
In the reference startup profile this is wired in `04_baseline.py` using
`build_baseline_signals(namespace=globals())`, and emits `baseline` at run boundaries.
Included baseline signals cover:
- mapped BASE motors,
- optional YZ and GI stage motors when present,
- generator voltage/current readbacks.

### Snapshot stream

`measure_yzstage` emits a `snapshot` stream inside the run immediately before measurement.
This is used for debugging and state auditing.

### Interactive console usage

When running with `qserver-console` or `qserver-qtconsole`, startup exports:
- standard Bluesky plans (`count`, `scan`, `rel_scan`, `list_scan`, `grid_scan`, etc.),
- interactive fitting scans (`peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`).

Interactive scans support:
- minimal form: `scan_fn(motor, start, stop)`,
- extended form: `scan_fn(motor, start, stop, num, exposure_time)`.

### Tiled storage

Runs are persisted via TiledWriter subscription configured in beamline startup.
Each run’s metadata includes entry identifiers and configuration identifiers.

## Failure modes & recovery

- If a measurement fails:
  - the queue can be paused/stopped,
  - failed item(s) can be retried or removed,
  - because each measurement is one run, partial progress remains in Tiled.
- If configuration is mismatched:
  - recommended: add a lightweight “expected config id” guard to fail early.

## Recommended minimal CLI entrypoints (optional)

Consider adding console scripts (not included here by default):
- `mouse-logbook-validate` → compile + validate only
- `mouse-logbook-enqueue` → compile + validate + enqueue

## Defaults (environment variables)

The planner/CLI uses these environment variables:

- `MOUSE_DATA_ROOT` (default `/data/mouse`)
- `MOUSE_CONFIG_ROOT` (default `/data/mouse_configs`)

They are read via `mouse_bluesky.settings.Settings.from_env()` and can be overridden by CLI flags or by injecting extra kwargs during planning.

## CLI usage

The repository includes a small `mouse-bluesky` CLI:

- `mouse-bluesky validate LOGBOOK PROJECTS_DIR` compiles and statically validates the planned queue.
- `mouse-bluesky enqueue LOGBOOK PROJECTS_DIR` compiles, validates, and enqueues into a running Queue Server via the ZMQ control address.

These commands are intended for operator workflows where you want fast feedback before running the instrument.
