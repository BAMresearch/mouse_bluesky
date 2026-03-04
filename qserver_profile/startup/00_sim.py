from __future__ import annotations

from bluesky import plan_stubs as bps
from bluesky.plans import count
from ophyd.sim import det, motor  # safe simulated devices


def sim_count(num: int = 5, delay: float = 0.0):
    """Count a simulated detector."""
    yield from count([det], num=num, delay=delay)


def sim_move_and_count(pos: float = 1.0, num: int = 1):
    """Move a simulated motor and count a simulated detector."""
    yield from bps.mv(motor, float(pos))
    yield from count([det], num=int(num))


def sim_sleep(seconds: float = 1.0):
    """Sleep in a plan (useful for queue testing)."""
    yield from bps.sleep(float(seconds))