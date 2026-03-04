from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from enum import Enum
from typing import Any

import attrs


class CollatePolicy(str, Enum):
    """Per-entry collation policy.

    - FORBID: barrier; keep order, no reordering across this entry.
    - ALLOW: collate within its contiguous ALLOW block.
    """
    FORBID = "FORBID"
    ALLOW = "ALLOW"


@attrs.frozen(slots=True)
class PlanSpec:
    """Reference to a Bluesky plan.

    - Interactive: resolve name->callable, call it to obtain a generator.
    - Queue Server: convert to QS plan item payload via to_qs_item().
    """
    name: str
    kwargs: Mapping[str, Any] = attrs.field(factory=dict, converter=dict)
    meta: Mapping[str, Any] = attrs.field(factory=dict, converter=dict)

    def to_qs_item(self) -> dict[str, Any]:
        """Convert this spec into a Queue Server item payload."""
        return {"item_type": "plan", "name": self.name, "args": [], "kwargs": dict(self.kwargs)}


@attrs.frozen(slots=True)
class CompiledEntry:
    """Result of compiling one logbook entry."""
    collate: CollatePolicy
    specs: tuple[PlanSpec, ...]


PlanFn = Callable[..., Iterator]
PlanFnRegistry = Mapping[str, PlanFn]
