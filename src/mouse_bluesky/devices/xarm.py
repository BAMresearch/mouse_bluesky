from __future__ import annotations

import inspect
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol, TypeAlias

from ophyd import Component as Cpt
from ophyd import Device, Signal
from ophyd.status import DeviceStatus, InvalidState
from pint import Quantity, UnitRegistry

POSE_FIELDS = ("x", "y", "z", "roll", "pitch", "yaw")
UNIT_REGISTRY = UnitRegistry()

ScalarLike: TypeAlias = float | int | Quantity


@dataclass(frozen=True, slots=True)
class XArmPose:
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.x, self.y, self.z, self.roll, self.pitch, self.yaw)


PoseLike: TypeAlias = XArmPose | Mapping[str, ScalarLike] | Sequence[ScalarLike]


class XArmBackend(Protocol):
    def set_position(
        self,
        x: float,
        y: float,
        z: float,
        roll: float,
        pitch: float,
        yaw: float,
        **kwargs: Any,
    ) -> Any: ...

    def get_position(self, **kwargs: Any) -> Any: ...


def _extract_status_code(response: Any) -> int | None:
    if response is None:
        return None
    if isinstance(response, bool):
        return 0 if response else -1
    if isinstance(response, int):
        return response
    if isinstance(response, tuple) and response and isinstance(response[0], int):
        return response[0]
    return None


def _call_with_supported_kwargs(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if not kwargs:
        return method(*args)
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        try:
            return method(*args, **kwargs)
        except TypeError:
            return method(*args)

    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return method(*args, **kwargs)

    accepted = {k: v for k, v in kwargs.items() if k in signature.parameters}
    return method(*args, **accepted)


def _safe_set_finished(status: DeviceStatus) -> None:
    try:
        status.set_finished()
    except InvalidState:
        return


def _safe_set_exception(status: DeviceStatus, exc: Exception) -> None:
    try:
        status.set_exception(exc)
    except InvalidState:
        return


class XArm850(Device):
    """
    Ophyd wrapper around xArm 850 Cartesian pose moves via xArm Python SDK.

    Implements Bluesky-relevant interfaces:
    - `set(...)` / `check_value(...)` for movable plans
    - `locate()` for setpoint + readback tracking
    - `stop(...)` / `pause()` / `resume()` for safe interruption handling
    """

    target_x = Cpt(Signal, value=0.0, kind="config")
    target_y = Cpt(Signal, value=0.0, kind="config")
    target_z = Cpt(Signal, value=0.0, kind="config")
    target_roll = Cpt(Signal, value=0.0, kind="config")
    target_pitch = Cpt(Signal, value=0.0, kind="config")
    target_yaw = Cpt(Signal, value=0.0, kind="config")

    readback_x = Cpt(Signal, value=0.0, kind="hinted")
    readback_y = Cpt(Signal, value=0.0, kind="hinted")
    readback_z = Cpt(Signal, value=0.0, kind="hinted")
    readback_roll = Cpt(Signal, value=0.0, kind="hinted")
    readback_pitch = Cpt(Signal, value=0.0, kind="hinted")
    readback_yaw = Cpt(Signal, value=0.0, kind="hinted")

    moving = Cpt(Signal, value=0, kind="normal")
    connected = Cpt(Signal, value=0, kind="normal")
    last_status_code = Cpt(Signal, value=0, kind="normal")

    def __init__(
        self,
        prefix: str = "",
        *,
        host: str | None = None,
        arm: XArmBackend | None = None,
        auto_connect: bool = True,
        disconnect_on_unstage: bool = False,
        default_speed: ScalarLike | None = None,
        default_acceleration: ScalarLike | None = None,
        length_unit: str = "millimeter",
        angle_unit: str = "degree",
        speed_unit: str = "millimeter/second",
        acceleration_unit: str = "millimeter/second**2",
        is_radian: bool = False,
        unit_registry: UnitRegistry | None = None,
        **kwargs: Any,
    ):
        super().__init__(prefix=prefix, **kwargs)
        if arm is None and host is None:
            raise ValueError("Provide either 'arm' or 'host' to build the xArm backend.")

        self._ureg = unit_registry or UNIT_REGISTRY
        self._display_length_unit = self._ureg.Unit(length_unit)
        self._display_angle_unit = self._ureg.Unit(angle_unit)
        self._display_speed_unit = self._ureg.Unit(speed_unit)
        self._display_acceleration_unit = self._ureg.Unit(acceleration_unit)

        self._backend_length_unit = self._ureg.millimeter
        self._backend_angle_unit = self._ureg.radian if is_radian else self._ureg.degree
        self._backend_speed_unit = self._ureg.millimeter / self._ureg.second
        self._backend_acceleration_unit = self._ureg.millimeter / (self._ureg.second**2)
        self._is_radian = is_radian

        self._validate_unit_dimensions()

        self._default_speed = (
            None
            if default_speed is None
            else self._coerce_scalar(default_speed, unit=self._display_speed_unit, label="default_speed")
        )
        self._default_acceleration = (
            None
            if default_acceleration is None
            else self._coerce_scalar(
                default_acceleration,
                unit=self._display_acceleration_unit,
                label="default_acceleration",
            )
        )

        self._arm = arm if arm is not None else self._build_backend(host=host, is_radian=is_radian)
        self._disconnect_on_unstage = disconnect_on_unstage

        self._move_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._active_status: DeviceStatus | None = None

        if auto_connect:
            self.connect()

    def _validate_unit_dimensions(self) -> None:
        reference_pairs = (
            ("length_unit", self._display_length_unit, self._backend_length_unit),
            ("angle_unit", self._display_angle_unit, self._ureg.degree),
            ("speed_unit", self._display_speed_unit, self._backend_speed_unit),
            ("acceleration_unit", self._display_acceleration_unit, self._backend_acceleration_unit),
        )
        for label, value_unit, reference_unit in reference_pairs:
            if value_unit.dimensionality != reference_unit.dimensionality:
                raise ValueError(
                    f"{label}={value_unit!s} is incompatible with expected dimension of {reference_unit!s}."
                )

    @staticmethod
    def _build_backend(*, host: str | None, is_radian: bool) -> XArmBackend:
        if host is None:
            raise ValueError("'host' must be provided when no pre-built backend is given.")
        try:
            from xarm.wrapper import XArmAPI
        except ImportError as exc:
            raise ImportError("Install `xarm-python-sdk` to use XArm850 without an injected backend.") from exc
        return XArmAPI(host, is_radian=is_radian)

    def _call_backend(self, method_name: str, *args: Any, required: bool = True, **kwargs: Any) -> Any:
        method = getattr(self._arm, method_name, None)
        if method is None:
            if required:
                raise AttributeError(f"xArm backend does not provide '{method_name}'")
            return None
        return _call_with_supported_kwargs(method, *args, **kwargs)

    def _record_status_code(self, action: str, response: Any, *, raise_on_error: bool) -> None:
        code = _extract_status_code(response)
        if code is None:
            return
        self.last_status_code.put(int(code))
        if raise_on_error and code != 0:
            raise RuntimeError(f"{self.name}: {action} failed with xArm status code {code}.")

    def _coerce_scalar(self, value: ScalarLike, *, unit: Any, label: str) -> float:
        if isinstance(value, Quantity):
            try:
                magnitude = float(value.to(str(unit)).magnitude)
            except Exception as exc:
                raise ValueError(f"{label} must be compatible with '{unit}'") from exc
        else:
            magnitude = float(value)

        if not math.isfinite(magnitude):
            raise ValueError(f"{label} must be finite.")
        return magnitude

    def _coerce_pose(self, pose: PoseLike, *, length_unit: Any, angle_unit: Any, label: str) -> XArmPose:
        if isinstance(pose, Mapping):
            missing = [field for field in POSE_FIELDS if field not in pose]
            if missing:
                raise ValueError(f"Missing pose fields: {missing}")
            values = tuple(pose[field] for field in POSE_FIELDS)
        elif isinstance(pose, XArmPose):
            values = pose.as_tuple()
        elif isinstance(pose, Sequence) and not isinstance(pose, (str, bytes)):
            if len(pose) != 6:
                raise ValueError(f"Expected 6 pose values, got {len(pose)}")
            values = tuple(pose)
        else:
            raise TypeError("Pose must be XArmPose, a mapping, or a sequence of six numbers/quantities.")

        x = self._coerce_scalar(values[0], unit=length_unit, label=f"{label}.x")
        y = self._coerce_scalar(values[1], unit=length_unit, label=f"{label}.y")
        z = self._coerce_scalar(values[2], unit=length_unit, label=f"{label}.z")
        roll = self._coerce_scalar(values[3], unit=angle_unit, label=f"{label}.roll")
        pitch = self._coerce_scalar(values[4], unit=angle_unit, label=f"{label}.pitch")
        yaw = self._coerce_scalar(values[5], unit=angle_unit, label=f"{label}.yaw")
        return XArmPose(x=x, y=y, z=z, roll=roll, pitch=pitch, yaw=yaw)

    def _convert_units(self, value: float, *, from_unit: Any, to_unit: Any) -> float:
        return float((value * from_unit).to(to_unit).magnitude)

    def _display_to_backend_pose(self, pose: XArmPose) -> XArmPose:
        return XArmPose(
            x=self._convert_units(pose.x, from_unit=self._display_length_unit, to_unit=self._backend_length_unit),
            y=self._convert_units(pose.y, from_unit=self._display_length_unit, to_unit=self._backend_length_unit),
            z=self._convert_units(pose.z, from_unit=self._display_length_unit, to_unit=self._backend_length_unit),
            roll=self._convert_units(pose.roll, from_unit=self._display_angle_unit, to_unit=self._backend_angle_unit),
            pitch=self._convert_units(
                pose.pitch,
                from_unit=self._display_angle_unit,
                to_unit=self._backend_angle_unit,
            ),
            yaw=self._convert_units(pose.yaw, from_unit=self._display_angle_unit, to_unit=self._backend_angle_unit),
        )

    def _backend_to_display_pose(self, pose: XArmPose) -> XArmPose:
        return XArmPose(
            x=self._convert_units(pose.x, from_unit=self._backend_length_unit, to_unit=self._display_length_unit),
            y=self._convert_units(pose.y, from_unit=self._backend_length_unit, to_unit=self._display_length_unit),
            z=self._convert_units(pose.z, from_unit=self._backend_length_unit, to_unit=self._display_length_unit),
            roll=self._convert_units(pose.roll, from_unit=self._backend_angle_unit, to_unit=self._display_angle_unit),
            pitch=self._convert_units(
                pose.pitch,
                from_unit=self._backend_angle_unit,
                to_unit=self._display_angle_unit,
            ),
            yaw=self._convert_units(pose.yaw, from_unit=self._backend_angle_unit, to_unit=self._display_angle_unit),
        )

    @property
    def target(self) -> XArmPose:
        return XArmPose(
            x=float(self.target_x.get()),
            y=float(self.target_y.get()),
            z=float(self.target_z.get()),
            roll=float(self.target_roll.get()),
            pitch=float(self.target_pitch.get()),
            yaw=float(self.target_yaw.get()),
        )

    @property
    def readback_pose(self) -> XArmPose:
        return XArmPose(
            x=float(self.readback_x.get()),
            y=float(self.readback_y.get()),
            z=float(self.readback_z.get()),
            roll=float(self.readback_roll.get()),
            pitch=float(self.readback_pitch.get()),
            yaw=float(self.readback_yaw.get()),
        )

    @property
    def position(self) -> tuple[float, float, float, float, float, float]:
        return self.readback_pose.as_tuple()

    def stage(self) -> list[Any]:
        if not bool(self.connected.get()):
            self.connect()
        return super().stage()

    def unstage(self) -> list[Any]:
        unstaged = super().unstage()
        if self._disconnect_on_unstage:
            self.disconnect()
        return unstaged

    def connect(self) -> None:
        self._call_backend("connect", required=False)
        self._record_status_code(
            "motion_enable",
            self._call_backend("motion_enable", True, required=False),
            raise_on_error=True,
        )
        self._record_status_code("set_mode", self._call_backend("set_mode", 0, required=False), raise_on_error=True)
        self._record_status_code("set_state", self._call_backend("set_state", 0, required=False), raise_on_error=True)
        self.connected.put(1)
        self.refresh_readback()

    def disconnect(self) -> None:
        self._call_backend("disconnect", required=False)
        self.connected.put(0)

    def clear_error(self) -> None:
        self._record_status_code("clean_error", self._call_backend("clean_error", required=False), raise_on_error=True)
        self.resume()

    def pause(self) -> None:
        self.stop(success=False)

    def resume(self) -> None:
        self._stop_requested.clear()
        if not bool(self.connected.get()):
            self.connect()
            return
        self._record_status_code(
            "motion_enable",
            self._call_backend("motion_enable", True, required=False),
            raise_on_error=True,
        )
        self._record_status_code("set_state", self._call_backend("set_state", 0, required=False), raise_on_error=True)

    def trigger(self) -> DeviceStatus:
        status = DeviceStatus(self)
        try:
            self.refresh_readback()
            _safe_set_finished(status)
        except Exception as exc:
            _safe_set_exception(status, exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
        return status

    def refresh_readback(self) -> XArmPose:
        response = self._call_backend("get_position")
        status_code = _extract_status_code(response)
        payload = response
        if isinstance(response, tuple) and len(response) >= 2 and isinstance(response[0], int):
            payload = response[1]

        if status_code is not None:
            self.last_status_code.put(int(status_code))
            if status_code != 0:
                raise RuntimeError(f"{self.name}: get_position failed with xArm status code {status_code}.")

        backend_pose = self._coerce_pose(
            payload,
            length_unit=self._backend_length_unit,
            angle_unit=self._backend_angle_unit,
            label="readback",
        )
        display_pose = self._backend_to_display_pose(backend_pose)
        self._set_readback_pose(display_pose)
        return display_pose

    def locate(self) -> dict[str, tuple[float, float, float, float, float, float]]:
        try:
            self.refresh_readback()
        except Exception:
            # Keep cached readback when online query fails.
            pass
        return {"setpoint": self.target.as_tuple(), "readback": self.readback_pose.as_tuple()}

    def _set_target_pose(self, pose: XArmPose) -> None:
        self.target_x.put(pose.x)
        self.target_y.put(pose.y)
        self.target_z.put(pose.z)
        self.target_roll.put(pose.roll)
        self.target_pitch.put(pose.pitch)
        self.target_yaw.put(pose.yaw)

    def _set_readback_pose(self, pose: XArmPose) -> None:
        self.readback_x.put(pose.x)
        self.readback_y.put(pose.y)
        self.readback_z.put(pose.z)
        self.readback_roll.put(pose.roll)
        self.readback_pitch.put(pose.pitch)
        self.readback_yaw.put(pose.yaw)

    def set_target(
        self,
        pose: PoseLike | None = None,
        *,
        x: ScalarLike | None = None,
        y: ScalarLike | None = None,
        z: ScalarLike | None = None,
        roll: ScalarLike | None = None,
        pitch: ScalarLike | None = None,
        yaw: ScalarLike | None = None,
    ) -> XArmPose:
        if pose is not None:
            if any(value is not None for value in (x, y, z, roll, pitch, yaw)):
                raise ValueError("Provide either 'pose' or individual axis values, not both.")
            parsed_pose = self._coerce_pose(
                pose,
                length_unit=self._display_length_unit,
                angle_unit=self._display_angle_unit,
                label="target",
            )
        else:
            axis_values = (x, y, z, roll, pitch, yaw)
            if any(value is None for value in axis_values):
                raise ValueError("Provide a full pose or all axis values (x, y, z, roll, pitch, yaw).")
            parsed_pose = self._coerce_pose(
                axis_values,
                length_unit=self._display_length_unit,
                angle_unit=self._display_angle_unit,
                label="target",
            )

        self._set_target_pose(parsed_pose)
        return parsed_pose

    def move_to(
        self,
        pose: PoseLike,
        *,
        wait: bool = False,
        timeout: float | None = None,
        speed: ScalarLike | None = None,
        acceleration: ScalarLike | None = None,
    ) -> DeviceStatus:
        target_pose = self.set_target(pose)
        return self._start_move(target_pose, wait=wait, timeout=timeout, speed=speed, acceleration=acceleration)

    def move_to_target(
        self,
        *,
        wait: bool = False,
        timeout: float | None = None,
        speed: ScalarLike | None = None,
        acceleration: ScalarLike | None = None,
    ) -> DeviceStatus:
        return self._start_move(self.target, wait=wait, timeout=timeout, speed=speed, acceleration=acceleration)

    def set(
        self,
        new_position: PoseLike,
        *,
        timeout: float | None = None,
        moved_cb: Callable[..., Any] | None = None,
        wait: bool = False,
        speed: ScalarLike | None = None,
        acceleration: ScalarLike | None = None,
    ) -> DeviceStatus:
        status = self.move_to(
            new_position,
            wait=wait,
            timeout=timeout,
            speed=speed,
            acceleration=acceleration,
        )
        if moved_cb is not None:
            status.add_callback(partial(moved_cb, obj=self))
        return status

    def check_value(self, value: PoseLike) -> None:
        self._coerce_pose(
            value,
            length_unit=self._display_length_unit,
            angle_unit=self._display_angle_unit,
            label="setpoint",
        )

    def _start_move(
        self,
        pose: XArmPose,
        *,
        wait: bool,
        timeout: float | None,
        speed: ScalarLike | None,
        acceleration: ScalarLike | None,
    ) -> DeviceStatus:
        with self._move_lock:
            if self._active_status is not None and not self._active_status.done:
                raise RuntimeError(f"{self.name}: a move is already in progress.")
            self._stop_requested.clear()
            self._set_target_pose(pose)
            status = DeviceStatus(self, timeout=timeout)
            self._active_status = status
            self.moving.put(1)

        command_speed = (
            self._default_speed
            if speed is None
            else self._coerce_scalar(speed, unit=self._display_speed_unit, label="speed")
        )
        command_acceleration = (
            self._default_acceleration
            if acceleration is None
            else self._coerce_scalar(
                acceleration,
                unit=self._display_acceleration_unit,
                label="acceleration",
            )
        )

        worker = threading.Thread(
            target=self._move_worker,
            args=(pose, status, timeout, command_speed, command_acceleration),
            daemon=True,
        )
        worker.start()

        if wait:
            status.wait(timeout=timeout)
        return status

    def _move_worker(
        self,
        display_pose: XArmPose,
        status: DeviceStatus,
        timeout: float | None,
        speed: float | None,
        acceleration: float | None,
    ) -> None:
        backend_pose = self._display_to_backend_pose(display_pose)
        backend_speed = None
        if speed is not None:
            backend_speed = self._convert_units(
                speed,
                from_unit=self._display_speed_unit,
                to_unit=self._backend_speed_unit,
            )
        backend_acceleration = None
        if acceleration is not None:
            backend_acceleration = self._convert_units(
                acceleration,
                from_unit=self._display_acceleration_unit,
                to_unit=self._backend_acceleration_unit,
            )

        try:
            response = self._call_backend(
                "set_position",
                *backend_pose.as_tuple(),
                wait=True,
                timeout=timeout,
                speed=backend_speed,
                mvacc=backend_acceleration,
                is_radian=self._is_radian,
            )
            status_code = _extract_status_code(response)
            if status_code is not None:
                self.last_status_code.put(int(status_code))

            if self._stop_requested.is_set():
                _safe_set_exception(status, RuntimeError(f"{self.name}: motion stopped by user request."))
                return
            if status_code is not None and status_code != 0:
                _safe_set_exception(
                    status,
                    RuntimeError(f"{self.name}: set_position failed with xArm status code {status_code}."),
                )
                return

            try:
                self.refresh_readback()
            except Exception:
                self._set_readback_pose(display_pose)
            else:
                self._set_target_pose(self.readback_pose)
            _safe_set_finished(status)
        except Exception as exc:
            if self._stop_requested.is_set():
                _safe_set_exception(status, RuntimeError(f"{self.name}: motion stopped by user request."))
            else:
                _safe_set_exception(status, exc if isinstance(exc, Exception) else RuntimeError(str(exc)))
        finally:
            self.moving.put(0)
            with self._move_lock:
                if self._active_status is status:
                    self._active_status = None

    def stop(self, *, success: bool = False) -> None:
        with self._move_lock:
            active_status = self._active_status
            if self._stop_requested.is_set() and (active_status is None or active_status.done):
                self.moving.put(0)
                return

        self._stop_requested.set()

        command_error: Exception | None = None
        try:
            response = self._call_backend("set_state", 4, required=False)
            if response is None and getattr(self._arm, "emergency_stop", None) is not None:
                response = self._call_backend("emergency_stop")
            if response is None:
                raise AttributeError("xArm backend does not provide set_state or emergency_stop.")
            self._record_status_code("stop", response, raise_on_error=False)
        except Exception as exc:
            command_error = exc

        with self._move_lock:
            status = self._active_status
        if status is not None and not status.done:
            if success and command_error is None:
                _safe_set_finished(status)
            else:
                _safe_set_exception(status, RuntimeError(f"{self.name}: motion stopped by user request."))

        self.moving.put(0)
        if command_error is not None:
            raise command_error
