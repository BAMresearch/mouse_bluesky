from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import Mapping

from bluesky import plan_stubs as bps
from bluesky import preprocessors as bpp
from bluesky.utils import RunEngineControlException

from .public import _resolve_optional_device
from .shutter import SHUTTER_CLOSE_TIMEOUT_S, close_shutter_best_effort

DETECTOR_PARK_POSITION = 400
EVACUATE_TARGET_PRESSURE = 1
VENTILATE_TARGET_PRESSURE = 900
EVACUATE_TIMEOUT_S = 1800.0
VENTILATE_TIMEOUT_S = 600.0
EVACUATE_POLL_INTERVAL_S = 3.0
VENTILATE_POLL_INTERVAL_S = 1.0
VENTILATE_PUMP_OFF_DELAY_S = 1.0
VENTILATE_HOLD_S = 10.0
SIGNAL_SET_TIMEOUT_S = 30
OUTPUT_OFF = 0
OUTPUT_ON = 1


def _read_pressure(signal) -> Iterator:
    pressure = yield from bps.rd(signal)
    if not math.isfinite(pressure):
        raise ValueError(f"Non-finite pressure from {signal.name}: {pressure}")
    return pressure


def _preflight(namespace):
    det_stage = _resolve_optional_device(None, name="det_stage", namespace=namespace)
    arduino = _resolve_optional_device(None, name="arduino", namespace=namespace)
    pressure_gauge = _resolve_optional_device(None, name="pressure_gauge", namespace=namespace)
    generators = []
    for name in ("cu_generator", "mo_generator"):
        try:
            generator = _resolve_optional_device(None, name=name, namespace=namespace)
        except ValueError as exc:
            print(f"Warning: {exc}")
        else:
            generators.append((name, generator))

    detx = det_stage.x
    pressure = pressure_gauge.pressure
    do6 = arduino.digital_output_6
    do7 = arduino.digital_output_7
    yield from bps.rd(detx)
    yield from _read_pressure(pressure)
    yield from bps.rd(do6)
    yield from bps.rd(do7)
    return detx, pressure, do6, do7, generators


def _close_shutter(generator, name):
    try:
        shutter = generator.shutter
        yield from close_shutter_best_effort(shutter, name, timeout_s=SHUTTER_CLOSE_TIMEOUT_S)
    except RunEngineControlException:
        raise
    except Exception as exc:
        print(f"Warning: could not confirm {name} shutter closed: {exc}")


def _start(detx, generators):
    yield from bps.clear_checkpoint()
    for name, generator in generators:
        yield from _close_shutter(generator, name)
    yield from bps.mv(detx, DETECTOR_PARK_POSITION)


def _set_valve(signal, value):
    # The output PV stores the last command, not a trustworthy valve readback.
    # Always send the command, even when its cached value already matches.
    yield from bps.abs_set(signal, value, wait=True, timeout=SIGNAL_SET_TIMEOUT_S)


def _wait_for_pressure(signal, *, target, evacuating, timeout_s, poll_interval_s):
    deadline = time.monotonic() + timeout_s
    while True:
        pressure = yield from _read_pressure(signal)
        print("current pressure:", pressure)
        target_reached = pressure <= target if evacuating else pressure >= target
        if target_reached:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Pressure timeout after {timeout_s} s: last pressure {pressure}, target {target}")
        yield from bps.sleep(min(poll_interval_s, remaining))


def evacuate(*, timeout_s: float = EVACUATE_TIMEOUT_S, namespace: Mapping[str, object] | None = None) -> Iterator:
    """Evacuate the chamber, leaving the pump on even if the plan fails."""
    detx, pressure, do6, do7, generators = yield from _preflight(namespace)

    def body():
        yield from _start(detx, generators)
        yield from _set_valve(do7, OUTPUT_OFF)
        yield from _set_valve(do6, OUTPUT_ON)
        yield from _wait_for_pressure(
            pressure,
            target=EVACUATE_TARGET_PRESSURE,
            evacuating=True,
            timeout_s=timeout_s,
            poll_interval_s=EVACUATE_POLL_INTERVAL_S,
        )

    yield from bpp.run_wrapper(
        body(), md={"activity": "evacuate", "target_pressure": EVACUATE_TARGET_PRESSURE, "timeout_s": timeout_s}
    )


def ventilate(*, timeout_s: float = VENTILATE_TIMEOUT_S, namespace: Mapping[str, object] | None = None) -> Iterator:
    """Ventilate the chamber, closing the vent output when the valve sequence ends."""
    detx, pressure, do6, do7, generators = yield from _preflight(namespace)

    def valves():
        yield from _set_valve(do6, OUTPUT_OFF)
        yield from bps.sleep(VENTILATE_PUMP_OFF_DELAY_S)
        yield from _set_valve(do7, OUTPUT_ON)
        yield from _wait_for_pressure(
            pressure,
            target=VENTILATE_TARGET_PRESSURE,
            evacuating=False,
            timeout_s=timeout_s,
            poll_interval_s=VENTILATE_POLL_INTERVAL_S,
        )
        yield from bps.sleep(VENTILATE_HOLD_S)
        final_pressure = yield from _read_pressure(pressure)
        print("current pressure:", final_pressure)

    def body():
        yield from _start(detx, generators)
        # Install cleanup before the first valve command. An interruption of
        # the courtesy shutter close above must not start a valve sequence.
        yield from bpp.finalize_wrapper(valves(), _set_valve(do7, OUTPUT_OFF))

    yield from bpp.run_wrapper(
        body(), md={"activity": "ventilate", "target_pressure": VENTILATE_TARGET_PRESSURE, "timeout_s": timeout_s}
    )
