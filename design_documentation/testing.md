# Testing strategy

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
  - inserts `apply_config` only when config changes
  - does not duplicate if repeated config IDs

- Static validation:
  - missing config files
  - missing HDF5 group
  - non-scalar datasets flagged

## Integration tests (optional, outside CI)

- connect to a test Queue Server instance and add a small queue
- run with simulated devices (Ophyd sim) where possible
