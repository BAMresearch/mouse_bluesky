# Examples

These examples demonstrate how to use **mouse_bluesky** safely.

## Contents

- `01_compile_validate.py` – Compile a logbook into `PlanSpec`s and run static validation.
- `02_enqueue_queue_server.py` – Enqueue compiled plans into a running Queue Server via ZMQ control socket.
- `03_interactive_runengine_sim.py` – Run a small sequence interactively using `RunEngine` (no Queue Server required).

Environment variables used by the CLI and examples:

- `MOUSE_DATA_ROOT` – default `root_path`
- `MOUSE_CONFIG_ROOT` – default `config_root`
