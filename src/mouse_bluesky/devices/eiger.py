from typing import OrderedDict

from ophyd import EpicsSignal
from ophyd.areadetector import ADComponent, EigerDetector
from ophyd.areadetector.cam import EigerDetectorCam
from ophyd.areadetector.plugins import ImagePlugin, ROIPlugin, ROIStatNPlugin_V25, ROIStatPlugin_V35, StatsPlugin
from ophyd.areadetector.trigger_mixins import SingleTrigger


class EigerWithStats(SingleTrigger, EigerDetector):
    """
    ADEigerDetector

    SingleTrigger:

    * stop any current acquisition
    * sets image_mode to 'Multiple'
    """

    cam = ADComponent(EigerDetectorCam, "cam1:")

    image = ADComponent(ImagePlugin, "image1:")

    roi1 = ADComponent(ROIPlugin, "ROI1:")
    roistat1 = ADComponent(ROIStatPlugin_V35, "ROIStat1:")
    roistat1_1 = ADComponent(ROIStatNPlugin_V25, "ROIStat1:1:")
    stats1 = ADComponent(StatsPlugin, "Stats1:")
    Restart = ADComponent(EpicsSignal, "cam1:Restart")
    Initialize = ADComponent(EpicsSignal, "cam1:Initialize")
    FilePath = ADComponent(EpicsSignal, "cam1:FilePath")
    WaitForPlugins = ADComponent(EpicsSignal, "cam1:WaitForPlugins")


# areadetector setup
def ad_setup(det):
    det.wait_for_connection(timeout=3)
    det.roi1.nd_array_port.put("EIG")  # connect to the main ADEiger NDArray port
    det.roistat1.nd_array_port.put("EIG")  # ibid.
    det.stats1.nd_array_port.put("EIG")  # ibid.
    det.missing_plugins()

    # start the AD IOC and run the magic "test_capture_eiger.sh" script on the server
    det.stage_sigs = OrderedDict(
        [
            ("cam.acquire", 0),
        ]
    )

    det.roistat1_1.kind = "hinted"
    det.roistat1_1.total.kind = "hinted"

    det.image.stage_sigs["blocking_callbacks"] = "No"
