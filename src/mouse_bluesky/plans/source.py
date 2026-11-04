from attrs import frozen


@frozen
class SourceSettings:
    generator_name: str
    photon_energy_ev: float
    threshold_energy_ev: float


CU_SOURCE = SourceSettings(generator_name="cu_generator", photon_energy_ev=8050, threshold_energy_ev=4025)
MO_SOURCE = SourceSettings(generator_name="mo_generator", photon_energy_ev=17480, threshold_energy_ev=8740)


def source_settings_for_config_id(config_id: int) -> SourceSettings:
    """Use the legacy leading-digit rule: odd selects Cu, even selects Mo."""
    digits = [char for char in str(config_id) if char.isdigit()]
    if not digits:
        raise ValueError(f"`config_id` must contain at least one digit, got {config_id!r}")
    return CU_SOURCE if int(digits[0]) % 2 == 1 else MO_SOURCE
