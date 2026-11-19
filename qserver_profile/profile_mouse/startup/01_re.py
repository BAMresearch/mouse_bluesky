from __future__ import annotations

from bluesky import RunEngine

from mouse_bluesky.identity import configure_run_identity

# Minimal RunEngine required by Queue Server
RE = RunEngine({})
configure_run_identity(RE)


# # Optional: print documents to console (useful in demo mode)
# def _print_doc(name, doc):
#     print(f"[RE] {name}: keys={list(doc)}")


# RE.subscribe(_print_doc)
