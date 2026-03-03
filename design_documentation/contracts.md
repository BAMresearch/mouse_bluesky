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

## Snapshot vs baseline

- Baseline: configured once at RE level; produces the `baseline` stream.
- Snapshot: emitted per measurement run right before acquisition (stream `snapshot`).

## Additional parameters parsing

Base behavior:
- Keep all values as strings.

Optional typed behavior:
- if `__json__` key exists, its value is parsed as a JSON object and merged over the base dict.

Validation:
- invalid JSON raises ValueError.
