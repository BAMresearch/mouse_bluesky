from __future__ import annotations

from types import SimpleNamespace

from ophyd import Signal
from ophyd.sim import SynAxis

from mouse_bluesky.plans.source import CU_SOURCE


class FakeEnergySignal(Signal):
    """Record set requests and emulate the Eiger's threshold reset."""

    def __init__(self, *, detector, field: str, value: float):
        super().__init__(name=f"eiger_{field}", value=value)
        self.detector = detector
        self.field = field
        self.respond_to_set = True

    def set(self, value, *, timeout=None, **kwargs):
        self.detector.writes.append((self.field, value))
        self.detector.set_timeouts.append(timeout)
        if self.field == "photon_energy":
            self.detector.cam.threshold_energy.put(0)
        return super().set(value if self.respond_to_set else self.get(), timeout=timeout, **kwargs)


class FakeEiger:
    """Signal-only detector for energy tests; never instantiates EPICS devices."""

    def __init__(
        self,
        *,
        photon_energy_ev: float = CU_SOURCE.photon_energy_ev,
        threshold_energy_ev: float = CU_SOURCE.threshold_energy_ev,
    ):
        self.writes: list[tuple[str, float]] = []
        self.set_timeouts: list[float | None] = []
        self.cam = SimpleNamespace(
            photon_energy=FakeEnergySignal(detector=self, field="photon_energy", value=photon_energy_ev),
            threshold_energy=FakeEnergySignal(detector=self, field="threshold_energy", value=threshold_energy_ev),
        )


def build_startup_namespace(
    *,
    include_yz: bool = True,
    include_gi: bool = False,
    include_generators: bool = True,
    include_sensors: bool = False,
    include_eiger: bool = False,
) -> dict[str, object]:
    """Build a fake namespace that mirrors the shipped startup profile."""
    namespace: dict[str, object] = {
        "det_stage": SimpleNamespace(x=SynAxis(name="detx"), y=SynAxis(name="dety"), z=SynAxis(name="detz")),
        "beam_stop": SimpleNamespace(
            bsr=SynAxis(name="bsr"),
            bsz=SynAxis(name="bsz"),
            out_position=270.0,
        ),
        "dual": SimpleNamespace(dual=SynAxis(name="dual")),
        "s1": SimpleNamespace(
            top=SynAxis(name="s1top"),
            bot=SynAxis(name="s1bot"),
            left=SynAxis(name="s1hl"),
            right=SynAxis(name="s1hr"),
        ),
        "s2": SimpleNamespace(
            top=SynAxis(name="s2top"),
            bot=SynAxis(name="s2bot"),
            left=SynAxis(name="s2hl"),
            right=SynAxis(name="s2hr"),
        ),
        "s3": SimpleNamespace(
            top=SynAxis(name="s3top"),
            bot=SynAxis(name="s3bot"),
            left=SynAxis(name="s3hl"),
            right=SynAxis(name="s3hr"),
        ),
    }

    if include_yz:
        namespace["sample_stage_yz"] = SimpleNamespace(y=SynAxis(name="ysam"), z=SynAxis(name="zsam"))
    if include_gi:
        namespace["sample_stage_gi"] = SimpleNamespace(x=SynAxis(name="gsx"), y=SynAxis(name="gsy"))
    if include_generators:
        namespace["cu_generator"] = SimpleNamespace(
            name="cu_generator",
            shutter=Signal(name="cu_shutter", value=0),
            voltage=Signal(name="cu_voltage", value=5000),
            current=Signal(name="cu_current", value=60),
        )
        namespace["mo_generator"] = SimpleNamespace(
            name="mo_generator",
            shutter=Signal(name="mo_shutter", value=0),
            voltage=Signal(name="mo_voltage", value=5000),
            current=Signal(name="mo_current", value=100),
        )
    if include_sensors:
        namespace["pressure_gauge"] = SimpleNamespace(pressure=Signal(name="pressure", value=1.2))
        namespace["arduino"] = SimpleNamespace(
            temperature_env=Signal(name="temperature_env", value=22.3),
            temperature_stage=Signal(name="temperature_stage", value=26.7),
        )
    if include_eiger:
        namespace["eiger"] = FakeEiger()

    return namespace
