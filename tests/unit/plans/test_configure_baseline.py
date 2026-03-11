from types import SimpleNamespace

from mouse_bluesky.plans.configure import build_baseline_signals


def _base_namespace(*, include_yz: bool = True, include_gi: bool = False, include_generators: bool = True):
    ns = {
        "eiger": SimpleNamespace(cam=SimpleNamespace(x=object(), y=object(), z=object())),
        "beam_stop": SimpleNamespace(bsr=object(), bsz=object()),
        "dual": SimpleNamespace(dual=object()),
        "s1": SimpleNamespace(top=object(), bot=object(), left=object(), right=object()),
        "s2": SimpleNamespace(top=object(), bot=object(), left=object(), right=object()),
        "s3": SimpleNamespace(top=object(), bot=object(), left=object(), right=object()),
    }
    if include_yz:
        ns["sample_stage_yz"] = SimpleNamespace(y=object(), z=object())
    if include_gi:
        ns["sample_stage_gi"] = SimpleNamespace(x=object(), y=object())
    if include_generators:
        ns["cu_generator"] = SimpleNamespace(voltage=object(), current=object())
        ns["mo_generator"] = SimpleNamespace(voltage=object(), current=object())
    return ns


def test_build_baseline_signals_includes_base_optional_stages_and_generators():
    ns = _base_namespace(include_yz=True, include_gi=True, include_generators=True)

    baseline = build_baseline_signals(namespace=ns)

    assert baseline == [
        ns["eiger"].cam.x,
        ns["eiger"].cam.y,
        ns["eiger"].cam.z,
        ns["beam_stop"].bsr,
        ns["beam_stop"].bsz,
        ns["dual"].dual,
        ns["s1"].bot,
        ns["s1"].top,
        ns["s1"].left,
        ns["s1"].right,
        ns["s2"].bot,
        ns["s2"].top,
        ns["s2"].left,
        ns["s2"].right,
        ns["s3"].bot,
        ns["s3"].top,
        ns["s3"].left,
        ns["s3"].right,
        ns["sample_stage_yz"].y,
        ns["sample_stage_yz"].z,
        ns["sample_stage_gi"].x,
        ns["sample_stage_gi"].y,
        ns["cu_generator"].voltage,
        ns["cu_generator"].current,
        ns["mo_generator"].voltage,
        ns["mo_generator"].current,
    ]


def test_build_baseline_signals_skips_missing_optional_devices():
    ns = _base_namespace(include_yz=False, include_gi=False, include_generators=False)

    baseline = build_baseline_signals(namespace=ns)

    assert baseline == [
        ns["eiger"].cam.x,
        ns["eiger"].cam.y,
        ns["eiger"].cam.z,
        ns["beam_stop"].bsr,
        ns["beam_stop"].bsz,
        ns["dual"].dual,
        ns["s1"].bot,
        ns["s1"].top,
        ns["s1"].left,
        ns["s1"].right,
        ns["s2"].bot,
        ns["s2"].top,
        ns["s2"].left,
        ns["s2"].right,
        ns["s3"].bot,
        ns["s3"].top,
        ns["s3"].left,
        ns["s3"].right,
    ]

