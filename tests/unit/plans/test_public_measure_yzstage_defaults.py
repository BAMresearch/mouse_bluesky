from __future__ import annotations

from pathlib import Path

import pytest
from bluesky import RunEngine

from mouse_bluesky.plans.public import UNRESOLVED_YMD_SENTINEL, measure_yzstage
from tests.unit.plans.support import build_startup_namespace


def _namespace(*, include_cu: bool = True, include_mo: bool = True) -> dict[str, object]:
    ns = build_startup_namespace(include_eiger=True)
    if not include_cu:
        del ns["cu_generator"]
    if not include_mo:
        del ns["mo_generator"]
    return ns


@pytest.fixture(autouse=True)
def simulated_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_acquisition(*args, **kwargs):
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)


def _run_start_doc(plan) -> dict:
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE(plan)
    assert docs[0][0] == "start"
    return docs[0][1]


def test_measure_yzstage_interactive_defaults_resolve_from_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    ns = _namespace(include_cu=True, include_mo=False)

    plan = measure_yzstage(namespace=ns)
    start = _run_start_doc(plan)

    assert start["proposal"] == "2026001"
    assert start["sampleid"] == 1
    assert start["sampos"] == ""
    assert start["config_id"] == 123
    assert start["ymd"] == UNRESOLVED_YMD_SENTINEL
    assert str(start["destination"]).startswith(tmp_path.as_posix())


def test_measure_yzstage_none_ymd_uses_safe_sentinel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    plan = measure_yzstage(namespace=_namespace(include_cu=True, include_mo=False), ymd=None)
    start = _run_start_doc(plan)

    assert start["ymd"] == UNRESOLVED_YMD_SENTINEL


def test_measure_yzstage_legacy_generator_selection_uses_even_config_for_mo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    plan = measure_yzstage(namespace=_namespace(include_cu=False, include_mo=True), config_id=266)
    start = _run_start_doc(plan)

    assert start["config_id"] == 266


def test_measure_yzstage_raises_on_missing_legacy_default_generator() -> None:
    ns = _namespace(include_cu=False, include_mo=True)
    with pytest.raises(ValueError, match="cu_generator"):
        plan = measure_yzstage(namespace=ns, root_path="tests/data/mouse")
        RunEngine({})(plan)
