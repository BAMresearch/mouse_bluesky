from mouse_bluesky.devices.eiger import EigerWithStats, ad_configure_exposure, ad_setup
from mouse_bluesky.devices.generator import XrayGenerator
from mouse_bluesky.devices.mouse_motors import BeamStop, DetectorMotions, DualSourceMotor, SampleStageYZ, Slit
from mouse_bluesky.devices.mouse_sensors import Arduino, PressureGauge
from mouse_bluesky.devices.xarm import XArm850

# for my IOC, these parameters apply:
AD_IOC = "eiger:"
FILE_BASE_IOC = "/tmp/current/"
FILE_BASE_BLUESKY = "/mnt/iockad/tmp/"

eiger = EigerWithStats(AD_IOC, name="eiger")
ad_setup(eiger)

# Connect to the sample stage and beam stop, which are needed for the measure_yzstage plan.:

sample_stage_yz = SampleStageYZ("newport1:", name="sample_stage_yz")

beam_stop = BeamStop("ims:", name="beam_stop")
s1 = Slit("ims:s1", name="s1")
s2 = Slit("ims:s2", name="s2")
s3 = Slit("ims:s3", name="s3")
s1.wait_for_connection()
s2.wait_for_connection()
s3.wait_for_connection()
dual = DualSourceMotor("ims:", name="dual_source_motor")

# x-ray generator
cu_generator = XrayGenerator("source_cu:", name="cu_generator")
mo_generator = XrayGenerator("source_mo:", name="mo_generator")

det_stage = DetectorMotions("ims:", name="det_stage")

# sensors
pressure_gauge = PressureGauge("pressure_gauge:", name="pressure_gauge")
arduino = Arduino("portenta:", name="arduino")

# Optional xArm 850 (non-EPICS, uses xarm-python-sdk):
# xarm850 = XArm850(name="xarm850", host="192.168.1.240")
