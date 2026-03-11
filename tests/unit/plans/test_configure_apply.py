from pathlib import Path
from types import SimpleNamespace

from bluesky import RunEngine
from bluesky_queueserver.manager.profile_tools import global_user_namespace
from ophyd.sim import SynAxis

from mouse_bluesky.plans.configure import apply_config


def _namespace_with_axes() -> dict[str, object]:
    return {
        "det_stage": SimpleNamespace(x=SynAxis(name="detx"), y=SynAxis(name="dety"), z=SynAxis(name="detz")),
        "beam_stop": SimpleNamespace(bsr=SynAxis(name="bsr"), bsz=SynAxis(name="bsz")),
        "dual": SimpleNamespace(dual=SynAxis(name="dual")),
        "s1": SimpleNamespace(
            top=SynAxis(name="s1top"),
            bot=SynAxis(name="s1bot"),
            left=SynAxis(name="s1hl"),
            right=SynAxis(name="s1hr"),
        ),
        "s2": SimpleNamespace(
            top=SynAxis(name="s2top"),
            bot=SynAxis(name="s2bot"),
            left=SynAxis(name="s2hl"),
            right=SynAxis(name="s2hr"),
        ),
        "s3": SimpleNamespace(
            top=SynAxis(name="s3top"),
            bot=SynAxis(name="s3bot"),
            left=SynAxis(name="s3hl"),
            right=SynAxis(name="s3hr"),
        ),
        "sample_stage_yz": SimpleNamespace(y=SynAxis(name="ysam"), z=SynAxis(name="zsam")),
    }


def test_apply_config_does_not_move_sample_stage_yz():
    namespace = _namespace_with_axes()
    RE = RunEngine({})
    config_root = Path("tests/data/mouse_configs").as_posix()

    y_before = namespace["sample_stage_yz"].y.position
    z_before = namespace["sample_stage_yz"].z.position

    RE(apply_config(config_id=123, config_root=config_root, namespace=namespace))

    assert namespace["sample_stage_yz"].y.position == y_before
    assert namespace["sample_stage_yz"].z.position == z_before


def test_apply_config_uses_qserver_user_namespace_when_namespace_is_none():
    namespace = _namespace_with_axes()
    RE = RunEngine({})
    config_root = Path("tests/data/mouse_configs").as_posix()

    original_user_ns = dict(global_user_namespace.user_ns)
    try:
        global_user_namespace.set_user_namespace(user_ns=namespace, use_ipython=False)
        RE(apply_config(config_id=123, config_root=config_root))
    finally:
        global_user_namespace.set_user_namespace(user_ns=original_user_ns, use_ipython=False)
