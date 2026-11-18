"""Replay TiledWriter backup files into Tiled.

When Tiled fails during a run, ``TiledWriter(..., backup_directory=...)`` writes every document of
that run, from its start document on, to ``<first part of the run uid>.jsonl`` in the backup
directory, one ``{"name": ..., "doc": ...}`` object per line. Replaying a file sends those
documents through a fresh ``TiledWriter``, as the RunEngine would have done.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

REPLAYED_DIRNAME = "replayed"

Document = tuple[str, dict[str, Any]]


def backup_files(paths: Iterable[Path]) -> list[Path]:
    """Expand directories to the ``*.jsonl`` files directly inside them, keeping file arguments as given."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.glob("*.jsonl") if p.is_file()))
        else:
            files.append(path)
    return files


def read_documents(path: Path) -> list[Document]:
    """Read the ``(name, doc)`` pairs of one backup file."""
    with path.open(encoding="utf-8") as stream:
        items = [json.loads(line) for line in stream if line.strip()]
    return [(item["name"], item["doc"]) for item in items]


def is_complete(run: Any, documents: list[Document]) -> bool:
    """Return True if Tiled holds the stop document and every stream has the rows the backup's stop counts."""
    stops = [doc for name, doc in documents if name == "stop"]
    if not stops or not run.metadata.get("stop"):
        return False
    for stream, count in (stops[0].get("num_events") or {}).items():
        if stream not in run:
            if count:
                return False
            continue
        time = run[stream].read().get("time")
        rows = 0 if time is None else time.size
        if rows != count:
            return False
    return True


def _move_to_replayed(path: Path) -> Path:
    """Move a handled backup file into ``replayed/`` next to it without overwriting an earlier file."""
    done = path.parent / REPLAYED_DIRNAME
    done.mkdir(exist_ok=True)
    target = done / path.name
    counter = 1
    while target.exists():
        target = done / f"{path.stem}.{counter}{path.suffix}"
        counter += 1
    path.rename(target)
    return target


def _default_writer_factory(client: Any) -> Callable[[str, dict[str, Any]], Any]:
    from bluesky.callbacks.tiled_writer import TiledWriter

    # Unfinished backups have no stop document to flush the writer's event cache.
    return TiledWriter(client, batch_size=1)


def replay_file(
    path: Path,
    client: Any,
    *,
    replace_partial: bool = False,
    include_unfinished: bool = False,
    writer_factory: Callable[[Any], Callable[[str, dict[str, Any]], Any]] | None = None,
    log: Callable[[str], None] = print,
) -> bool:
    """Replay one backup file. Return True if the run is now complete in Tiled and the file was moved."""
    try:
        documents = read_documents(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        log(f"{path.name}: cannot read the backup ({error}); left in place")
        return False

    starts = [doc for name, doc in documents if name == "start"]
    if len(starts) != 1 or documents[0][0] != "start":
        log(f"{path.name}: expected the file to begin with its only start document; left in place")
        return False
    uid = starts[0]["uid"]
    has_stop = any(name == "stop" for name, _ in documents)
    if not has_stop and not include_unfinished:
        # TiledWriter keeps appending to a run's backup until the run ends, also after Tiled recovers.
        log(
            f"{path.name}: no stop document yet, so the run may still be in progress; left in place. "
            "Use --include-unfinished for a run that will never finish"
        )
        return False

    try:
        if uid in client:
            if is_complete(client[uid], documents):
                _move_to_replayed(path)
                log(f"{path.name}: run {uid} is already complete in Tiled; moved to {REPLAYED_DIRNAME}/")
                return True
            if not replace_partial:
                log(f"{path.name}: run {uid} is partly in Tiled; rerun with --replace-partial to rewrite it")
                return False
            if not has_stop:
                log(f"{path.name}: no stop document, so the partial run {uid} cannot be replaced; left in place")
                return False
            client.delete_contents(uid, recursive=True, external_only=False)
            log(f"{path.name}: deleted the partial run {uid}")

        writer = (writer_factory or _default_writer_factory)(client)
        for name, doc in documents:
            writer(name, doc)

        if has_stop and not is_complete(client[uid], documents):
            log(f"{path.name}: run {uid} was written but is not complete in Tiled; left in place")
            return False
    except Exception as error:  # noqa: BLE001 - report and continue with the next file
        log(f"{path.name}: replay failed ({type(error).__name__}: {error}); left in place")
        return False

    _move_to_replayed(path)
    note = "" if has_stop else " (the backup has no stop document: the run never finished)"
    log(f"{path.name}: replayed {len(documents)} documents as run {uid}{note}")
    return True


def replay_backups(
    paths: Iterable[Path],
    client: Any,
    *,
    replace_partial: bool = False,
    include_unfinished: bool = False,
    writer_factory: Callable[[Any], Callable[[str, dict[str, Any]], Any]] | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Replay every backup file in ``paths``. Return the number of files left for attention."""
    files = backup_files(paths)
    if not files:
        log("No backup files found.")
        return 0
    left = 0
    for path in files:
        try:
            done = replay_file(
                path,
                client,
                replace_partial=replace_partial,
                include_unfinished=include_unfinished,
                writer_factory=writer_factory,
                log=log,
            )
        except Exception as error:  # noqa: BLE001 - isolate validation and archive errors too
            log(f"{path.name}: replay failed ({type(error).__name__}: {error}); left in place")
            done = False
        if not done:
            left += 1
    return left
