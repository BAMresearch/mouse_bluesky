from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import attrs
from bluesky_queueserver.manager.comms import zmq_single_request

from ..protocols.registry import LogbookEntryLike, ProtocolRegistry
from .config_insertion import insert_apply_config_on_change
from .logbook_integration import iter_mouse_logbook_entries
from .models import CompiledEntry, PlanSpec
from .params import parse_additional_parameters
from .scheduler import schedule


@attrs.frozen(slots=True)
class QueueServerTarget:
    """Connection details for a Queue Server control endpoint."""

    zmq_control_addr: str = "tcp://127.0.0.1:60615"
    user: str = "mouse-bluesky"
    user_group: str = "primary"


def compile_entries(entries: Iterable[LogbookEntryLike], *, registry: ProtocolRegistry) -> list[CompiledEntry]:
    """Compile logbook entries into protocol-aware planning units."""
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
    measurement_extra_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    """Build queue-ready plan specs from entries with scheduling and config insertion."""
    compiled = compile_entries(entries, registry=registry)
    ordered = schedule(compiled)
    with_configs = insert_apply_config_on_change(
        ordered,
        extra_apply_kwargs=dict(apply_config_extra_kwargs or {}),
    )
    extra_measurement_kwargs = dict(measurement_extra_kwargs or {})
    if not extra_measurement_kwargs:
        return with_configs

    out: list[PlanSpec] = []
    for spec in with_configs:
        if spec.name != "measure_yzstage":
            out.append(spec)
            continue
        merged_kwargs = dict(spec.kwargs)
        merged_kwargs.update(extra_measurement_kwargs)
        out.append(PlanSpec(name=spec.name, kwargs=merged_kwargs, meta=spec.meta))
    return out


def _queue_item_add_request(*, payload: Mapping[str, Any], zmq_control_addr: str) -> dict[str, Any]:
    """Submit one `queue_item_add` request with keyword compatibility for test stubs."""
    try:
        return zmq_single_request(
            method="queue_item_add",
            params=payload,
            zmq_control_addr=zmq_control_addr,
        )
    except TypeError as exc:
        if "zmq_control_addr" not in str(exc):
            raise
        return zmq_single_request(
            method="queue_item_add",
            params=payload,
            zmq_server_address=zmq_control_addr,
        )


def populate_queue(
    specs: Sequence[PlanSpec], *, target: QueueServerTarget, position: str = "back"
) -> list[dict[str, Any]]:
    """Push plan specs into Queue Server using `queue_item_add`.

    Queue Server inserts with ``pos="front"`` as stack-like prepends. To keep
    the execution order equal to ``specs`` when targeting the front, submit
    requests in reverse sequence.
    """
    enqueue_specs = reversed(specs) if position == "front" else specs
    responses: list[dict[str, Any]] = []
    for spec in enqueue_specs:
        payload = {
            "item": spec.to_qs_item(),
            "pos": position,
            "user": target.user,
            "user_group": target.user_group,
        }
        responses.append(_queue_item_add_request(payload=payload, zmq_control_addr=target.zmq_control_addr))
    return responses


def build_plan_specs_from_logbook(
    *,
    logbook_path: Path,
    project_base_path: Path,
    registry: ProtocolRegistry,
    load_all: bool = False,
    apply_config_extra_kwargs: Mapping[str, Any] | None = None,
    measurement_extra_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    """Read logbook rows and return fully prepared plan specs."""
    entries = list(
        iter_mouse_logbook_entries(
            logbook_path=logbook_path,
            project_base_path=project_base_path,
            load_all=load_all,
        )
    )
    return build_plan_specs(
        entries,
        registry=registry,
        apply_config_extra_kwargs=apply_config_extra_kwargs,
        measurement_extra_kwargs=measurement_extra_kwargs,
    )
