# tests/test_plan_parameters_contract.py
from mouse_bluesky.planner.validate import validate_specs
from mouse_bluesky.planner.logbook2bluesky import build_plan_specs_from_logbook
from mouse_bluesky.protocols.builtin import build_default_registry
from pathlib import Path

def test_compiled_specs_have_required_kwargs():
    specs = build_plan_specs_from_logbook(
        logbook_path=Path("tests/data/example_logbook.xlsx"),
        project_base_path=Path("tests/data/projects"),
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": "tests/data/mouse_configs"},
        measurement_extra_kwargs={"root_path": "tests/data/mouse"},
    )
    issues = validate_specs(
        specs,
        known_plans={"apply_config", "measure_yzstage"},
        config_root=Path("tests/data/mouse_configs"),
    )
    assert issues == []