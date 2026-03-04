from mouse_bluesky.planner.models import PlanSpec
from mouse_bluesky.planner.sequence import annotate_sequence_index


# tests a simple sequence counter that keeps track of the measurement number across a sequence of PlanSpecs, even if there are non-measurement steps in between. This is used to annotate each measurement with a sequence index that can be used for naming outputs, etc.
def test_sequence_index_counts_only_measurements() -> None:
    specs = [
        PlanSpec("apply_config", kwargs={"config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"entry_row_index": 1, "config_id": 101}),
        PlanSpec("measure_yzstage", kwargs={"entry_row_index": 2, "config_id": 101}),
        PlanSpec("apply_config", kwargs={"config_id": 102}),
        PlanSpec("measure_yzstage", kwargs={"entry_row_index": 3, "config_id": 102}),
    ]
    out = annotate_sequence_index(specs, start=0)

    seqs = [s.kwargs.get("sequence_index") for s in out if s.name == "measure_yzstage"]
    assert seqs == [0, 1, 2]

    # apply_config unchanged
    assert "sequence_index" not in out[0].kwargs
    assert "sequence_index" not in out[3].kwargs
