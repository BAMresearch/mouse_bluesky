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
  F --> G[Insert apply_config before every measurement]
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
    - `triangulation`: compiles one sample/configuration into ordered
      `measure_yzstage` points and a final `apply_config` restore. Collation is
      `FORBID`; `ALLOW` is rejected to preserve the series order.
- `mouse_bluesky.protocols.triangulation`
  - Requires `configuration` (int); accepts `steps=50` (int, at least 2),
    `duration=60` (positive seconds), `start=500` and `stop=-130` (distinct mm).
    Unknown parameters fail compilation, including during CLI validation.
  - Uses `numpy.linspace(start, stop, steps)` in that order. Each point carries
    `meta["apply_config_kwargs"] = {"detx": distance, "beam_stop_out": True}`.
    Config insertion copies these to the point's preceding `apply_config`,
    applying the full configuration with direct moves to the target distance
    and the live `beam_stop.out_position`.
  - Run `md` contains `protocol="triangulation"`, `triangulation_index` (0-based),
    `triangulation_points` and `triangulation_detx`. Actual detector readback is
    recorded in the baseline and each `im_craw.nxs` at `/saxs/Saxslab/detx`.
  - The unchanged atomic measurement keeps both 20 s beam profiles and the
    main exposure, with the beamstop out throughout. The default 50 points at
    60 s main exposure take roughly 1.5 to 2 hours including moves/overhead.
    Example logbook parameters: `{"configuration": "123", "steps": "3"}`.
    See [operations](operations.md#triangulation-protocol) for a full example.

### Planner

- `mouse_bluesky.planner.params`
  - Parses `additional_parameters: Dict[str, str]`.
  - Supports an optional `__json__` blob for typed values.
- `mouse_bluesky.planner.scheduler`
  - Implements **barrier-aware collation**:
    - `collate=FORBID` creates a barrier.
    - `collate=ALLOW` entries are collated only within their contiguous block.
- `mouse_bluesky.planner.config_insertion`
  - Inserts `apply_config(config_id)` before every `measure_yzstage`.
- `mouse_bluesky.planner.validate`
  - Static checks: known plan names, config files exist, `/saxs/Saxslab` group exists, scalar datasets.
- `mouse_bluesky.planner.logbook2bluesky`
  - End-to-end: compile → schedule → insert config changes → (optional validate) → push to Queue Server.
  - Adds `apply_config_extra_kwargs` (including `config_root`) to every config
    spec, preserving explicit spec values, including the triangulation restore.
    An enabled YMD marker follows the last measurement for that date, before
    the restore if triangulation is last; the restore only writes an audit run.

### Plans

- `mouse_bluesky.plans.atomic`
  - Atomic measurement plan(s): no `open_run`, no baseline logic.
- `mouse_bluesky.plans.public`
  - `measure_yzstage`: opens run, records metadata, takes a **snapshot** stream immediately before acquisition, then calls atomic plan.
- `mouse_bluesky.plans.configure`
  - `apply_config`: loads `{config_id}.nxs` and applies grouped/ordered motor moves.
    Optional `detx` and `beam_stop_out` override only those two file setpoints
    before moving, obey `_move_required`, and are recorded in audit metadata.
    The final triangulation config application has no overrides and restores
    the file's detector and beamstop positions. Limits remain EPICS/Ophyd's
    responsibility; the planner has no detector travel range.
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
