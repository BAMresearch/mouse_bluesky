from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import attrs
from bluesky_queueserver.manager.comms import zmq_single_request

from ..protocols.registry import LogbookEntryLike, ProtocolRegistry
from .config_insertion import insert_apply_config_before_measurements
from .logbook_integration import iter_mouse_logbook_entries
from .marker_insertion import insert_ymd_complete_markers
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
    insert_ymd_complete: bool = False,
) -> list[PlanSpec]:
    """Build queue-ready plan specs from entries with scheduling and per-measurement config insertion."""
    compiled = compile_entries(entries, registry=registry)
    ordered = schedule(compiled)
    with_configs = insert_apply_config_before_measurements(ordered)
    extra_apply_kwargs = dict(apply_config_extra_kwargs or {})
    extra_measurement_kwargs = dict(measurement_extra_kwargs or {})
    out: list[PlanSpec] = []
    for spec in with_configs:
        merged_kwargs = dict(spec.kwargs)
        if spec.name == "apply_config":
            # Protocols may supply their own config applications (e.g. restore).
            merged_kwargs = {**extra_apply_kwargs, **merged_kwargs}
        elif spec.name == "measure_yzstage":
            merged_kwargs.update(extra_measurement_kwargs)
        out.append(PlanSpec(name=spec.name, kwargs=merged_kwargs, meta=spec.meta))
    return insert_ymd_complete_markers(out) if insert_ymd_complete else out


def _queue_request(method: str, *, params: Mapping[str, Any] | None = None, zmq_control_addr: str) -> Any:
    """Submit a request using either supported control-address keyword."""
    try:
        return zmq_single_request(
            method=method,
            params=params,
            zmq_control_addr=zmq_control_addr,
        )
    except TypeError as exc:
        if "zmq_control_addr" not in str(exc):
            raise
        return zmq_single_request(
            method=method,
            params=params,
            zmq_server_address=zmq_control_addr,
        )


def _queue_item_add_request(*, payload: Mapping[str, Any], zmq_control_addr: str) -> Any:
    """Submit one `queue_item_add` request with keyword compatibility for test stubs."""
    return _queue_request("queue_item_add", params=payload, zmq_control_addr=zmq_control_addr)


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


def _remove_run_now_items(items: Sequence[Mapping[str, Any]], *, target: QueueServerTarget) -> None:
    """Remove the stop only after confirming the plan was removed."""
    for item, label in zip(items, ("plan", "queue stop"), strict=True):
        uid = item["item_uid"]
        response, error = _queue_request(
            "queue_item_remove", params={"uid": uid}, zmq_control_addr=target.zmq_control_addr
        )
        if error or not response or not response.get("success"):
            reason = error or (response or {}).get("msg") or "request failed"
            print(f"Could not remove {label} ({uid}): {reason}.")
            print("The queue stop was left in place.")
            return
        print(f"Removed {label} ({uid}).")


def run_now_then_stop(name: str, *, target: QueueServerTarget) -> bool:
    """Start a plan followed by a queue stop, preserving queued measurements."""
    status, error = _queue_request("status", zmq_control_addr=target.zmq_control_addr)
    status = status or {}
    state = status.get("manager_state", "unknown")
    # The status endpoint has no `success` field in Queue Server 0.0.24, and its `msg` is the
    # server version, so it only explains a refusal when a request actually failed.
    if error:
        reason = f"no reply from the Queue Server ({error})"
    elif not status.get("success", True):
        reason = status.get("msg") or "status request failed"
    elif not status.get("worker_environment_exists"):
        reason = "the worker environment is not open"
    elif state != "idle":
        reason = "the manager is not idle"
    else:
        reason = None
    if reason:
        print(f"Refusing to run {name}: manager state={state}; {reason}.")
        print("Stop the queue, wait until it is idle, then run the command again.")
        return False

    batch, error = _queue_request(
        "queue_item_add_batch",
        params={
            "items": [PlanSpec(name=name).to_qs_item(), {"item_type": "instruction", "name": "queue_stop"}],
            "pos": "front",
            "user": target.user,
            "user_group": target.user_group,
        },
        zmq_control_addr=target.zmq_control_addr,
    )
    if error or not batch or not batch.get("success"):
        reason = error or (batch or {}).get("msg") or "request failed"
        print(f"Queue batch add failed: {reason}.")
        return False

    started, error = _queue_request("queue_start", zmq_control_addr=target.zmq_control_addr)
    if error or not started or not started.get("success"):
        reason = error or (started or {}).get("msg") or "request failed"
        print(f"Queue start failed: {reason}.")
        _remove_run_now_items(batch["items"], target=target)
        return False
    return True


def build_plan_specs_from_logbook(
    *,
    logbook_path: Path,
    project_base_path: Path,
    registry: ProtocolRegistry,
    load_all: bool = False,
    apply_config_extra_kwargs: Mapping[str, Any] | None = None,
    measurement_extra_kwargs: Mapping[str, Any] | None = None,
    insert_ymd_complete: bool = False,
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
        insert_ymd_complete=insert_ymd_complete,
    )
