# Contracts & inner workings

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
