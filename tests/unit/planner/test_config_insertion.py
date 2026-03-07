from mouse_bluesky.planner.config_insertion import insert_apply_config_on_change
from mouse_bluesky.planner.models import PlanSpec


def test_insert_apply_config_only_on_change_meta() -> None:
    specs = [
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 102}, meta={"config_id": 102}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 102}, meta={"config_id": 102}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
    ]
    out = insert_apply_config_on_change(specs)

    # Expect apply_config inserted before first 101, before first 102, before last 101 (since it changes back)
    names = [s.name for s in out]
    assert names == [
        "apply_config",
        "measure_yzstage",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
    ]
    assert out[0].kwargs["config_id"] == 101
    assert out[3].kwargs["config_id"] == 102
    assert out[6].kwargs["config_id"] == 101


def test_insert_apply_config_fallback_to_kwargs_when_meta_missing() -> None:
    specs = [
        PlanSpec("measure_yzstage", kwargs={"config_id": 7}, meta={}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 7}, meta={}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 8}, meta={}),
    ]
    out = insert_apply_config_on_change(specs)
    assert [s.name for s in out] == ["apply_config", "measure_yzstage", "measure_yzstage", "apply_config", "measure_yzstage"]
    assert out[0].kwargs["config_id"] == 7
    assert out[3].kwargs["config_id"] == 8
