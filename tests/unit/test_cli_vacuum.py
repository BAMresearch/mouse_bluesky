import ast
import inspect
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from mouse_bluesky import cli
from mouse_bluesky.planner.models import PlanSpec
from mouse_bluesky.plans import vacuum

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def queue_stub(monkeypatch):
    calls = []
    responses = [{"success": True}]

    def populate_queue(specs, *, target, position):
        calls.append((specs, target, position))
        return responses

    def forbidden_request(*args, **kwargs):
        pytest.fail("The CLI must not make a Queue Server request outside populate_queue")

    monkeypatch.setattr(cli, "populate_queue", populate_queue)
    monkeypatch.setattr("mouse_bluesky.planner.logbook2bluesky.zmq_single_request", forbidden_request)
    monkeypatch.setattr(cli, "build_plan_specs_from_logbook", lambda **kwargs: [PlanSpec(name="measure_yzstage")])
    monkeypatch.setattr(cli, "validate_specs", lambda *args, **kwargs: [])
    return calls, responses


def command_args(command, *options):
    return [command, *(["unused.xlsx", "projects"] if command == "enqueue" else []), *options]


@pytest.mark.parametrize("command", ["evacuate", "ventilate", "enqueue"])
@pytest.mark.parametrize(
    "options, position",
    [
        ([], "back"),
        (["--prioritize"], "front"),
        (["--position", "front"], "front"),
        (["--position", "back", "--prioritize"], "front"),
    ],
)
def test_commands_enqueue_only_with_shared_options(queue_stub, capsys, command, options, position):
    calls, _ = queue_stub
    with pytest.raises(SystemExit) as exc:
        cli.main(command_args(command, *(["--enqueue-only"] if command != "enqueue" else []), *options))
    assert exc.value.code == 0
    assert len(calls) == 1
    specs, target, submitted_position = calls[0]
    assert len(specs) == 1
    assert specs[0].name == ("measure_yzstage" if command == "enqueue" else command)
    assert dict(specs[0].kwargs) == {}
    assert submitted_position == position
    assert target.zmq_control_addr == "tcp://127.0.0.1:60615"
    assert target.user == "mouse-bluesky"
    assert target.user_group == "primary"
    assert capsys.readouterr().out == "Enqueued 1 items to tcp://127.0.0.1:60615.\n"


@pytest.mark.parametrize("command", ["evacuate", "ventilate", "enqueue"])
def test_commands_accept_target_and_identity(queue_stub, capsys, command):
    calls, _ = queue_stub
    with pytest.raises(SystemExit) as exc:
        cli.main(
            command_args(
                command,
                *(["--enqueue-only"] if command != "enqueue" else []),
                "--zmq",
                "tcp://example.invalid:60615",
                "--user",
                "operator",
                "--user-group",
                "staff",
                "--quiet",
            )
        )
    assert exc.value.code == 0
    _, target, _ = calls[0]
    assert target.zmq_control_addr == "tcp://example.invalid:60615"
    assert target.user == "operator"
    assert target.user_group == "staff"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("command", ["evacuate", "ventilate", "enqueue"])
@pytest.mark.parametrize(
    "response",
    [
        {"success": False, "msg": "refused", "traceback": "details"},
        (False, "refused", "details"),
        SimpleNamespace(success=False, msg="refused", traceback="details"),
    ],
)
def test_rejected_items_have_nonzero_exit_and_preserve_enqueue_output(queue_stub, capsys, command, response):
    _, responses = queue_stub
    responses[:] = [response]
    with pytest.raises(SystemExit) as exc:
        cli.main(command_args(command, *(["--enqueue-only"] if command != "enqueue" else [])))
    assert exc.value.code == 1
    assert capsys.readouterr().out == "Queue add failed for 1 item(s):\n[1] msg=refused\ndetails\n"


@pytest.mark.parametrize("name, timeout", [("evacuate", 1800.0), ("ventilate", 600.0)])
def test_vacuum_plans_are_registered_without_loading_hardware(name, timeout):
    startup = ROOT / "qserver_profile/profile_mouse/startup"
    tree = ast.parse((startup / "00_plans.py").read_text())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "mouse_bluesky.plans.vacuum"
        for alias in node.names
    }
    assert name in imports
    plans = yaml.safe_load((startup / "existing_plans_and_devices.yaml").read_text())["existing_plans"]
    entry = plans[name]
    assert entry["module"] == "mouse_bluesky.plans.vacuum"
    assert entry["name"] == name
    assert entry["properties"]["is_generator"] is True
    assert list(plans).index(name) > list(plans).index("apply_config")
    params = {param["name"]: param for param in entry["parameters"]}
    assert list(params) == list(inspect.signature(getattr(vacuum, name)).parameters)
    assert float(params["timeout_s"]["default"]) == timeout
    assert params["namespace"]["default"] == "None"
    assert all(param["kind"]["name"] == "KEYWORD_ONLY" for param in params.values())


@pytest.mark.parametrize("name", ["evacuate", "ventilate"])
def test_scripts_are_executable_and_forward_options_to_stub_cli(tmp_path, name):
    script = ROOT / f"{name}.sh"
    assert os.access(script, os.X_OK)
    stub = tmp_path / "mouse-bluesky"
    stub.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$VACUUM_TEST_ARGS"\n')
    stub.chmod(0o755)
    args_file = tmp_path / "args"
    subprocess.run(
        [script.as_posix(), "--prioritize"],
        check=True,
        cwd=tmp_path,
        env={**os.environ, "PATH": tmp_path.as_posix(), "VACUUM_TEST_ARGS": args_file.as_posix()},
    )
    assert args_file.read_text().splitlines() == [name, "--zmq", "tcp://127.0.0.1:60615", "--prioritize"]
