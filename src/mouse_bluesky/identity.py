"""Instrument-owned identity for every MOUSE run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from bluesky import RunEngine

RUN_IDENTITY = MappingProxyType({"facility": "BAM", "instrument": "MOUSE"})
IDENTITY_KEYS = ("facility", "instrument", "station")


def refuse_identity_keys(md: Mapping[str, object] | None) -> None:
    """Refuse caller-supplied identity, including values matching the instrument."""
    if md is None:
        return
    offending = [key for key in IDENTITY_KEYS if key in md]
    if offending:
        raise ValueError(f"Run identity keys are instrument-owned and cannot be supplied: {', '.join(offending)}")


class _RunIdentityValidator:
    def __init__(self, existing_validator: Callable[[dict], object]) -> None:
        self.existing_validator = existing_validator

    def __call__(self, md: dict) -> None:
        self.existing_validator(md)
        offending = [key for key, value in RUN_IDENTITY.items() if md.get(key) != value]
        if "station" in md:
            offending.append("station")
        if offending:
            raise ValueError(f"Invalid MOUSE run identity metadata: {', '.join(offending)}")


def configure_run_identity(RE: RunEngine) -> None:
    """Set MOUSE identity defaults and validate the merged metadata of every run."""
    RE.md.update(RUN_IDENTITY)
    if not isinstance(RE.md_validator, _RunIdentityValidator):
        RE.md_validator = _RunIdentityValidator(RE.md_validator)
