# Architecture

## Scope

This repository implements:

- **Bluesky plans** for MOUSE measurements (atomic measurement + higher-level wrappers).
- A **logbook-driven planner** that compiles logbook entries into **Queue Server** plan items and pushes them via the Queue Server API.
- **Static pre-validation** of the planned queue (plan names, config files, minimal HDF5 structure sanity checks).
- **Interactive scan helpers** (`peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`) with live fitting.
- A **reference Queue Server startup profile** under
  `qserver_profile/profile_mouse/startup/`.

Production beamline deployment may still keep startup in a dedicated operations
repository, but this repo now includes a working reference startup profile:
- `01_re.py` (RunEngine),
- `02_tiledwriter.py` (optional TiledWriter),
- `03_init_devices.py` (devices),
- `04_baseline.py` (SupplementalData baseline wiring),
- `00_plans.py` (plan exports for Queue Server discovery).

## High-level flow

```mermaid
flowchart LR
  A[Excel Logbook Row<br/>Logbook2MouseEntry] --> B[Parse additional_parameters<br/>str->str + optional __json__]
  B --> C[ProtocolRegistry]
  C --> D[Protocol.compile(entry, params)]
  D --> E[CompiledEntry: collate policy + QueuePlan list]
  E --> F[Segment Scheduler<br/>collate ALLOW blocks only]
  F --> G[Insert apply_config on config changes]
  G --> H[Static validation (optional)]
  H --> I[Queue population via QS API<br/>queue_item_add]
  I --> J[Queue Server executes plans]
  J --> K[Measurement run in Tiled]
```

## Key modules

### Protocols

- `mouse_bluesky.protocols.registry`
  - `ProtocolRegistry`: maps `protocol` strings to compilers.
  - `ProtocolSpec`: (name, compile function).
- `mouse_bluesky.protocols.builtin`
  - Examples:
    - **Single-plan protocol**: compiles to exactly one Queue Server plan item (interactive-friendly plan).
    - **Generator protocol** (e.g., `standard_measurements`): compiles to multiple plan items (reorderable).

### Planner

- `mouse_bluesky.planner.params`
  - Parses `additional_parameters: Dict[str, str]`.
  - Supports an optional `__json__` blob for typed values.
- `mouse_bluesky.planner.scheduler`
  - Implements **barrier-aware collation**:
    - `collate=FORBID` creates a barrier.
    - `collate=ALLOW` entries are collated only within their contiguous block.
- `mouse_bluesky.planner.config_insertion`
  - Inserts `apply_config(config_id)` only when the configuration changes.
- `mouse_bluesky.planner.validate`
  - Static checks: known plan names, config files exist, `/saxs/Saxslab` group exists, scalar datasets.
- `mouse_bluesky.planner.logbook2bluesky`
  - End-to-end: compile → schedule → insert config changes → (optional validate) → push to Queue Server.

### Plans

- `mouse_bluesky.plans.atomic`
  - Atomic measurement plan(s): no `open_run`, no baseline logic.
- `mouse_bluesky.plans.public`
  - `measure_yzstage`: opens run, records metadata, takes a **snapshot** stream immediately before acquisition, then calls atomic plan.
- `mouse_bluesky.plans.configure`
  - `apply_config`: loads `{config_id}.nxs` and applies grouped/ordered motor moves.
  - `save_config`: writes current mapped machine state to `{config_id}.nxs`.
  - `build_baseline_signals`: resolves baseline signals from config maps and generator readbacks.
- `mouse_bluesky.plans.snapshot`
  - `snapshot_state`: reads debugging signals into a dedicated stream (e.g. `snapshot`).

### Interactive scans

- `mouse_bluesky.interactive.scans`
  - user-facing helpers: `peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`
  - minimal API supports `scan_fn(motor, start, stop)`
  - extended API supports `scan_fn(motor, start, stop, num, exposure_time)`
- `mouse_bluesky.interactive.fit_models`
  - lmfit model builders and initial guess helpers
- `mouse_bluesky.interactive.exposure`
  - deterministic Eiger-style exposure path handling (`cam.acquire_time`, `cam.acquire_period`)

## Streams & metadata strategy

- **Baseline stream**: configured in startup (`04_baseline.py`) via `SupplementalData`.
  Baseline signals are built by `build_baseline_signals(...)`, including:
  - mapped base motors,
  - optional YZ and GI stage signals if available,
  - generator voltage/current readbacks.
- **Snapshot stream**: emitted inside each measurement run, immediately before detector acquisition, for “debugging before every measurement”.
- **RunStart metadata**:
  - should include `entry_row_index`, `config_id`, `repeat_index`, and a filtered `logbook_entry` dictionary (JSON-friendly).

## NeXus configuration state file contract

- Config file: `{config_id}.nxs`
- Settings stored as scalar datasets under:
  - `/saxs/Saxslab/<pv_or_motor_name> = <scalar_value>`

The configuration loader reads those scalars and applies them via grouped `bps.mv`
sequences to avoid unsafe simultaneous moves.
