from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

import attrs

from ..planner.models import CompiledEntry


class LogbookEntryLike(Protocol):
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
    name: str
    compile: CompilerFn


class ProtocolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ProtocolSpec] = {}

    def register(self, spec: ProtocolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate protocol name: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ProtocolSpec:
        try:
            return self._specs[name]
        except KeyError as e:
            raise ValueError(f"Unknown protocol {name!r}. Known: {sorted(self._specs)}") from e

    def known(self) -> list[str]:
        return sorted(self._specs)
