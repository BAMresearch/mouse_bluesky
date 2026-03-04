from __future__ import annotations

from bluesky import RunEngine

# Minimal RunEngine required by Queue Server
RE = RunEngine({})


# Optional: print documents to console (useful in demo mode)
def _print_doc(name, doc):
    print(f"[RE] {name}: keys={list(doc)}")


RE.subscribe(_print_doc)