# src/mouse_bluesky/planner/logbook_integration.py
from __future__ import annotations

from pathlib import Path
from typing import Iterable

try:
    from mouse_logbook.legacy import Logbook2MouseReader
except Exception as e:  # pragma: no cover
    Logbook2MouseReader = None  # type: ignore[assignment]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def iter_mouse_logbook_entries(
    *,
    logbook_path: Path,
    project_base_path: Path,
    load_all: bool = False,
) -> Iterable[object]:
    """Yield enriched logbook entries using mouse_logbook.

    We intentionally return `Iterable[object]` here to avoid hard coupling in types.
    Downstream compilers rely on attribute access (proposal/sampleid/sampos/protocol/additional_parameters).
    """
    if Logbook2MouseReader is None:  # pragma: no cover
        raise RuntimeError(
            "mouse_logbook is not installed or import failed. "
            "Install mouse-logbook and retry."
        ) from _IMPORT_ERROR

    reader = Logbook2MouseReader(
        logbook_path,
        project_base_path=project_base_path,
        load_all=load_all,
    )
    yield from reader
