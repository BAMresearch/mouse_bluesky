from mouse_bluesky.planner.config_insertion import insert_apply_config_before_measurements
from mouse_bluesky.planner.models import PlanSpec


def test_insert_apply_config_before_every_measurement_meta() -> None:
    specs = [
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 102}, meta={"config_id": 102}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 102}, meta={"config_id": 102}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 101}, meta={"config_id": 101}),
    ]
    out = insert_apply_config_before_measurements(specs)

    names = [s.name for s in out]
    assert names == [
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
    ]
    assert out[0].kwargs["config_id"] == 101
    assert out[2].kwargs["config_id"] == 101
    assert out[4].kwargs["config_id"] == 102
    assert out[6].kwargs["config_id"] == 102
    assert out[8].kwargs["config_id"] == 101


def test_insert_apply_config_fallback_to_kwargs_when_meta_missing() -> None:
    specs = [
        PlanSpec("measure_yzstage", kwargs={"config_id": 7}, meta={}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 7}, meta={}),
        PlanSpec("measure_yzstage", kwargs={"config_id": 8}, meta={}),
    ]
    out = insert_apply_config_before_measurements(specs)
    assert [s.name for s in out] == [
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
        "apply_config",
        "measure_yzstage",
    ]
    assert out[0].kwargs["config_id"] == 7
    assert out[2].kwargs["config_id"] == 7
    assert out[4].kwargs["config_id"] == 8
