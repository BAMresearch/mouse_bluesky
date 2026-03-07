# Demo setup

This repository supports two practical demos:

## 1) Interactive RunEngine demo (no Queue Server)

Purpose: quickly verify that compiled `PlanSpec`s can be materialized and executed.

1. Start a Jupyter session in this repo.
2. Build specs from the example logbook:

```python
from pathlib import Path
from mouse_bluesky.protocols.builtin import build_default_registry
from mouse_bluesky.planner.logbook2bluesky import build_plan_specs_from_logbook

specs = build_plan_specs_from_logbook(
    logbook_path=Path("tests/data/example_logbook.xlsx"),
    project_base_path=Path("tests/data/projects"),
    registry=build_default_registry(),
    apply_config_extra_kwargs={"config_root": "/path/to/configs"},
    measurement_extra_kwargs={"root_path": "/data/mouse"},
)
```

3. Materialize and execute with simulated devices (you will need to wire `plan_funcs` to your actual plans/devices).

```python
from bluesky import RunEngine

from mouse_bluesky.planner.materialize import materialize_plans
from mouse_bluesky.plans.public import measure_yzstage
from mouse_bluesky.plans.configure import apply_config

RE = RunEngine({})
plan_funcs = {
    "measure_yzstage": measure_yzstage,
    "apply_config": apply_config,
}

for plan in materialize_plans(specs, plan_funcs):
    RE(plan)
```

Notes:
- In production you will provide the device objects (Eiger, motors, shutters) via the Queue Server worker startup.
- Baseline can be configured using `build_baseline_signals(...)` from `plans.configure`.

## 2) Queue Server demo

Purpose: validate end-to-end queue population.

1. Start Queue Server manager/worker using your beamline startup profile (recommended).
   The reference profile in this repo is under `qserver_profile/startup/`:
   - `00_plans.py`: exports public plans, standard Bluesky plans, and interactive scans.
   - `01_re.py`: RunEngine.
   - `02_tiledwriter.py`: optional TiledWriter subscription.
   - `03_init_devices.py`: devices (including generators).
   - `04_baseline.py`: SupplementalData baseline setup.
2. Validate the queue from the command line:

```bash
mouse-bluesky validate /path/to/logbook.xlsx /path/to/projects --root-path /data/mouse --config-root /data/mouse_configs
```

3. Enqueue into a running Queue Server:

```bash
mouse-bluesky enqueue /path/to/logbook.xlsx /path/to/projects --zmq tcp://127.0.0.1:60615 \
  --root-path /data/mouse --config-root /data/mouse_configs
```

4. Start the queue using Queue Server UI/CLI.

Notes:
- This repo uses the Queue Server ZMQ control API (`queue_item_add`) to populate the queue.
- The worker environment must register the plan names referenced by the planner (`measure_yzstage`, `apply_config`, plus any custom single-plan protocols).
- Interactive console sessions (`qserver-console`, `qserver-qtconsole`) can also run:
  - standard plans (`count`, `scan`, `rel_scan`, `list_scan`, `grid_scan`, ...),
  - interactive scans (`peak_scan`, `valley_scan`, `edge_scan`, `capillary_scan`).
