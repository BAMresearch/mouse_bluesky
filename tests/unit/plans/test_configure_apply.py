from pathlib import Path

import pytest
from bluesky import RunEngine
from bluesky_queueserver.manager.profile_tools import global_user_namespace

from mouse_bluesky.plans.configure import apply_config
from tests.unit.plans.support import build_startup_namespace


def test_apply_config_does_not_move_sample_stage_yz():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = Path("tests/data/mouse_configs").as_posix()

    y_before = namespace["sample_stage_yz"].y.position
    z_before = namespace["sample_stage_yz"].z.position

    RE(apply_config(config_id=123, config_root=config_root, namespace=namespace))

    assert namespace["sample_stage_yz"].y.position == y_before
    assert namespace["sample_stage_yz"].z.position == z_before


def test_apply_config_uses_qserver_user_namespace_when_namespace_is_none():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = Path("tests/data/mouse_configs").as_posix()

    original_user_ns = dict(global_user_namespace.user_ns)
    try:
        global_user_namespace.set_user_namespace(user_ns=namespace, use_ipython=False)
        RE(apply_config(config_id=123, config_root=config_root))
    finally:
        global_user_namespace.set_user_namespace(user_ns=original_user_ns, use_ipython=False)


def test_apply_config_emits_start_and_stop_documents():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = Path("tests/data/mouse_configs").as_posix()
    docs: list[tuple[str, dict]] = []

    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE(apply_config(config_id=123, config_root=config_root, namespace=namespace))

    assert [name for name, _ in docs] == ["start", "stop"]
    start_doc = docs[0][1]
    stop_doc = docs[1][1]
    assert start_doc["config_id"] == 123
    assert start_doc["activity"] == "apply_config"
    assert start_doc["config_file"].endswith("/123.nxs")
    assert stop_doc["exit_status"] == "success"


def test_apply_config_emits_failed_run_documents_when_config_is_missing(tmp_path: Path):
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    docs: list[tuple[str, dict]] = []

    RE.subscribe(lambda name, doc: docs.append((name, doc)))

    with pytest.raises(FileNotFoundError):
        RE(apply_config(config_id=999, config_root=tmp_path.as_posix(), namespace=namespace))

    assert [name for name, _ in docs] == ["start", "stop"]
    start_doc = docs[0][1]
    stop_doc = docs[1][1]
    assert start_doc["config_id"] == 999
    assert stop_doc["exit_status"] == "fail"
    assert "Config file not found" in stop_doc["reason"]
