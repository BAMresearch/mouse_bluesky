import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from mouse_bluesky import cli
from mouse_bluesky.planner import logbook2bluesky
from mouse_bluesky.planner.marker_insertion import insert_ymd_complete_markers
from mouse_bluesky.planner.models import PlanSpec
from mouse_bluesky.planner.validate import validate_specs
from mouse_bluesky.plans.processing import mark_ymd_complete
from mouse_bluesky.protocols.builtin import build_default_registry


def measure(ymd="20261118", **kwargs):
    return PlanSpec(name="measure_yzstage", kwargs={"ymd": ymd, **kwargs}, meta={"original": True})


def marker(ymd="20261118", **kwargs):
    return PlanSpec(name="mark_ymd_complete", kwargs={"ymd": ymd, **kwargs}, meta={"ymd": ymd})


def entry(row=1, **kwargs):
    fields = dict(
        row_index=row,
        proposal="P",
        sampleid=row,
        sampos="A",
        protocol="standard_measurements",
        additional_parameters={"__json__": '{"configs": [123, 160]}'},
        batchnum=3,
        positions={},
        ymd="20261118",
    )
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def test_single_ymd_marker_copies_root_from_last_measurement():
    specs = [measure(root_path="first"), measure(root_path="last")]
    assert insert_ymd_complete_markers(specs) == [*specs, marker(root_path="last")]
    assert len(specs) == 2


def test_interleaved_ymds_and_other_plans_keep_order():
    a, b, final_a = measure(), measure("20261119"), measure(root_path="last")
    config = PlanSpec(name="apply_config", kwargs={"ymd": "20261118", "config_id": 123})
    other = PlanSpec(name="other")
    specs = [a, config, b, other, final_a, other]
    assert insert_ymd_complete_markers(specs) == [
        a,
        config,
        b,
        marker("20261119"),
        other,
        final_a,
        marker(root_path="last"),
        other,
    ]


def test_missing_and_sentinel_dates_are_skipped():
    specs = [PlanSpec(name="measure_yzstage"), measure("20261232"), measure(None)]
    assert insert_ymd_complete_markers(specs) == specs


def test_no_measurements_is_unchanged():
    specs = [PlanSpec(name="apply_config"), PlanSpec(name="other", kwargs={"ymd": "20261118"})]
    assert insert_ymd_complete_markers(specs) == specs
    assert insert_ymd_complete_markers([]) == []


def test_custom_plan_names():
    specs = [PlanSpec(name="measurement", kwargs={"ymd": "20261118"})]
    assert insert_ymd_complete_markers(specs, measurement_plan_name="measurement", marker_plan_name="ready") == [
        *specs,
        PlanSpec(name="ready", kwargs={"ymd": "20261118"}, meta={"ymd": "20261118"}),
    ]


@pytest.mark.parametrize("extra", [None, {"root_path": "/custom/data", "ymd": "20261119"}])
def test_build_specs_defaults_unchanged_and_markers_follow_merge_and_scheduling(extra):
    entries = [entry(), entry(2)]
    registry = build_default_registry()
    default = logbook2bluesky.build_plan_specs(entries, registry=registry, measurement_extra_kwargs=extra)
    assert [s.name for s in default] == ["apply_config", "measure_yzstage"] * 4
    assert [s.kwargs["config_id"] for s in default if s.name == "measure_yzstage"] == [123, 123, 160, 160]
    marked = logbook2bluesky.build_plan_specs(
        entries, registry=registry, measurement_extra_kwargs=extra, insert_ymd_complete=True
    )
    expected = marker("20261119", root_path="/custom/data") if extra else marker()
    assert marked == [*default, expected]


def test_from_logbook_forwards_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(logbook2bluesky, "iter_mouse_logbook_entries", lambda **kwargs: [entry()])
    specs = logbook2bluesky.build_plan_specs_from_logbook(
        logbook_path=tmp_path / "unused.xlsx",
        project_base_path=tmp_path,
        registry=build_default_registry(),
        insert_ymd_complete=True,
        measurement_extra_kwargs={"root_path": str(tmp_path)},
    )
    assert specs[-1] == marker(root_path=str(tmp_path))


@pytest.mark.parametrize("command", ["validate", "enqueue"])
@pytest.mark.parametrize("disabled", [False, True])
def test_cli_inserts_known_marker_by_default(monkeypatch, tmp_path, capsys, command, disabled):
    monkeypatch.setattr(logbook2bluesky, "iter_mouse_logbook_entries", lambda **kwargs: [entry()])
    queued = []

    def populate(specs, **kwargs):
        queued.extend(specs)
        return [{"success": True}] * len(specs)

    def forbidden(*args, **kwargs):
        pytest.fail("Test must not contact Queue Server")

    monkeypatch.setattr(cli, "populate_queue", populate)
    monkeypatch.setattr(logbook2bluesky, "zmq_single_request", forbidden)
    args = [
        command,
        "unused.xlsx",
        "projects",
        "--root-path",
        str(tmp_path),
        "--config-root",
        "tests/data/mouse_configs",
    ]
    if command == "validate":
        args += ["--print-specs", "20"]
    if disabled:
        args += ["--no-ymd-complete"]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "unknown_plan" not in output
    if command == "validate":
        assert ("mark_ymd_complete" in output) is not disabled
        if not disabled:
            assert output.splitlines()[-1] == f"mark_ymd_complete {{'ymd': '20261118', 'root_path': '{tmp_path}'}}"
    else:
        assert (queued[-1].name == "mark_ymd_complete") is not disabled
        if not disabled:
            assert queued[-1] == marker(root_path=str(tmp_path))


def test_marker_validation_requires_ymd():
    issues = validate_specs([PlanSpec(name="mark_ymd_complete")], known_plans={"mark_ymd_complete"})
    assert len(issues) == 1
    assert issues[0].kind == "missing_marker_kwarg"
    assert "ymd" in issues[0].message
    assert validate_specs([marker()]) == []


def test_queue_server_exposes_marker_and_parameter_signature_without_loading_hardware():
    startup = Path("qserver_profile/profile_mouse/startup")
    tree = ast.parse((startup / "00_plans.py").read_text())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "mouse_bluesky.plans.processing"
        for alias in node.names
    }
    assert "mark_ymd_complete" in imports
    plans = yaml.safe_load((startup / "existing_plans_and_devices.yaml").read_text())["existing_plans"]
    registered = plans["mark_ymd_complete"]
    assert registered["name"] == "mark_ymd_complete"
    assert registered["module"] == "mouse_bluesky.plans.processing"
    assert registered["properties"]["is_generator"] is True
    assert list(plans).index("mark_ymd_complete") == list(plans).index("evacuate") + 1
    params = {p["name"]: p for p in registered["parameters"]}
    signature = inspect.signature(mark_ymd_complete)
    assert list(params) == list(signature.parameters)
    for name, parameter in signature.parameters.items():
        assert params[name]["kind"] == {"name": "KEYWORD_ONLY", "value": 3}
        if parameter.default is inspect.Parameter.empty:
            assert "default" not in params[name]
        else:
            assert params[name]["default"] == repr(parameter.default)
