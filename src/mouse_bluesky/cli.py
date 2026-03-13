from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .planner.logbook2bluesky import QueueServerTarget, build_plan_specs_from_logbook, populate_queue
from .planner.validate import validate_specs
from .protocols.builtin import build_default_registry
from .settings import Settings


def _normalize_queue_response(response: Any) -> dict[str, Any]:
    """Return a normalized view of a Queue Server response."""
    normalized: dict[str, Any] = {"success": False, "msg": None, "traceback": None, "raw": response}

    if isinstance(response, Mapping):
        normalized["success"] = bool(response.get("success", False))
        normalized["msg"] = response.get("msg")
        normalized["traceback"] = response.get("traceback")
        return normalized

    if isinstance(response, tuple):
        for item in response:
            if isinstance(item, Mapping):
                normalized["success"] = bool(item.get("success", False))
                normalized["msg"] = item.get("msg")
                normalized["traceback"] = item.get("traceback")
                return normalized
        if response and isinstance(response[0], bool):
            normalized["success"] = bool(response[0])
            if len(response) > 1:
                normalized["msg"] = str(response[1])
            if len(response) > 2:
                normalized["traceback"] = str(response[2])
            return normalized

    success_attr = getattr(response, "success", None)
    if success_attr is not None:
        normalized["success"] = bool(success_attr)
        normalized["msg"] = getattr(response, "msg", None)
        normalized["traceback"] = getattr(response, "traceback", None)
        return normalized

    if isinstance(response, str):
        normalized["msg"] = response

    return normalized


def _cmd_build_specs(args: argparse.Namespace) -> int:
    """Compile and validate planned specs for a logbook input."""
    settings = Settings.from_env(
        root_default=args.root_default,
        config_default=args.config_default,
    )

    registry = build_default_registry()

    measurement_extra = {"root_path": str(args.root_path or settings.root_path)}
    apply_extra = {"config_root": str(args.config_root or settings.config_root)}

    specs = build_plan_specs_from_logbook(
        logbook_path=Path(args.logbook),
        project_base_path=Path(args.projects),
        registry=registry,
        load_all=args.load_all,
        apply_config_extra_kwargs=apply_extra,
        measurement_extra_kwargs=measurement_extra,
    )

    issues = validate_specs(
        specs,
        known_plans=set(registry.known()) | {"apply_config", "measure_yzstage"},
        config_root=args.config_root or settings.config_root,
    )

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps([{"kind": i.kind, "message": i.message, "context": i.context} for i in issues], indent=2),
            encoding="utf-8",
        )

    if issues and not args.quiet:
        for i in issues:
            ctx = f" {i.context}" if i.context else ""
            print(f"[{i.kind}] {i.message}{ctx}")

    if args.print_specs:
        for s in specs[: args.print_specs]:
            print(f"{s.name} {dict(s.kwargs)}")

    return 1 if issues else 0


def _cmd_enqueue(args: argparse.Namespace) -> int:
    """Compile, validate, and enqueue specs into Queue Server."""
    settings = Settings.from_env(root_default=args.root_default, config_default=args.config_default)
    registry = build_default_registry()

    measurement_extra = {"root_path": str(args.root_path or settings.root_path)}
    apply_extra = {"config_root": str(args.config_root or settings.config_root)}

    specs = build_plan_specs_from_logbook(
        logbook_path=Path(args.logbook),
        project_base_path=Path(args.projects),
        registry=registry,
        load_all=args.load_all,
        apply_config_extra_kwargs=apply_extra,
        measurement_extra_kwargs=measurement_extra,
    )

    issues = validate_specs(
        specs,
        known_plans=set(registry.known()) | {"apply_config", "measure_yzstage"},
        config_root=args.config_root or settings.config_root,
    )

    if issues:
        for i in issues:
            ctx = f" {i.context}" if i.context else ""
            print(f"[{i.kind}] {i.message}{ctx}")
        print("Refusing to enqueue due to validation issues.")
        return 1

    target = QueueServerTarget(
        zmq_control_addr=args.zmq,
        user=args.user,
        user_group=args.user_group,
    )
    responses = populate_queue(specs, target=target, position=args.position)

    # inspect responses for errors
    normalized = [_normalize_queue_response(r) for r in responses]
    failed = [r for r in normalized if not r["success"]]
    if failed:
        print(f"Queue add failed for {len(failed)} item(s):")
        for i, r in enumerate(failed, start=1):
            if r["msg"]:
                print(f"[{i}] msg={r['msg']}")
            else:
                print(f"[{i}] response={r['raw']!r}")
            if r["traceback"]:
                print(r["traceback"])
        return 1

    if not args.quiet:
        print(f"Enqueued {len(responses)} items to {args.zmq}.")
    return 0


def main(argv: list[str] | None = None) -> None:
    """Run the `mouse-bluesky` CLI entrypoint."""
    p = argparse.ArgumentParser(prog="mouse-bluesky", description="MOUSE Bluesky planning + Queue Server utilities")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        """Attach common CLI options shared by subcommands."""
        sp.add_argument("logbook", help="Path to logbook Excel file")
        sp.add_argument("projects", help="Base directory containing project/proposal spreadsheets")
        sp.add_argument("--load-all", action="store_true", help="Include entries with converttoscript!=1")
        sp.add_argument("--root-path", type=Path, default=None, help="Data root path (default from env)")
        sp.add_argument("--config-root", type=Path, default=None, help="Config root path containing {config_id}.nxs")
        sp.add_argument("--root-default", default="/data/mouse", help="Default root path if env not set")
        sp.add_argument("--config-default", default="/data/mouse_configs", help="Default config root if env not set")
        sp.add_argument("-q", "--quiet", action="store_true", help="Less output")

    p_build = sub.add_parser("validate", help="Compile and validate the planned queue")
    add_common(p_build)
    p_build.add_argument("--output-json", default=None, help="Write validation issues to a JSON file")
    p_build.add_argument("--print-specs", type=int, default=0, help="Print first N generated specs")
    p_build.set_defaults(func=_cmd_build_specs)

    p_enq = sub.add_parser("enqueue", help="Compile, validate, and enqueue into a running Queue Server")
    add_common(p_enq)
    p_enq.add_argument("--zmq", default="tcp://127.0.0.1:60615", help="Queue Server ZMQ control address")
    p_enq.add_argument("--position", default="back", choices=["front", "back"], help="Queue insertion position")
    p_enq.add_argument(
        "--prioritize",
        action="store_const",
        const="front",
        dest="position",
        help="Insert at queue front preserving spec order (enqueued in reverse under the hood)",
    )
    p_enq.add_argument("--user", default="mouse-bluesky", help="Queue Server request user")
    p_enq.add_argument("--user-group", default="primary", help="Queue Server request user group")
    p_enq.set_defaults(func=_cmd_enqueue)

    ns = p.parse_args(argv)
    rc = int(ns.func(ns))
    raise SystemExit(rc)
