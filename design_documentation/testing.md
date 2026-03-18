# Testing strategy

Tests are organized into:

- `tests/unit/` for deterministic, isolated tests.
- `tests/integration/` for cross-module behavior with simulated devices/runtime.

## Unit tests (pytest)

Focus on deterministic, hardware-free tests:

- `parse_additional_parameters`
  - plain strings
  - `__json__` override
  - `collate` parsing

- Scheduler:
  - `FORBID` creates barriers
  - `ALLOW` blocks collate internally
  - overall segment order preserved

- Config insertion:
  - inserts `apply_config` before every measurement
  - preserves the scheduled measurement order

- Static validation:
  - missing config files
  - missing HDF5 group
  - non-scalar datasets flagged

- Interactive scan helpers:
  - fit-model guess construction
  - runtime default resolution (`RE`, default detector, detector field)
  - deterministic exposure configuration for Eiger-style detector paths
  - baseline signal builder composition for optional devices

## Integration tests

- Interactive scans with simulated detector/motor bundles:
  - `peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`
  - verify fit centers and behavior under realistic synthetic profiles

## Recommended commands

```bash
pytest tests/unit tests/integration
```
