from __future__ import annotations

from typing import Mapping

import attrs
import pytest

from mouse_bluesky.planner.models import CollatePolicy
from mouse_bluesky.protocols.builtin import compile_standard_measurements


@attrs.frozen(slots=True)
class FakeEntry:
    row_index: int
    proposal: str
    sampleid: int
    sampos: str
    protocol: str
    additional_parameters: Mapping[str, str]
    batchnum: int = 1
    positions: Mapping[str, float] = attrs.field(factory=dict)

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


def test_sample_exposure_time_is_forwarded_to_measurement_kwargs() -> None:
    e = FakeEntry(1, "2025002", 13, "Cu C14", "standard_measurements", {})
    res = compile_standard_measurements(
        e,
        {"configs": [101, 102], "repeats": 1, "sample_exposure_time": 42.5, "collate": CollatePolicy.ALLOW},
    )
    assert all(float(s.kwargs["sample_exposure_time"]) == 42.5 for s in res.specs)


def test_sample_exposure_time_list_matches_configs() -> None:
    e = FakeEntry(1, "2025002", 13, "Cu C14", "standard_measurements", {})
    res = compile_standard_measurements(
        e,
        {"configs": [101, 102], "repeats": 1, "sample_exposure_time": [11, 22], "collate": CollatePolicy.ALLOW},
    )
    by_cfg = {int(s.kwargs["config_id"]): float(s.kwargs["sample_exposure_time"]) for s in res.specs}
    assert by_cfg == {101: 11.0, 102: 22.0}


def test_sample_exposure_time_list_length_mismatch_raises() -> None:
    e = FakeEntry(1, "2025002", 13, "Cu C14", "standard_measurements", {})
    with pytest.raises(ValueError, match="sample_exposure_time"):
        compile_standard_measurements(
            e,
            {"configs": [101, 102], "repeats": 1, "sample_exposure_time": [11], "collate": CollatePolicy.ALLOW},
        )
