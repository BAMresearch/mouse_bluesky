from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bluesky_queueserver.manager.profile_tools import global_user_namespace

from mouse_bluesky.plans.public import measure_yzstage


def test_measure_yzstage_resolves_devices_from_qserver_namespace(tmp_path: Path) -> None:
    user_ns = {
        "eiger": object(),
        "sample_stage_yz": object(),
        "beam_stop": object(),
        "cu_generator": SimpleNamespace(shutter=object()),
        "mo_generator": SimpleNamespace(shutter=object()),
    }
    original_user_ns = dict(global_user_namespace.user_ns)
    try:
        global_user_namespace.set_user_namespace(user_ns=user_ns, use_ipython=False)
        plan = measure_yzstage(root_path=tmp_path.as_posix(), ymd="20260312", batchnum=1, config_id=166)
        msg = next(plan)
        plan.close()
    finally:
        global_user_namespace.set_user_namespace(user_ns=original_user_ns, use_ipython=False)

    assert msg.command == "open_run"
