from bluesky import plan_stubs as bps
from bluesky.utils import RunEngineControlException

SHUTTER_CLOSE_TIMEOUT_S = 5


def close_shutter_best_effort(shutter, name, *, timeout_s=SHUTTER_CLOSE_TIMEOUT_S):
    """Attempt a timed shutter close without hiding RunEngine interruptions."""
    try:
        yield from bps.abs_set(shutter, 0, wait=True, timeout=timeout_s)
    except RunEngineControlException:
        raise
    except Exception as exc:
        print(f"Warning: could not confirm {name} shutter closed: {exc}")
