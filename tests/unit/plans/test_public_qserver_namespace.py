from __future__ import annotations

from pathlib import Path

from bluesky import RunEngine
from bluesky_queueserver.manager.profile_tools import global_user_namespace

from mouse_bluesky.plans.public import measure_yzstage
from tests.unit.plans.support import build_startup_namespace


def test_measure_yzstage_resolves_devices_from_qserver_namespace(tmp_path: Path, monkeypatch) -> None:
    user_ns = build_startup_namespace(include_eiger=True)

    def no_acquisition(*args, **kwargs):
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    original_user_ns = dict(global_user_namespace.user_ns)
    try:
        global_user_namespace.set_user_namespace(user_ns=user_ns, use_ipython=False)
        plan = measure_yzstage(root_path=tmp_path.as_posix(), ymd="20260312", batchnum=1, config_id=166)
        RE(plan)
    finally:
        global_user_namespace.set_user_namespace(user_ns=original_user_ns, use_ipython=False)

    assert docs[0][0] == "start"
