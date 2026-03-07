from __future__ import annotations

from bluesky.preprocessors import SupplementalData

from mouse_bluesky.plans.configure import build_baseline_signals

# Configure RE baseline after devices are initialized in 03_init_devices.py.
if "sd" not in globals():
    sd = SupplementalData()
    RE.preprocessors.append(sd)

sd.baseline = build_baseline_signals(namespace=globals())
