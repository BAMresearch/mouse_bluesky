from __future__ import annotations

from pathlib import Path

import pytest

from mouse_bluesky.plans.public import measure_yzstage


def test_measure_yzstage_interactive_defaults_resolve_from_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOUSE_DATA_ROOT", tmp_path.as_posix())

    ns = {
        "eiger": object(),
        "sample_stage_yz": object(),
        "beam_stop": object(),
        "shutter": object(),
    }

    plan = measure_yzstage(namespace=ns)
    msg = next(plan)
    plan.close()

    assert msg.command == "open_run"
    assert msg.kwargs["proposal"] == "interactive"
    assert msg.kwargs["sampleid"] == 0
    assert msg.kwargs["sampos"] == "interactive"
    assert msg.kwargs["config_id"] == -1
    assert str(msg.kwargs["destination"]).startswith(tmp_path.as_posix())


def test_measure_yzstage_raises_on_missing_default_device() -> None:
    ns = {
        "eiger": object(),
        "sample_stage_yz": object(),
        "beam_stop": object(),
    }
    with pytest.raises(ValueError, match="shutter"):
        plan = measure_yzstage(namespace=ns, root_path="tests/data/mouse")
        next(plan)
