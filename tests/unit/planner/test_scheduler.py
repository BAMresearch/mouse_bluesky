from mouse_bluesky.planner.models import CollatePolicy, CompiledEntry, PlanSpec
from mouse_bluesky.planner.scheduler import schedule


def spec(name: str, *, cfg: int | None, sample: str, step: int, repeat: int) -> PlanSpec:
    meta = {"sample_key": sample, "step": step, "repeat": repeat}
    if cfg is not None:
        meta["config_id"] = cfg
    return PlanSpec(name=name, kwargs={"config_id": cfg} if cfg is not None else {}, meta=meta)


def test_schedule_collates_only_within_contiguous_allow_blocks() -> None:
    # Segment layout: FORBID, (ALLOW block), FORBID, (ALLOW block)
    forbid_1 = CompiledEntry(
        collate=CollatePolicy.FORBID,
        specs=(spec("measure_yzstage", cfg=999, sample="S0", step=0, repeat=0),),
    )

    # ALLOW block of two entries; create an intentionally "unordered" list that should be sorted by config_id
    allow_block = CompiledEntry(
        collate=CollatePolicy.ALLOW,
        specs=(
            spec("measure_yzstage", cfg=102, sample="S1", step=0, repeat=0),
            spec("measure_yzstage", cfg=101, sample="S2", step=0, repeat=0),
        ),
    )

    forbid_2 = CompiledEntry(
        collate=CollatePolicy.FORBID,
        specs=(spec("measure_yzstage", cfg=888, sample="S3", step=0, repeat=0),),
    )

    allow_block_2 = CompiledEntry(
        collate=CollatePolicy.ALLOW,
        specs=(
            spec("measure_yzstage", cfg=201, sample="S4", step=0, repeat=0),
            spec("measure_yzstage", cfg=200, sample="S5", step=0, repeat=0),
        ),
    )

    out = schedule([forbid_1, allow_block, forbid_2, allow_block_2])

    # Must preserve segment order: forbid_1 first, forbid_2 stays between the two allow blocks
    assert out[0].meta["config_id"] == 999
    assert out[3].meta["config_id"] == 888

    # First ALLOW block should be collated by config_id: 101 then 102
    assert out[1].meta["config_id"] == 101
    assert out[2].meta["config_id"] == 102

    # Second ALLOW block should be collated by config_id: 200 then 201
    assert out[4].meta["config_id"] == 200
    assert out[5].meta["config_id"] == 201


def test_schedule_tiebreakers_sample_step_repeat() -> None:
    # Same config_id, ordering should then be sample_key, then step, then repeat
    allow = CompiledEntry(
        collate=CollatePolicy.ALLOW,
        specs=(
            spec("measure_yzstage", cfg=101, sample="B", step=0, repeat=1),
            spec("measure_yzstage", cfg=101, sample="A", step=1, repeat=0),
            spec("measure_yzstage", cfg=101, sample="A", step=0, repeat=0),
        ),
    )
    out = schedule([allow])
    assert [(s.meta["sample_key"], s.meta["step"], s.meta["repeat"]) for s in out] == [
        ("A", 0, 0),
        ("A", 1, 0),
        ("B", 0, 1),
    ]
