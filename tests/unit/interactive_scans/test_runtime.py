from __future__ import annotations

import pytest

from mouse_bluesky.interactive_scans.runtime import coerce_uid, resolve_detector_field


class DummyDetector:
    def __init__(self, name: str) -> None:
        self.name = name


def test_coerce_uid_from_singleton_tuple() -> None:
    assert coerce_uid(("abc",)) == "abc"


def test_resolve_detector_field_uses_single_detector_name() -> None:
    det = DummyDetector("eiger")
    assert resolve_detector_field([det], None) == "eiger"


def test_resolve_detector_field_requires_name_for_multiple_detectors() -> None:
    with pytest.raises(ValueError):
        resolve_detector_field([DummyDetector("a"), DummyDetector("b")], None)
