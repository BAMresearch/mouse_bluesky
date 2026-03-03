# Architecture

## Scope

This repository implements:

- **Bluesky plans** for MOUSE measurements (atomic measurement + higher-level wrappers).
- A **logbook-driven planner** that compiles logbook entries into **Queue Server** plan items and pushes them via the Queue Server API.
- **Static pre-validation** of the planned queue (plan names, config files, minimal HDF5 structure sanity checks).

This repository **does not** own or bundle beamline startup:
- RunEngine creation, `SupplementalData` baseline configuration, device instantiation, Queue Server startup, and TiledWriter wiring are expected to live in the beamline startup/profile repo.

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
  - `apply_config`: framework stub to load `{config_id}.nxs` and set PV/motor targets carefully.
- `mouse_bluesky.plans.snapshot`
  - `snapshot_state`: reads debugging signals into a dedicated stream (e.g. `snapshot`).

## Streams & metadata strategy

- **Baseline stream** (recommended): configured once on the RunEngine via `SupplementalData(baseline=[...])`.
- **Snapshot stream**: emitted inside each measurement run, immediately before detector acquisition, for “debugging before every measurement”.
- **RunStart metadata**:
  - should include `entry_row_index`, `config_id`, `repeat_index`, and a filtered `logbook_entry` dictionary (JSON-friendly).

## NeXus configuration state file contract

- Config file: `{config_id}.nxs`
- Settings stored as scalar datasets under:
  - `/saxs/Saxslab/<pv_or_motor_name> = <scalar_value>`

The configuration loader reads those scalars to a dict and applies them via `bps.mv` (sequenced to avoid power-supply overload).
