from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import pytest

from mouse_bluesky.planner.models import CollatePolicy
from mouse_bluesky.protocols.builtin import compile_standard_measurements


@dataclass(frozen=True, slots=True)
class FakeEntry:
    row_index: int
    proposal: str
    sampleid: int
    sampos: str
    protocol: str
    additional_parameters: Mapping[str, str]
    batchnum: int = 1
    positions: Mapping[str, float] = field(default_factory=dict)

    @property
    def ymd(self) -> str:
        return "20251221"


def test_repeats_list_matches_configs() -> None:
    e = FakeEntry(1, "2025002", 13, "Cu C14", "standard_measurements", {})
    res = compile_standard_measurements(
        e,
        {"configs": [101, 102, 103], "repeats": [1, 3, 7], "collate": CollatePolicy.ALLOW},
    )
    cfgs = [s.meta["config_id"] for s in res.specs]
    assert cfgs.count(101) == 1
    assert cfgs.count(102) == 3
    assert cfgs.count(103) == 7


def test_repeats_list_length_mismatch_raises() -> None:
    e = FakeEntry(1, "2025002", 13, "Cu C14", "standard_measurements", {})
    with pytest.raises(ValueError):
        compile_standard_measurements(e, {"configs": [101, 102], "repeats": [1, 2, 3], "collate": CollatePolicy.ALLOW})
