from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from bluesky_queueserver.manager.comms import zmq_single_request

from ..protocols.registry import LogbookEntryLike, ProtocolRegistry
from .config_insertion import insert_apply_config_on_change
from .models import CompiledEntry, PlanSpec
from .params import parse_additional_parameters
from .scheduler import schedule


@dataclass(frozen=True, slots=True)
class QueueServerTarget:
    zmq_control_addr: str = "tcp://127.0.0.1:60615"


def compile_entries(entries: Iterable[LogbookEntryLike], *, registry: ProtocolRegistry) -> list[CompiledEntry]:
    compiled: list[CompiledEntry] = []
    for e in entries:
        spec = registry.get(e.protocol)
        params = parse_additional_parameters(e.additional_parameters)
        compiled.append(spec.compile(e, params))
    return compiled


def build_plan_specs(
    entries: Iterable[LogbookEntryLike],
    *,
    registry: ProtocolRegistry,
    apply_config_extra_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    compiled = compile_entries(entries, registry=registry)
    ordered = schedule(compiled)
    return insert_apply_config_on_change(ordered, extra_apply_kwargs=dict(apply_config_extra_kwargs or {}))


def populate_queue(specs: Sequence[PlanSpec], *, target: QueueServerTarget, position: str = "back") -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for s in specs:
        payload = {"item": s.to_qs_item(), "pos": position}
        responses.append(zmq_single_request(method="queue_item_add", params=payload, zmq_control_addr=target.zmq_control_addr))
    return responses
