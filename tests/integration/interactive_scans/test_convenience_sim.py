from __future__ import annotations

import json
from pathlib import Path

from mouse_bluesky.interactive import convenience

from .test_scans_sim import make_peak_bundle


def test_ct_returns_single_detector_count() -> None:
    sim = make_peak_bundle()
    counts = convenience.ct(seconds=0.0, RE=sim.RE, dets=[sim.detector])
    assert isinstance(counts, float)


def test_test_measure_writes_temp_json() -> None:
    sim = make_peak_bundle()
    result = convenience.test_measure(seconds=0.0, RE=sim.RE, dets=[sim.detector], visualize=False)

    assert "uid" in result
    assert isinstance(result["counts"], float)

    data_path = Path(result["data_path"])
    assert data_path.exists()

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert payload["uid"] == result["uid"]
    assert payload["counts"] == result["counts"]
    assert result["plot_path"] is None
