# Contracts & inner workings

## YMD-complete marker

The CLI inserts `mark_ymd_complete` after the last `measure_yzstage` for each
distinct logbook date in the final queue order: after scheduling, collation,
configuration insertion and the measurement kwargs merge. It copies `root_path`
from that last measurement. There is one trigger per YMD, with no logbook marker
row and no per-batch trigger. Measurements without a YMD or with the unresolved
sentinel `20261232` are skipped. Library builders opt in with
`insert_ymd_complete=True`; CLI `validate` and `enqueue` enable it by default.

The marker is `<root>/<YYYY>/<YMD>/READY_FOR_PROCESSING.json`:

```json
{
  "format": "mouse-ymd-complete/1",
  "marker_id": "34ae6a61e06d4a6393aaef81728de385",
  "ymd": "20261118",
  "created": "2026-11-18T17:00:00+00:00",
  "files": [
    {"path": "20261118_3_0/COMPLETE", "size": 3},
    {"path": "20261118_3_0/image.h5", "size": 123}
  ],
  "sequences": [{"name": "20261118_3_0", "complete": true}]
}
```

- `format` identifies the schema version.
- `marker_id` is a fresh UUID4 hex string for this processing trigger.
- `ymd` is the eight-digit calendar date and must match the directory name.
- `created` is the creation time in ISO 8601 UTC with an explicit offset.
- `files` is sorted by relative POSIX path, with each regular file's size in
  bytes. It includes nested files and `COMPLETE` flags. It excludes symlinks,
  dotfiles, dot-directories (including `.keep`, sync partials and marker temp
  files), and the marker itself. Mtimes are used locally to detect changes but
  omitted from the manifest because share mtimes can differ.
- `sequences` lists visible direct subdirectories sorted by name, excluding
  symlinks. `complete` means that directory contains a regular `COMPLETE` file.
  The pipeline decides how to handle incomplete sequences.

`procpipeline` is omitted: the data pipeline reads it from the logbook and writes
it into the HDF5 files. The marker describes files and completion state; it does
not choose the processing workflow.

The plan requires an existing, nonempty YMD directory. It samples file sizes
and nanosecond mtimes every 2 s until unchanged for at least 10 s, with a 300 s
timeout. These timings are plan parameters. It writes JSON into
`.READY_FOR_PROCESSING.<marker_id>.tmp`, flushes and `fsync`s the file, then uses
`os.replace` to publish it atomically. Failure removes the temp file. A later
successful marker replaces an earlier one with a new `marker_id`.

The audit run persisted to Tiled carries `activity: "ymd_complete"`, `ymd`,
`marker_id` and the absolute POSIX `marker_path`, plus the usual facility and
instrument identity. A missing or empty directory, settle timeout, or filesystem
error closes the run with `exit_status="fail"` and a reason, prints a warning,
and returns normally so the queue continues. No new marker is published on
failure; an existing marker is retained. Abort and halt retain normal RunEngine
behavior, including an `abort` stop document, and do not publish a marker during
settling.

The sync tool may deliver the marker before its data. The standard-library-only
`mouse_bluesky.processing_marker.check_marker(ymd_directory)` is the reference
readiness check on the share. Its frozen `MarkerCheck` result contains `ready`,
`marker_id`, `missing`, `size_mismatch` and `problem`. Missing or invalid JSON,
unknown format, a mismatched YMD, or missing or differently sized listed files
means not ready. Additional unlisted files do not block readiness. Never start
processing solely because the marker exists.

## Protocol compilation contract

Input:
- `entry.protocol: str`
- `entry.additional_parameters: Dict[str, str]`

Output:
- `CompiledEntry(collate: CollatePolicy, plans: tuple[QueuePlan,...])`

Notes:
- Single-plan protocols compile to exactly one `QueuePlan`.
- Generator protocols compile to multiple `QueuePlan` items.

## Scheduler contract (barrier-aware collation)

Input:
- sequence of `CompiledEntry` in logbook order

Output:
- a flat `list[QueuePlan]`

Rules:
- contiguous ALLOW entries are collated together (stable sort key uses plan meta, e.g. config_id + sample_key)
- FORBID entries flush the buffer and are appended in place

## Configuration insertion contract

Input:
- scheduled `QueuePlan` list

Output:
- new list with `apply_config(config_id)` inserted before each measurement carrying a `config_id`

Rule:
- `config_id` may be sourced from `plan.meta["config_id"]` or `plan.parameters["config_id"]`

### Source energy and fail-stop behavior

`apply_config` and `measure_yzstage` share the legacy source selection rule:

| First digit of `config_id` | Source | Generator | PhotonEnergy (eV) | ThresholdEnergy (eV) |
|---|---|---|---|---|
| odd (e.g. 123) | Cu | `cu_generator` | 8047.78 | 4023.89 |
| even (e.g. 223) | Mo | `mo_generator` | 17480 | 8740 |

`apply_config` resolves the required `eiger` detector along with the motors,
before any motor moves. After the moves, it reads both energy readbacks and
skips writing only if both are within 1 eV of their targets. Otherwise it writes
photon energy first, then threshold energy, always both: the detector firmware
can reset the threshold when photon energy changes. Each write waits for
completion with a 60 s timeout and the same 1 eV tolerance as the readback
check. Both readbacks are then checked again; a mismatch raises `RuntimeError`
identifying the signal, target and readback.
Returning from Mo to Cu explicitly restores the Cu energies.

The audit run records `photon_energy_ev` and `threshold_energy_ev`. An energy
write failure, timeout or readback mismatch stops execution and closes that
audit run with `exit_status="fail"`; measurement must not continue.
`measure_yzstage` repeats the same energy guard before allocating its sequence
directory or opening the shutter, including when called without `apply_config`.
An energy failure there leaves the shutter unopened and creates no sequence
directory. When `apply_config` already set the energies, the guard adds no writes.

Before the energy guard, `measure_yzstage` reads the active generator's voltage
and current and requires finite power of at least 90% of nominal (Cu 27 W,
Mo 45 W). The order is power check, energy guard, sequence directory, then run.
A failed power check stops the queue and leaves nothing behind: no detector
writes, sequence directory, run documents or shutter commands. Read failures
propagate unchanged.

## NeXus state file contract

- file name: `{config_id}.nxs`
- group path: `/saxs/Saxslab`
- leaf datasets: scalar, named after PV/motor identifiers
- each dataset value becomes the target setpoint
- optional stage datasets:
  - YZ stage fields (if present, all required YZ fields must be present),
  - GI stage fields (if present, all required GI fields must be present).

## Baseline signal contract

`build_baseline_signals(namespace=...)` returns an ordered list of readable
signals for `SupplementalData.baseline`:

- always includes BASE mapped signals,
- conditionally includes YZ and GI stage signals if resolvable,
- conditionally includes generator readbacks (`cu/mo` voltage and current) if resolvable.

Duplicate signal objects are removed while preserving order.

## Run identity metadata

Every MOUSE run's start document carries `facility="BAM"` and
`instrument="MOUSE"` (case-sensitive). `station` is absent because MOUSE has
one set-up. The values are defined in `mouse_bluesky.identity.RUN_IDENTITY`
and applied by `configure_run_identity(RE)` in the Queue Server start-up
file `01_re.py`.

The RunEngine metadata validator enforces these values and the absence of
`station` on every run, while preserving the existing metadata validator.
Callers cannot supply `facility`, `instrument` or `station`, even with
matching values. `measure_yzstage` and the interactive entry points
`peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`, `ct` and
`test_measure` refuse these keys before reads, detector configuration or
directory creation.

Any other RunEngine writing MOUSE runs to Tiled, including a notebook or
interactive session, must call
`mouse_bluesky.identity.configure_run_identity(RE)` before running plans.

The timeline also relies on start metadata `sampleid`, `plan_name` and
`activity`, stop metadata `exit_status`, `reason` and `num_events`, and the
stream names `baseline`, `snapshot` and `mouse_eiger_measure`. These keys
and stream names must not change.

## Snapshot vs baseline

- Baseline: configured once at RE level; produces the `baseline` stream.
- Snapshot: emitted per measurement run right before acquisition (stream `snapshot`).

## Measurement defaults

- `measure_yzstage` uses an impossible-date sentinel (`20261232`) when `ymd`
  is omitted or `None`, instead of defaulting to the current date.
- This is a safety measure to avoid writing ad hoc or underspecified runs into
  an existing day-based data tree.
- Source selection currently follows a legacy config-id rule:
  - leading odd digit -> `cu_generator`
  - leading even digit -> `mo_generator`

## Interactive scan call contract

User-facing scan helpers support positional short forms:

- `peak_scan(motor, start, stop[, num, exposure_time])`
- `valley_scan(motor, start, stop[, num, exposure_time])`
- `edge_scan(motor, start, stop[, num, exposure_time])`
- `capillary_scan(motor, start, stop[, num, exposure_time])`

Shared runtime defaults:
- RunEngine defaults to interactive `RE` if omitted.
- Detector defaults to interactive `eiger` if omitted.

## Additional parameters parsing

Base behavior:
- Keep all values as strings.

Optional typed behavior:
- if `__json__` key exists, its value is parsed as a JSON object and merged over the base dict.

Validation:
- invalid JSON raises ValueError.
