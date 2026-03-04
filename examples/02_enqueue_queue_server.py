from __future__ import annotations

from pathlib import Path

from mouse_bluesky.planner.logbook2bluesky import QueueServerTarget, build_plan_specs_from_logbook, populate_queue
from mouse_bluesky.planner.validate import validate_specs
from mouse_bluesky.protocols.builtin import build_default_registry

LOGBOOK = Path("tests/data/example_logbook.xlsx")
PROJECTS = Path("tests/data/projects")
ROOT_PATH = Path("tests/data/mouse")
CONFIG_ROOT = Path("tests/data/mouse_configs")

ZMQ = "tcp://127.0.0.1:60615"

registry = build_default_registry()

specs = build_plan_specs_from_logbook(
    logbook_path=LOGBOOK,
    project_base_path=PROJECTS,
    registry=registry,
    apply_config_extra_kwargs={"config_root": str(CONFIG_ROOT)},
    measurement_extra_kwargs={"root_path": str(ROOT_PATH)},
)

issues = validate_specs(specs, known_plans={"apply_config", "measure_yzstage"}, config_root=CONFIG_ROOT)
if issues:
    raise SystemExit(f"Refusing to enqueue: {len(issues)} validation issue(s). Run examples/01_compile_validate.py")

target = QueueServerTarget(zmq_control_addr=ZMQ)
responses = populate_queue(specs, target=target, position="back")

print(f"Enqueued {len(specs)} items. Last response: {responses[-1] if responses else None}")
