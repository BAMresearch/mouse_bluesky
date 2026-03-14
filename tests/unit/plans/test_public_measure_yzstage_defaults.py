from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mouse_bluesky.plans.public import UNRESOLVED_YMD_SENTINEL, measure_yzstage


def _namespace(*, include_cu: bool = True, include_mo: bool = True) -> dict[str, object]:
    ns: dict[str, object] = {
        "eiger": object(),
        "sample_stage_yz": object(),
        "beam_stop": object(),
    }
    if include_cu:
        ns["cu_generator"] = SimpleNamespace(shutter=object())
    if include_mo:
        ns["mo_generator"] = SimpleNamespace(shutter=object())
    return ns


def test_measure_yzstage_interactive_defaults_resolve_from_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    ns = _namespace(include_cu=True, include_mo=False)

    plan = measure_yzstage(namespace=ns)
    msg = next(plan)
    plan.close()

    assert msg.command == "open_run"
    assert msg.kwargs["proposal"] == "2026001"
    assert msg.kwargs["sampleid"] == 1
    assert msg.kwargs["sampos"] == ""
    assert msg.kwargs["config_id"] == 123
    assert msg.kwargs["ymd"] == UNRESOLVED_YMD_SENTINEL
    assert str(msg.kwargs["destination"]).startswith(tmp_path.as_posix())


def test_measure_yzstage_none_ymd_uses_safe_sentinel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    plan = measure_yzstage(namespace=_namespace(include_cu=True, include_mo=False), ymd=None)
    msg = next(plan)
    plan.close()

    assert msg.kwargs["ymd"] == UNRESOLVED_YMD_SENTINEL


def test_measure_yzstage_legacy_generator_selection_uses_even_config_for_mo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    plan = measure_yzstage(namespace=_namespace(include_cu=False, include_mo=True), config_id=266)
    msg = next(plan)
    plan.close()

    assert msg.command == "open_run"
    assert msg.kwargs["config_id"] == 266


def test_measure_yzstage_raises_on_missing_legacy_default_generator() -> None:
    ns = _namespace(include_cu=False, include_mo=True)
    with pytest.raises(ValueError, match="cu_generator"):
        plan = measure_yzstage(namespace=ns, root_path="tests/data/mouse")
        next(plan)
