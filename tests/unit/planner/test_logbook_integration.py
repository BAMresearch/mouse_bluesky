import types
from pathlib import Path

import pytest

from mouse_bluesky.planner import logbook_integration


def test_iter_mouse_logbook_entries_uses_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeReader:
        def __init__(self, logbook_path, project_base_path, load_all):
            self._items = [types.SimpleNamespace(proposal="P", sampleid=1, sampos="A", protocol="measure_once",
                                                 additional_parameters={}, row_index=0)]
        def __iter__(self):
            return iter(self._items)

    monkeypatch.setattr(logbook_integration, "Logbook2MouseReader", FakeReader)

    items = list(
        logbook_integration.iter_mouse_logbook_entries(
            logbook_path=Path("x.xlsx"),
            project_base_path=Path("projects"),
            load_all=False,
        )
    )
    assert len(items) == 1
    assert items[0].protocol == "measure_once"
