from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

import attrs

from ..planner.models import CompiledEntry


class LogbookEntryLike(Protocol):
    """Structural contract expected by protocol compilers."""
    row_index: int
    proposal: str
    sampleid: int
    sampos: str
    protocol: str
    additional_parameters: Mapping[str, str]
    batchnum: int
    positions: Mapping[str, float]
    ymd: str


CompilerFn = Callable[[LogbookEntryLike, Mapping[str, Any]], CompiledEntry]


@attrs.frozen(slots=True)
class ProtocolSpec:
    """Describes one named protocol compiler."""
    name: str
    compile: CompilerFn


class ProtocolRegistry:
    """Stores protocol compilers and resolves them by protocol name."""

    def __init__(self) -> None:
        """Initialize an empty protocol registry."""
        self._specs: dict[str, ProtocolSpec] = {}

    def register(self, spec: ProtocolSpec) -> None:
        """Register one protocol compiler by unique name."""
        if spec.name in self._specs:
            raise ValueError(f"Duplicate protocol name: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ProtocolSpec:
        """Return a registered protocol compiler, or raise for unknown names."""
        try:
            return self._specs[name]
        except KeyError as e:
            raise ValueError(f"Unknown protocol {name!r}. Known: {sorted(self._specs)}") from e

    def known(self) -> list[str]:
        """List known protocol names in stable sorted order."""
        return sorted(self._specs)
