import json

import numpy as np
from ophyd.sim import make_fake_device

from mouse_bluesky.devices.eiger import EigerWithStats, ad_setup

TS_FIELDS = ("ts_max_value", "ts_mean_value", "ts_min_value", "ts_net", "ts_total", "ts_timestamp")


def make_eiger():
    eiger = make_fake_device(EigerWithStats)("SIM:", name="eiger")
    ad_setup(eiger)
    return eiger


def test_ad_setup_leaves_roi_time_series_out_of_the_reading():
    eiger = make_eiger()

    read_keys = set(eiger.describe())
    assert not any("_ts_" in key for key in read_keys)
    assert "eiger_roistat1_1_total" in read_keys
    assert "eiger_roistat1_1_net" in read_keys
    assert eiger.hints["fields"] == ["eiger_roistat1_1_total"]


def test_eiger_reading_stays_json_encodable_when_time_series_hold_arrays():
    eiger = make_eiger()
    for name in TS_FIELDS:
        getattr(eiger.roistat1_1, name).sim_put(np.arange(5.0))

    values = {key: reading["value"] for key, reading in eiger.read().items()}

    json.dumps(values)
