import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from bluesky_queueserver.manager.profile_ops import validate_plan

from mouse_bluesky import cli
from mouse_bluesky.planner import logbook2bluesky
from mouse_bluesky.planner.config_insertion import insert_apply_config_before_measurements
from mouse_bluesky.planner.models import CollatePolicy, CompiledEntry, PlanSpec
from mouse_bluesky.planner.params import parse_additional_parameters
from mouse_bluesky.planner.validate import validate_specs
from mouse_bluesky.plans.configure import apply_config
from mouse_bluesky.plans.public import measure_yzstage
from mouse_bluesky.protocols.builtin import build_default_registry
from mouse_bluesky.protocols.registry import ProtocolRegistry, ProtocolSpec
from mouse_bluesky.protocols.triangulation import compile_triangulation


def entry(**changes):
    fields = dict(
        row_index=12,
        proposal="2026001",
        sampleid=7,
        sampos="A1",
        protocol="triangulation",
        additional_parameters={"configuration": "123"},
        batchnum=3,
        positions={"ysam": 1.2, "zsam": 3.4, "ysam.blank": 5.6, "zsam.blank": 7.8},
        ymd="20261119",
    )
    return SimpleNamespace(**(fields | changes))


def test_defaults_compile_full_measurements_and_restore():
    e = entry()
    compiled = compile_triangulation(e, {"configuration": 123})
    assert compiled.collate is CollatePolicy.FORBID
    assert len(compiled.specs) == 51
    for index, (spec, distance) in enumerate(zip(compiled.specs[:-1], np.linspace(500, -130, 50), strict=True)):
        assert spec.name == "measure_yzstage"
        assert spec.kwargs == {
            "entry_row_index": 12,
            "proposal": "2026001",
            "sampleid": 7,
            "sampos": "A1",
            "ymd": "20261119",
            "batchnum": 3,
            "config_id": 123,
            "repeat_index": 0,
            "sampleposition": dict(e.positions),
            "sample_exposure_time": 60.0,
            "md": {
                "protocol": "triangulation",
                "triangulation_index": index,
                "triangulation_points": 50,
                "triangulation_detx": float(distance),
            },
        }
        assert spec.meta == {
            "sample_key": "2026001-7",
            "config_id": 123,
            "step": index,
            "repeat": 0,
            "apply_config_kwargs": {"detx": float(distance), "beam_stop_out": True},
        }
        assert type(spec.meta["apply_config_kwargs"]["detx"]) is float
        assert not {"facility", "instrument"} & spec.kwargs["md"].keys()
    assert compiled.specs[-1] == PlanSpec("apply_config", kwargs={"config_id": 123}, meta={"config_id": 123})


@pytest.mark.parametrize(
    "overrides,start,stop,steps,duration",
    [
        ({"start": 450}, 450, -130, 50, 60),
        ({"stop": 12.5}, 500, 12.5, 50, 60),
        ({"steps": 3}, 500, -130, 3, 60),
        ({"duration": 4.5}, 500, -130, 50, 4.5),
        ({"start": -10, "stop": 40, "steps": 2, "duration": 0.5}, -10, 40, 2, 0.5),
    ],
)
def test_each_parameter_override(overrides, start, stop, steps, duration):
    result = compile_triangulation(entry(), {"configuration": 123, **overrides})
    assert [s.meta["apply_config_kwargs"]["detx"] for s in result.specs[:-1]] == list(np.linspace(start, stop, steps))
    assert all(s.kwargs["sample_exposure_time"] == duration for s in result.specs[:-1])
    assert all(s.kwargs["md"]["triangulation_points"] == steps for s in result.specs[:-1])


@pytest.mark.parametrize("json_params", [False, True])
def test_old_parameter_names_and_json_work_through_registry(json_params):
    params = {"configuration": 160, "start": 100, "stop": -20, "steps": 3, "duration": 2.5, "collate": "FORBID"}
    raw = {"__json__": json.dumps(params)} if json_params else {k: str(v) for k, v in params.items()}
    result = logbook2bluesky.compile_entries([entry(additional_parameters=raw)], registry=build_default_registry())[0]
    assert result.collate is CollatePolicy.FORBID
    assert [s.kwargs["md"]["triangulation_detx"] for s in result.specs[:-1]] == [100.0, 40.0, -20.0]
    assert all(s.kwargs["config_id"] == 160 for s in result.specs)
    assert all(s.kwargs["sample_exposure_time"] == 2.5 for s in result.specs[:-1])


@pytest.mark.parametrize(
    "params,message",
    [
        ({}, "requires 'configuration'"),
        ({"configuration": 1.5}, "'configuration' must be an int"),
        ({"configuration": True}, "'configuration' must be an int"),
        ({"configuration": "abc"}, "'configuration' must be an int"),
        ({"steps": 1}, "'steps' must be at least 2"),
        ({"steps": 0}, "'steps' must be at least 2"),
        ({"steps": -2}, "'steps' must be at least 2"),
        ({"steps": 2.5}, "'steps' must be an int"),
        ({"steps": "two"}, "'steps' must be an int"),
        ({"duration": 0}, "'duration' must be greater than 0"),
        ({"duration": -1}, "'duration' must be greater than 0"),
        ({"duration": "nan"}, "'duration' must be a finite number"),
        ({"duration": None}, "'duration' must be a finite number"),
        ({"start": float("inf")}, "'start' must be a finite number"),
        ({"stop": "abc"}, "'stop' must be a finite number"),
        ({"start": 10, "stop": 10}, "'start' and 'stop' must differ"),
        ({"configs": [123]}, "Unknown triangulation parameters: configs"),
        ({"collate": CollatePolicy.ALLOW}, "requires collate=FORBID"),
    ],
)
def test_invalid_parameters_fail_before_planning(params, message):
    # An empty mapping is the missing-configuration case; others use a valid config.
    supplied = {"configuration": 123, **params} if params else {}
    with pytest.raises(ValueError, match=message):
        compile_triangulation(entry(), supplied)


@pytest.mark.parametrize("insert_marker", [False, True])
def test_build_specs_inserts_independent_overrides_paths_and_marker(insert_marker):
    specs = logbook2bluesky.build_plan_specs(
        [entry(additional_parameters={"configuration": "123", "steps": "3"})],
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": "tests/data/mouse_configs"},
        measurement_extra_kwargs={"root_path": "/simulation/data"},
        insert_ymd_complete=insert_marker,
    )
    assert [s.name for s in specs] == ["apply_config", "measure_yzstage"] * 3 + (
        ["mark_ymd_complete"] if insert_marker else []
    ) + ["apply_config"]
    for index, distance in enumerate([500.0, 185.0, -130.0]):
        config, measurement = specs[2 * index : 2 * index + 2]
        assert config.kwargs == {
            "config_id": 123,
            "config_root": "tests/data/mouse_configs",
            "detx": distance,
            "beam_stop_out": True,
        }
        assert measurement.kwargs["root_path"] == "/simulation/data"
        assert measurement.kwargs["md"]["triangulation_index"] == index
        inspect.signature(measure_yzstage).bind(**measurement.kwargs)
    assert specs[-1].kwargs == {"config_id": 123, "config_root": "tests/data/mouse_configs"}
    if insert_marker:
        assert specs[-2].kwargs == {"ymd": "20261119", "root_path": "/simulation/data"}
    assert (
        validate_specs(
            specs,
            known_plans={"apply_config", "measure_yzstage", "mark_ymd_complete"},
            config_root="tests/data/mouse_configs",
        )
        == []
    )


@pytest.mark.parametrize("triangulation_first", [False, True])
def test_adjacent_standard_measurements_are_unchanged(triangulation_first):
    standard = entry(protocol="standard_measurements", additional_parameters={"__json__": '{"configs": [123, 160]}'})
    triangulation = entry(additional_parameters={"configuration": "123", "steps": "3"})
    options = dict(
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": "tests/data/mouse_configs"},
        measurement_extra_kwargs={"root_path": "/simulation/data"},
    )
    standard_only = logbook2bluesky.build_plan_specs([standard], **options)
    tri_only = logbook2bluesky.build_plan_specs([triangulation], **options)
    entries = [triangulation, standard] if triangulation_first else [standard, triangulation]
    combined = logbook2bluesky.build_plan_specs(entries, **options)
    assert combined == (tri_only + standard_only if triangulation_first else standard_only + tri_only)
    assert all("detx" not in s.kwargs and "beam_stop_out" not in s.kwargs for s in standard_only)


def test_extra_config_kwargs_do_not_overwrite_protocol_spec_keys():
    registry = ProtocolRegistry()
    explicit = PlanSpec("apply_config", kwargs={"config_id": 123, "config_root": "/protocol", "detx": 25.0})
    registry.register(ProtocolSpec("test", lambda e, p: CompiledEntry(CollatePolicy.FORBID, (explicit,))))
    result = logbook2bluesky.build_plan_specs(
        [entry(protocol="test")],
        registry=registry,
        apply_config_extra_kwargs={"config_root": "/global", "detx": 99, "config_id": 160},
    )
    assert result == [explicit]


def test_extra_config_kwargs_preserve_inserted_point_overrides():
    specs = logbook2bluesky.build_plan_specs(
        [entry(additional_parameters={"configuration": "123", "steps": "2"})],
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": "/global", "config_id": 160, "detx": 99, "beam_stop_out": False},
    )
    assert specs[0].kwargs == {"config_root": "/global", "config_id": 123, "detx": 500.0, "beam_stop_out": True}
    assert specs[2].kwargs == {"config_root": "/global", "config_id": 123, "detx": -130.0, "beam_stop_out": True}


def test_insertion_copies_overrides_without_changing_measurement():
    spec = PlanSpec(
        "measure_yzstage",
        kwargs={"config_id": 123},
        meta={
            "apply_config_kwargs": {"detx": 500.0, "beam_stop_out": True},
        },
    )
    config, unchanged = insert_apply_config_before_measurements([spec], extra_apply_kwargs={"detx": 99})
    assert config.kwargs == {"config_id": 123, "detx": 500.0, "beam_stop_out": True}
    assert unchanged is spec
    assert config.kwargs is not spec.meta["apply_config_kwargs"]


@pytest.mark.parametrize(
    "params,message", [({"configs": "123"}, "Unknown triangulation"), ({"collate": "ALLOW"}, "FORBID")]
)
def test_cli_validate_rejects_invalid_protocol_parameters_without_connections(monkeypatch, params, message):
    e = entry(additional_parameters={"configuration": "123", **params})
    monkeypatch.setattr(logbook2bluesky, "iter_mouse_logbook_entries", lambda **kwargs: [e])

    def forbidden(*args, **kwargs):
        pytest.fail("Validation must not contact Queue Server")

    monkeypatch.setattr(logbook2bluesky, "zmq_single_request", forbidden)
    with pytest.raises(ValueError, match=message):
        cli.main(["validate", "unused.xlsx", "projects"])


def test_queue_server_accepts_override_parameters_and_restore_without_loading_startup():
    plans = yaml.safe_load(Path("qserver_profile/profile_mouse/startup/existing_plans_and_devices.yaml").read_text())[
        "existing_plans"
    ]
    registered = plans["apply_config"]
    assert registered["module"] == "mouse_bluesky.plans.configure"
    assert registered["properties"]["is_generator"] is True
    params = {p["name"]: p for p in registered["parameters"]}
    signature = inspect.signature(apply_config)
    assert list(params) == list(signature.parameters)
    for name, parameter in signature.parameters.items():
        assert params[name]["annotation"]["type"] == repr(parameter.annotation)
        assert params[name]["kind"] == {"name": "KEYWORD_ONLY", "value": 3}
        if parameter.default is inspect.Parameter.empty:
            assert "default" not in params[name]
        else:
            assert params[name]["default"] == repr(parameter.default)
    specs = logbook2bluesky.build_plan_specs(
        [entry()],
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": "/simulation/configs"},
        measurement_extra_kwargs={"root_path": "/simulation/data"},
    )
    for spec in specs:
        valid, message = validate_plan(spec.to_qs_item(), allowed_plans=plans, allowed_devices={})
        assert valid, message
