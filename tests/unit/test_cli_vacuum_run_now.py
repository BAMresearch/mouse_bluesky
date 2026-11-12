from types import SimpleNamespace

import pytest

from mouse_bluesky import cli
from mouse_bluesky.planner.models import PlanSpec

ADDRESS = "tcp://127.0.0.1:60615"
STOP = {"item_type": "instruction", "name": "queue_stop"}
IDLE = {"manager_state": "idle", "worker_environment_exists": True}
ACCEPTED = {"success": True, "msg": ""}
BATCH = {"success": True, "items": [{"item_uid": "plan-uid"}, {"item_uid": "stop-uid"}]}


@pytest.fixture(params=["evacuate", "ventilate"])
def command(request):
    return request.param


@pytest.fixture
def requests_stub(monkeypatch):
    stub = SimpleNamespace(calls=[], addresses=[], responses=[])

    def record(method, params, address):
        stub.calls.append((method, params))
        stub.addresses.append(address)
        assert stub.responses, f"Unexpected request: {method}"
        return stub.responses.pop(0)

    def install(responses, *, address_keyword="zmq_control_addr"):
        stub.responses[:] = responses

        def control_request(method, params=None, *, zmq_control_addr):
            return record(method, params, zmq_control_addr)

        def server_request(method, params=None, *, zmq_server_address):
            return record(method, params, zmq_server_address)

        monkeypatch.setattr(
            "mouse_bluesky.planner.logbook2bluesky.zmq_single_request",
            control_request if address_keyword == "zmq_control_addr" else server_request,
        )
        return stub

    # Prevent any live request, including in tests that expect no requests.
    install([])
    return install


def invoke(command, *options):
    with pytest.raises(SystemExit) as exc:
        cli.main([command, *options])
    return exc.value.code


def batch_request(command, *, user="mouse-bluesky", user_group="primary"):
    return (
        "queue_item_add_batch",
        {"items": [PlanSpec(name=command).to_qs_item(), STOP], "pos": "front", "user": user, "user_group": user_group},
    )


@pytest.mark.parametrize("address_keyword", ["zmq_control_addr", "zmq_server_address"])
@pytest.mark.parametrize("options", [[], ["--prioritize"], ["--position", "front"]])
def test_runs_plan_then_stop(command, requests_stub, capsys, address_keyword, options):
    stub = requests_stub([(IDLE, ""), (BATCH, ""), (ACCEPTED, "")], address_keyword=address_keyword)
    assert invoke(command, *options) == 0
    assert stub.calls == [("status", None), batch_request(command), ("queue_start", None)]
    assert stub.addresses == [ADDRESS] * 3
    assert capsys.readouterr().out == (
        f"Started {command} at the front of the queue on {ADDRESS}; the queue will stop after it.\n"
    )


def test_target_and_identity_reach_requests(command, requests_stub, capsys):
    stub = requests_stub([(IDLE, ""), (BATCH, ""), (ACCEPTED, "")])
    address = "tcp://example.invalid:60615"
    assert invoke(command, "--zmq", address, "--user", "operator", "--user-group", "staff") == 0
    assert stub.calls == [
        ("status", None),
        batch_request(command, user="operator", user_group="staff"),
        ("queue_start", None),
    ]
    assert stub.addresses == [address] * 3
    assert address in capsys.readouterr().out


@pytest.mark.parametrize(
    "status, error, expected",
    [
        ({**IDLE, "manager_state": "paused"}, "", "paused"),
        ({**IDLE, "manager_state": "executing_queue"}, "", "executing_queue"),
        ({**IDLE, "manager_state": "starting_queue"}, "", "starting_queue"),
        ({**IDLE, "worker_environment_exists": False}, "", "idle"),
        ({"manager_state": "idle"}, "", "idle"),
        ({**IDLE, "success": False, "msg": "status rejected"}, "", "status rejected"),
        (None, "timeout", "timeout"),
    ],
)
@pytest.mark.parametrize("options", [[], ["--quiet"]])
def test_refuses_unavailable_queue(command, requests_stub, capsys, status, error, expected, options):
    stub = requests_stub([(status, error)])
    assert invoke(command, *options) == 1
    assert stub.calls == [("status", None)]
    output = capsys.readouterr().out
    assert expected in output
    assert "Stop the queue, wait until it is idle, then run the command again." in output


@pytest.mark.parametrize("response", [({"success": False, "msg": "batch rejected"}, ""), (None, "timeout")])
def test_batch_failure_does_not_start(command, requests_stub, capsys, response):
    stub = requests_stub([(IDLE, ""), response])
    assert invoke(command) == 1
    assert stub.calls == [("status", None), batch_request(command)]
    assert (response[1] or response[0]["msg"]) in capsys.readouterr().out


@pytest.mark.parametrize("response", [({"success": False, "msg": "start rejected"}, ""), (None, "timeout")])
def test_start_failure_removes_plan_then_stop(command, requests_stub, capsys, response):
    stub = requests_stub([(IDLE, ""), (BATCH, ""), response, (ACCEPTED, ""), (ACCEPTED, "")])
    assert invoke(command) == 1
    assert stub.calls == [
        ("status", None),
        batch_request(command),
        ("queue_start", None),
        ("queue_item_remove", {"uid": "plan-uid"}),
        ("queue_item_remove", {"uid": "stop-uid"}),
    ]
    output = capsys.readouterr().out
    assert (response[1] or response[0]["msg"]) in output
    assert "Removed plan (plan-uid)." in output
    assert "Removed queue stop (stop-uid)." in output


@pytest.mark.parametrize("response", [({"success": False, "msg": "already running"}, ""), (None, "timeout")])
def test_failed_plan_removal_leaves_stop_in_place(command, requests_stub, capsys, response):
    stub = requests_stub([(IDLE, ""), (BATCH, ""), (None, "timeout"), response])
    assert invoke(command, "--quiet") == 1
    assert stub.calls == [
        ("status", None),
        batch_request(command),
        ("queue_start", None),
        ("queue_item_remove", {"uid": "plan-uid"}),
    ]
    output = capsys.readouterr().out
    assert "Could not remove plan (plan-uid)" in output
    assert (response[1] or response[0]["msg"]) in output
    assert "The queue stop was left in place." in output


def test_failed_stop_removal_is_reported(command, requests_stub, capsys):
    stub = requests_stub(
        [(IDLE, ""), (BATCH, ""), (None, "timeout"), (ACCEPTED, ""), ({"success": False, "msg": "locked"}, "")]
    )
    assert invoke(command) == 1
    assert stub.calls[-2:] == [
        ("queue_item_remove", {"uid": "plan-uid"}),
        ("queue_item_remove", {"uid": "stop-uid"}),
    ]
    output = capsys.readouterr().out
    assert "Removed plan (plan-uid)." in output
    assert "Could not remove queue stop (stop-uid): locked." in output
    assert "The queue stop was left in place." in output


def test_position_back_requires_enqueue_only(command, requests_stub, capsys):
    stub = requests_stub([])
    assert invoke(command, "--position", "back") == 2
    assert stub.calls == []
    assert "--enqueue-only" in capsys.readouterr().err


def test_quiet_suppresses_success(command, requests_stub, capsys):
    stub = requests_stub([(IDLE, ""), (BATCH, ""), (ACCEPTED, "")])
    assert invoke(command, "--quiet") == 0
    assert stub.calls == [("status", None), batch_request(command), ("queue_start", None)]
    assert capsys.readouterr().out == ""
