from __future__ import annotations

import json
from pathlib import Path

import h5py

from mouse_bluesky.plans.im_craw import write_im_craw_nxs
from mouse_bluesky.plans.public import measure_yzstage
from tests.unit.plans.support import build_startup_namespace


def _scalar(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "item"):
        return value.item()
    return value


def test_write_im_craw_nxs_writes_metadata_and_state(tmp_path: Path) -> None:
    ns = build_startup_namespace(include_yz=True, include_generators=True, include_sensors=True)
    run_md = {
        "entry_row_index": 3,
        "proposal": "2026001",
        "sampleid": 12,
        "sampos": "Cu C14",
        "ymd": "20260311",
        "batchnum": 5,
        "config_id": 161,
        "repeat_index": 0,
        "sample_exposure_time": 60.0,
    }

    out = write_im_craw_nxs(
        destination=tmp_path / "scan_0001",
        run_md=run_md,
        namespace=ns,
        xray_generator=ns["cu_generator"],
    )

    assert out.name == "im_craw.nxs"
    assert out.exists()
    with h5py.File(out, "r") as f:
        assert _scalar(f["/entry1/experiment/proposal"][()]) == "2026001"
        assert _scalar(f["/entry1/sample/sampleid"][()]) == 12
        assert _scalar(f["/entry1/instrument/configuration"][()]) == 161
        assert _scalar(f["/entry1/instrument/source/name"][()]) == "cu_generator"
        assert float(_scalar(f["/entry1/instrument/source/voltage"][()])) == 45.0
        assert float(_scalar(f["/saxs/Saxslab/chamber_pressure"][()])) == 1.2
        assert float(_scalar(f["/entry1/experiment/environment_temperature"][()])) == 22.3
        assert float(_scalar(f["/entry1/experiment/stage_temperature"][()])) == 26.7
        assert float(_scalar(f["/saxs/Saxslab/detx"][()])) == float(ns["det_stage"].x.position)
        assert float(_scalar(f["/saxs/Saxslab/ysam"][()])) == float(ns["sample_stage_yz"].y.position)
        logbook_json = _scalar(f["/entry1/experiment/logbook_json"][()])
        parsed = json.loads(logbook_json)
        assert parsed["sampos"] == "Cu C14"


def test_measure_yzstage_writes_im_craw_next_to_detector_data(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ns = build_startup_namespace(include_yz=True, include_generators=True, include_sensors=True, include_eiger=True)
    destination = tmp_path / "20260311" / "batch005" / "007"

    def fake_allocate_sequence_dir(*, root: Path, ymd: str, batchnum: int) -> tuple[int, Path]:
        assert root == tmp_path
        assert ymd == "20260311"
        assert batchnum == 5
        return 7, destination

    def fake_mouse_eiger_measure(*args, **kwargs):
        if False:
            yield args, kwargs

    monkeypatch.setattr("mouse_bluesky.plans.public.allocate_sequence_dir", fake_allocate_sequence_dir)
    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", fake_mouse_eiger_measure)

    plan = measure_yzstage(
        entry_row_index=9,
        proposal="2026001",
        sampleid=44,
        sampos="sample-A",
        ymd="20260311",
        batchnum=5,
        config_id=161,
        repeat_index=2,
        root_path=tmp_path.as_posix(),
        namespace=ns,
        sampleposition={"ysam": 1.2, "zsam": -0.4},
        sample_exposure_time=33.0,
    )
    list(plan)

    sample_out = destination / "im_craw.nxs"
    beam_profile_out = destination / "beam_profile" / "im_craw.nxs"
    beam_profile_through_sample_out = destination / "beam_profile_through_sample" / "im_craw.nxs"

    assert sample_out.exists()
    assert beam_profile_out.exists()
    assert beam_profile_through_sample_out.exists()

    with h5py.File(sample_out, "r") as f:
        assert _scalar(f["/entry1/experiment/entry_row_index"][()]) == 9
        assert _scalar(f["/entry1/experiment/repeat_index"][()]) == 2
        assert _scalar(f["/entry1/instrument/configuration"][()]) == 161
        assert float(_scalar(f["/entry1/instrument/detector00/count_time"][()])) == 33.0

    with h5py.File(beam_profile_out, "r") as f:
        assert float(_scalar(f["/entry1/instrument/detector00/count_time"][()])) == 20.0

    with h5py.File(beam_profile_through_sample_out, "r") as f:
        assert float(_scalar(f["/entry1/instrument/detector00/count_time"][()])) == 20.0
