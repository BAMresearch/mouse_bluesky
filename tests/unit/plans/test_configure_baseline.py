from mouse_bluesky.plans.configure import build_baseline_signals
from tests.unit.plans.support import build_startup_namespace


def test_build_baseline_signals_includes_base_optional_stages_and_generators():
    ns = build_startup_namespace(include_yz=True, include_gi=True, include_generators=True, include_sensors=True)

    baseline = build_baseline_signals(namespace=ns)

    assert baseline == [
        ns["det_stage"].x,
        ns["det_stage"].y,
        ns["det_stage"].z,
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
        ns["pressure_gauge"].pressure,
        ns["arduino"].temperature_env,
        ns["arduino"].temperature_stage,
    ]


def test_build_baseline_signals_skips_missing_optional_devices():
    ns = build_startup_namespace(include_yz=False, include_gi=False, include_generators=False, include_sensors=False)

    baseline = build_baseline_signals(namespace=ns)

    assert baseline == [
        ns["det_stage"].x,
        ns["det_stage"].y,
        ns["det_stage"].z,
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
