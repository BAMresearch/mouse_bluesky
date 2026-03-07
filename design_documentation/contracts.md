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
- new list with `apply_config(config_id)` inserted only when config_id changes

Rule:
- `config_id` may be sourced from `plan.meta["config_id"]` or `plan.parameters["config_id"]`

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
