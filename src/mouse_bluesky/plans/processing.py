"""Publish a processing trigger after a YMD's files have stopped changing."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from bluesky import plan_stubs as bps

from mouse_bluesky.processing_marker import (
    MARKER_NAME,
    build_manifest,
    scan_ymd_dir,
    validate_ymd,
    write_marker_atomically,
    ymd_dir,
)
from mouse_bluesky.settings import Settings

SETTLE_S = 10.0
SETTLE_TIMEOUT_S = 300.0
SETTLE_POLL_S = 2.0


def _settled_files(path: Path, *, settle_s: float, timeout_s: float, poll_interval_s: float) -> Iterator:
    files = scan_ymd_dir(path)
    if not files:
        raise FileNotFoundError(f"No files in YMD directory: {path}")
    first_scan = stable_since = time.monotonic()
    while True:
        now = time.monotonic()
        if now - stable_since >= settle_s and stable_since + settle_s <= first_scan + timeout_s:
            if not files:
                raise FileNotFoundError(f"No files in YMD directory: {path}")
            return files
        remaining = first_scan + timeout_s - now
        if remaining <= 0:
            raise TimeoutError(f"Files kept changing in {path}; did not settle within {timeout_s} s")
        yield from bps.sleep(min(poll_interval_s, remaining))
        current = scan_ymd_dir(path)
        if current != files:
            files = current
            stable_since = time.monotonic()


def mark_ymd_complete(
    *,
    ymd: str,
    root_path: str | None = None,
    settle_s: float = SETTLE_S,
    timeout_s: float = SETTLE_TIMEOUT_S,
    poll_interval_s: float = SETTLE_POLL_S,
) -> Iterator:
    """Write a settled YMD manifest and audit run; filesystem failures warn and return."""
    validate_ymd(ymd)
    if root_path is None:
        root_path = Settings.from_env().root_path.as_posix()
    path = ymd_dir(Path(root_path), ymd).absolute()
    marker_id = uuid.uuid4().hex
    yield from bps.open_run(
        md={
            "activity": "ymd_complete",
            "ymd": ymd,
            "marker_id": marker_id,
            "marker_path": (path / MARKER_NAME).as_posix(),
        }
    )
    try:
        files = yield from _settled_files(path, settle_s=settle_s, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
        manifest = build_manifest(path, ymd, marker_id, files)
        marker = write_marker_atomically(path, manifest)
    except OSError as exc:
        print(f"Warning: could not mark YMD complete: {exc}")
        yield from bps.close_run(exit_status="fail", reason=str(exc))
        return
    print(f"Wrote {marker}: {len(manifest['files'])} files, {len(manifest['sequences'])} sequences")
    yield from bps.close_run()
