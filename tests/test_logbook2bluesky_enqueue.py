from __future__ import annotations

from typing import Mapping

import attrs
import pytest

from mouse_bluesky.planner.logbook2bluesky import QueueServerTarget, build_plan_specs, populate_queue
from mouse_bluesky.protocols.builtin import build_default_registry


@attrs.frozen(slots=True)
class FakeEntry:
    row_index: int
    proposal: str
    sampleid: int
    sampos: str
    protocol: str
    additional_parameters: Mapping[str, str]
    batchnum: int = 1
    positions: Mapping[str, float] = attrs.field(factory=dict)

    @property
    def ymd(self) -> str:
        return "20251221"


def test_build_and_populate_queue_calls_qs_api(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = build_default_registry()

    # Two entries in an ALLOW block: configs collated by config_id
    e1 = FakeEntry(
        row_index=1,
        proposal="P",
        sampleid=10,
        sampos="A",
        protocol="standard_measurements",
        additional_parameters={"__json__": '{"configs":[102,101],"repeats":1,"collate":"ALLOW"}'},
    )
    e2 = FakeEntry(
        row_index=2,
        proposal="P",
        sampleid=11,
        sampos="B",
        protocol="standard_measurements",
        additional_parameters={"__json__": '{"configs":[101],"repeats":1,"collate":"ALLOW"}'},
    )

    specs = build_plan_specs([e1, e2], registry=reg)

    # apply_config should be inserted when config changes along scheduled order.
    # Collation should group all 101 measurements before 102.
    names = [s.name for s in specs]
    assert "apply_config" in names
    assert "measure_yzstage" in names

    # Mock Queue Server API call
    calls = []

    def fake_zmq_single_request(*, method, params, zmq_control_addr):  # noqa: ANN001
        calls.append((method, params, zmq_control_addr))
        return {"success": True, "method": method}

    monkeypatch.setattr("mouse_bluesky.planner.logbook2bluesky.zmq_single_request", fake_zmq_single_request)

    target = QueueServerTarget(zmq_control_addr="tcp://127.0.0.1:60615", user="tester", user_group="primary")
    responses = populate_queue(specs, target=target)

    assert len(responses) == len(specs)
    assert all(r.get("success") for r in responses)

    # Ensure payloads are Queue Server plan items
    for (method, params, addr), spec in zip(calls, specs, strict=True):
        assert method == "queue_item_add"
        assert addr == "tcp://127.0.0.1:60615"
        assert "item" in params
        assert params["user"] == "tester"
        assert params["user_group"] == "primary"
        assert params["item"]["item_type"] == "plan"
        assert params["item"]["name"] == spec.name
        assert isinstance(params["item"]["kwargs"], dict)
