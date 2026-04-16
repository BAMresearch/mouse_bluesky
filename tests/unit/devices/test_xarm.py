from __future__ import annotations

import time

import pytest
from pint import UnitRegistry

from mouse_bluesky.devices.xarm import XArm850, XArmPose


class FakeXArmBackend:
    def __init__(self, *, move_delay_s: float = 0.0) -> None:
        self.position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # backend units: mm + degree
        self.move_delay_s = move_delay_s
        self.stop_requested = False
        self.state_history: list[int] = []
        self.connected = False
        self.last_set_position: tuple[float, float, float, float, float, float] | None = None

    def connect(self) -> int:
        self.connected = True
        return 0

    def disconnect(self) -> int:
        self.connected = False
        return 0

    def motion_enable(self, enable: bool) -> int:
        return 0 if enable else -1

    def set_mode(self, mode: int) -> int:
        return 0

    def set_state(self, state: int) -> int:
        self.state_history.append(state)
        if state == 4:
            self.stop_requested = True
        return 0

    def emergency_stop(self) -> int:
        self.stop_requested = True
        return 0

    def clean_error(self) -> int:
        return 0

    def get_position(self):
        return 0, list(self.position)

    def set_position(
        self,
        x: float,
        y: float,
        z: float,
        roll: float,
        pitch: float,
        yaw: float,
        *,
        wait: bool = True,
        timeout: float | None = None,
        speed: float | None = None,
        mvacc: float | None = None,
        is_radian: bool = False,
    ) -> int:
        self.stop_requested = False
        self.last_set_position = (x, y, z, roll, pitch, yaw)
        deadline = time.monotonic() + self.move_delay_s
        while time.monotonic() < deadline:
            if self.stop_requested:
                return -1
            time.sleep(0.005)
        if self.stop_requested:
            return -1
        self.position = [x, y, z, roll, pitch, yaw]
        return 0


def test_set_target_accepts_mapping_with_quantities() -> None:
    ureg = UnitRegistry()
    arm = XArm850(name="xarm", arm=FakeXArmBackend(), auto_connect=False)
    pose = arm.set_target(
        {
            "x": 0.1 * ureg.meter,
            "y": 200 * ureg.millimeter,
            "z": 0.3 * ureg.meter,
            "roll": 3.141592653589793 * ureg.radian,
            "pitch": 0 * ureg.degree,
            "yaw": 90 * ureg.degree,
        }
    )

    assert pose.x == pytest.approx(100.0)
    assert pose.y == pytest.approx(200.0)
    assert pose.z == pytest.approx(300.0)
    assert pose.roll == pytest.approx(180.0)
    assert pose.pitch == pytest.approx(0.0)
    assert pose.yaw == pytest.approx(90.0)
    assert arm.target == pose


def test_move_converts_public_units_to_backend_units() -> None:
    backend = FakeXArmBackend()
    arm = XArm850(
        name="xarm",
        arm=backend,
        auto_connect=False,
        length_unit="meter",
        angle_unit="radian",
        is_radian=False,
    )
    arm.set_target((0.1, 0.2, 0.3, 3.141592653589793, 0.0, 1.5707963267948966))
    status = arm.move_to_target(wait=True, timeout=1.0)

    assert status.done
    assert status.success
    assert backend.last_set_position is not None
    sent = backend.last_set_position
    assert sent[0] == pytest.approx(100.0)
    assert sent[1] == pytest.approx(200.0)
    assert sent[2] == pytest.approx(300.0)
    assert sent[3] == pytest.approx(180.0)
    assert sent[4] == pytest.approx(0.0)
    assert sent[5] == pytest.approx(90.0)

    readback = arm.readback_pose
    assert readback.x == pytest.approx(0.1)
    assert readback.y == pytest.approx(0.2)
    assert readback.z == pytest.approx(0.3)
    assert readback.roll == pytest.approx(3.141592653589793)
    assert readback.pitch == pytest.approx(0.0)
    assert readback.yaw == pytest.approx(1.5707963267948966)


def test_locate_returns_setpoint_and_readback() -> None:
    backend = FakeXArmBackend()
    backend.position = [10.0, 20.0, 30.0, 180.0, 0.0, 90.0]
    arm = XArm850(name="xarm", arm=backend, auto_connect=False)
    arm.set_target((11, 22, 33, 44, 55, 66))

    location = arm.locate()
    assert location["setpoint"] == pytest.approx((11.0, 22.0, 33.0, 44.0, 55.0, 66.0))
    assert location["readback"] == pytest.approx((10.0, 20.0, 30.0, 180.0, 0.0, 90.0))


def test_stop_mid_move_marks_status_failed() -> None:
    backend = FakeXArmBackend(move_delay_s=0.25)
    arm = XArm850(name="xarm", arm=backend, auto_connect=False)

    status = arm.move_to((50, 60, 70, 180, 0, 45), timeout=1.0, wait=False)
    time.sleep(0.05)
    arm.stop()

    with pytest.raises(RuntimeError, match="stopped"):
        status.wait(timeout=1.0)
    assert status.done
    assert not status.success
    assert 4 in backend.state_history
    assert arm.moving.get() == 0


def test_pause_resume_uses_backend_state_commands() -> None:
    backend = FakeXArmBackend()
    arm = XArm850(name="xarm", arm=backend, auto_connect=False)

    arm.pause()
    arm.resume()

    assert 4 in backend.state_history
    assert 0 in backend.state_history
    assert arm.connected.get() == 1
    assert arm.last_status_code.get() == 0
