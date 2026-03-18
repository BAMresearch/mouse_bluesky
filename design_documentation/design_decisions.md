# Design decisions

## 1) Protocols: single-plan vs generator

**Decision:** Support two categories:

1. **Single-plan protocols**:
   - `protocol` maps to a fully fledged Bluesky plan.
   - Planner queues it as **one** Queue Server plan item.
   - Benefit: can be executed interactively outside Queue Server for development/debugging.

2. **Generator protocols**:
   - `protocol` compiles to a list of plan items (each item = one run).
   - Benefit: reorderable / collatable scheduling, good for throughput optimization.

## 2) Collation policy only from logbook (`collate=ALLOW|FORBID`)

**Decision:** No CLI `--collate` switch. Collation is controlled exclusively by the per-entry parameter:
- `collate=FORBID`: barrier (no reordering across this entry).
- `collate=ALLOW`: eligible for collation within its contiguous ALLOW block.

**Rationale:** Matches beamtime operations: the logbook is the authoritative “what should be reordered” source.

## 3) Collate only contiguous ALLOW blocks

**Decision:** Collation is applied only within contiguous stretches of ALLOW entries, preserving high-level sequencing.

Example: `FORBID, ALLOW×5, FORBID, ALLOW×4`
- Collate inside the 5-entry block and inside the 4-entry block.
- Preserve the overall “chapter” sequence with FORBID barriers.

## 4) One MeasurementTask = one run in Tiled

**Decision:** Each measurement plan item corresponds to exactly **one** run.

**Rationale:**
- clear provenance and searchability in Tiled,
- restartability (resume after failures),
- easier data QA and audit.

## 5) Configuration application before every measurement

**Decision:** Insert `apply_config(config_id)` immediately before every queued measurement.

**Rationale:** Queue execution can be interrupted and priority measurements can be inserted at the front. Re-applying the requested configuration before each measurement keeps resumed queue execution reproducible without relying on the worker's current machine state.

**Operational note:** redundant `apply_config` calls are expected to be cheap because unchanged motors should remain at or near their target positions.

## 6) Snapshot before every measurement as a stream, not a separate run

**Decision:** Do **not** add an extra “snapshot run”. Instead:
- baseline is configured at RE level,
- a `snapshot` stream is emitted inside each measurement run right before acquisition.

**Rationale:** preserves “one run per measurement” while still capturing debugging signals immediately before data collection.

## 7) `additional_parameters` parsing

**Decision:** Keep the logbook schema as `Dict[str, str]`, but allow typed values using:
- optional `__json__` field containing a JSON object string.

**Rationale:** Excel-friendly, minimal schema change, allows lists/ints/dicts when needed.

## 8) RE / Queue Server / Tiled setup kept separate

**Decision:** The core library remains reusable and deployment-agnostic, while
this repo also ships a reference Queue Server startup profile. It provides:
- plans,
- planner,
- validators,
- protocol registry,
- reference startup scripts in `qserver_profile/profile_mouse/startup`.

**Rationale:** separation of concerns; avoids coupling to a specific deployment environment.

## 9) Interactive scan API favors short positional calls

**Decision:** User-facing interactive scans support concise usage:
- `scan_fn(motor, start, stop)`
- `scan_fn(motor, start, stop, num, exposure_time)`

with sensible defaults for detector and RunEngine resolution.

**Rationale:** this aligns with beamline console workflows and minimizes typing
for routine alignment scans.

## 10) Deterministic Eiger exposure path (no runtime signal guessing)

**Decision:** Exposure setting for interactive scans uses explicit Eiger-style
paths (`cam.acquire_time`, `cam.acquire_period`) instead of heuristic discovery.

**Rationale:** predictable behavior and simpler maintenance in a known detector
environment; IOC naming can be adjusted in one location when needed.
