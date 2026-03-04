from __future__ import annotations

from pathlib import Path

from mouse_bluesky.planner.logbook2bluesky import build_plan_specs_from_logbook
from mouse_bluesky.planner.validate import validate_specs
from mouse_bluesky.protocols.builtin import build_default_registry

LOGBOOK = Path("tests/data/example_logbook.xlsx")
PROJECTS = Path("tests/data/projects")
ROOT_PATH = Path("tests/data/mouse")
CONFIG_ROOT = Path("tests/data/mouse_configs")

registry = build_default_registry()

specs = build_plan_specs_from_logbook(
    logbook_path=LOGBOOK,
    project_base_path=PROJECTS,
    registry=registry,
    apply_config_extra_kwargs={"config_root": str(CONFIG_ROOT)},
    measurement_extra_kwargs={"root_path": str(ROOT_PATH)},
)

issues = validate_specs(specs, known_plans={"apply_config", "measure_yzstage"}, config_root=CONFIG_ROOT)

print(f"Generated {len(specs)} PlanSpecs")
if issues:
    print("Validation issues:")
    for i in issues:
        print(f"- [{i.kind}] {i.message} ({i.context})")
else:
    print("OK: no issues found")
