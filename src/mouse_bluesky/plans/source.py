import math

from attrs import frozen
from bluesky import plan_stubs as bps

# Voltage counts are 10 V and current counts are 10 uA, so watts = raw V * raw I * 1e-4.
# Cu 5000/60 is 50 kV * 0.6 mA = 30 W; assume the same raw-unit scaling for Mo.
GENERATOR_WATTS_PER_RAW_UNIT = 1e-4
MIN_SOURCE_POWER_FRACTION = 0.9


@frozen
class SourceSettings:
    generator_name: str
    photon_energy_ev: float
    threshold_energy_ev: float
    nominal_power_w: float


CU_SOURCE = SourceSettings(
    generator_name="cu_generator", photon_energy_ev=8047.78, threshold_energy_ev=4023.89, nominal_power_w=30
)
MO_SOURCE = SourceSettings(
    generator_name="mo_generator", photon_energy_ev=17480, threshold_energy_ev=8740, nominal_power_w=50
)


def source_power_w(voltage_raw, current_raw) -> float:
    return float(voltage_raw * current_raw * GENERATOR_WATTS_PER_RAW_UNIT)


def check_source_power(generator, source: SourceSettings):
    """Require at least 90% of nominal power before any measurement writes."""
    voltage_raw = yield from bps.rd(generator.voltage)
    current_raw = yield from bps.rd(generator.current)
    power_w = source_power_w(voltage_raw, current_raw)
    minimum_w = MIN_SOURCE_POWER_FRACTION * source.nominal_power_w
    if not math.isfinite(power_w) or power_w < minimum_w:
        raise RuntimeError(
            f"{generator.name}: source power {power_w} W, minimum {minimum_w} W "
            f"(voltage_raw={voltage_raw}, current_raw={current_raw})"
        )


def source_settings_for_config_id(config_id: int) -> SourceSettings:
    """Use the legacy leading-digit rule: odd selects Cu, even selects Mo."""
    digits = [char for char in str(config_id) if char.isdigit()]
    if not digits:
        raise ValueError(f"`config_id` must contain at least one digit, got {config_id!r}")
    return CU_SOURCE if int(digits[0]) % 2 == 1 else MO_SOURCE
