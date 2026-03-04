from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bluesky_queueserver.manager.comms import zmq_single_request

from ..protocols.registry import LogbookEntryLike, ProtocolRegistry
from .config_insertion import insert_apply_config_on_change
from .logbook_integration import iter_mouse_logbook_entries
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
    measurement_extra_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    compiled = compile_entries(entries, registry=registry)
    ordered = schedule(compiled)

    with_configs = insert_apply_config_on_change(
        ordered,
        extra_apply_kwargs=dict(apply_config_extra_kwargs or {}),
    )

    # <-- HERE is the injection step
    with_measurement_kwargs = _inject_kwargs(
        with_configs,
        plan_name="measure_yzstage",
        extra=dict(measurement_extra_kwargs or {}),
    )

    return with_measurement_kwargs


def _inject_kwargs(specs: list[PlanSpec], *, plan_name: str, extra: Mapping[str, Any]) -> list[PlanSpec]:
    """Return new PlanSpecs with `extra` merged into kwargs for `plan_name` specs."""
    extra_dict = dict(extra)
    if not extra_dict:
        return specs

    out: list[PlanSpec] = []
    for s in specs:
        if s.name == plan_name:
            new_kwargs = dict(s.kwargs)
            new_kwargs.update(extra_dict)
            out.append(PlanSpec(name=s.name, kwargs=new_kwargs, meta=s.meta))
        else:
            out.append(s)
    return out


def populate_queue(specs: Sequence[PlanSpec], *, target: QueueServerTarget, position: str = "back") -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for s in specs:
        payload = {"item": s.to_qs_item(), "pos": position}
        responses.append(zmq_single_request(
            "queue_item_add",
            payload,
            zmq_server_address=target.zmq_control_addr,
        ))
        # responses.append(_qs_request(method="queue_item_add", params=payload, zmq_addr=target.zmq_control_addr))
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
