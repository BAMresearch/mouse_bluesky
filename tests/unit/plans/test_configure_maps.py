import pytest

from mouse_bluesky.plans.configure import HDF5_OPHYD_MAP_BASE


def test_hdf5_ophyd_map_base_is_immutable():
    with pytest.raises(TypeError):
        HDF5_OPHYD_MAP_BASE["/saxs/Saxslab/ysam"] = "sample_stage_yz.y"  # type: ignore[index]
