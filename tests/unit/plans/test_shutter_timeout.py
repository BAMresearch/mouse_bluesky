import ast
from pathlib import Path
from time import monotonic

import pytest
from bluesky.utils import FailedStatus
from ophyd.status import Status
from ophyd.utils import StatusTimeoutError

from mouse_bluesky.plans import shutter as shutter_plans
from tests.unit.plans.test_measure_failure import MeasurementRig, RecordingShutter


class StalledShutter(RecordingShutter):
    """Let one command expire through a real asynchronous timeout status."""

    def __init__(self, stalled_value):
        super().__init__()
        self.stalled_value = stalled_value
        self.stalled_status = None

    def set(self, value, *, timeout=None, **kwargs):
        if value == self.stalled_value and self.stalled_status is None:
            assert timeout is not None
            self.writes.append(value)
            self.timeouts.append(timeout)
            self.stalled_status = Status(self, timeout=timeout)
            self.statuses.append(self.stalled_status)
            return self.stalled_status
        return super().set(value, timeout=timeout, **kwargs)


@pytest.mark.parametrize("stalled_value", [1, 0], ids=["open", "strict-close"])
def test_stalled_shutter_fails_run_and_retries_close(tmp_path, monkeypatch, stalled_value):
    timeout_s = 0.03
    rig = MeasurementRig(tmp_path)
    shutter = rig.shutter = StalledShutter(stalled_value)
    rig.namespace["cu_generator"].shutter = shutter
    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", rig.acquire)
    monkeypatch.setitem(shutter_plans.set_shutter.__kwdefaults__, "timeout_s", timeout_s)
    start = monotonic()

    with pytest.raises(FailedStatus) as exc:
        rig.RE(rig.plan())

    elapsed = monotonic() - start
    assert timeout_s <= elapsed < 2  # A regression must not wait for the 10 s production timeout.
    assert isinstance(exc.value.__cause__, StatusTimeoutError)
    assert exc.value.__cause__ is shutter.stalled_status.exception()
    assert shutter.stalled_status.done and not shutter.stalled_status.success
    rig.assert_failed(exc.value)
    assert shutter.writes == ([1, 0] if stalled_value == 1 else [1, 0, 0])
    assert shutter.timeouts == (
        [timeout_s, shutter_plans.SHUTTER_CLOSE_TIMEOUT_S]
        if stalled_value == 1
        else [timeout_s, timeout_s, shutter_plans.SHUTTER_CLOSE_TIMEOUT_S]
    )
    assert len(rig.exposures) == (0 if stalled_value == 1 else 3)
    assert shutter.get() == 0
    assert rig.beam_stop.bsr.position == rig.in_position


@pytest.mark.parametrize("value", [0, 1])
def test_set_shutter_defaults_to_ten_second_timeout(value):
    shutter = RecordingShutter()
    messages = list(shutter_plans.set_shutter(shutter, value))

    assert shutter_plans.SHUTTER_SET_TIMEOUT_S == 10
    assert [msg.command for msg in messages] == ["set", "wait"]
    assert messages[0].obj is shutter
    assert messages[0].args == (value,)
    assert messages[0].kwargs["timeout"] == 10
    assert messages[1].kwargs["group"] == messages[0].kwargs["group"]


def test_interactive_shutter_plans_use_timed_helper():
    source = Path("qserver_profile/profile_mouse/startup/05_interactive.py").read_text()
    module = ast.parse(source)
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "mouse_bluesky.plans.shutter"
        and any(alias.name == "set_shutter" for alias in node.names)
        for node in module.body
    )
    for name, value in (("open_shutter", 1), ("close_shutter", 0)):
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name)
        calls = [node for statement in function.body for node in ast.walk(statement) if isinstance(node, ast.Call)]
        assert len(calls) == 1
        call = calls[0]
        assert isinstance(call.func, ast.Name) and call.func.id == "set_shutter"
        assert ast.unparse(call.args[0]) == "cu_generator.shutter"
        assert ast.literal_eval(call.args[1]) == value
    assert "bps.mv(cu_generator.shutter" not in source
