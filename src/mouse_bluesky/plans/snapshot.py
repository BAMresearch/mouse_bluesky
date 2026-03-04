from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from bluesky import plan_stubs as bps


def snapshot_state(signals: Iterable[Any], *, stream_name: str = "snapshot") -> Iterator:
    """Read selected signals into a dedicated stream inside the active run."""
    yield from bps.create(stream_name)
    for signal in signals:
        yield from bps.read(signal)
    yield from bps.save()
