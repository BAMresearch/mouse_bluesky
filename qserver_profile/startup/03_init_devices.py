from mouse_bluesky.devices.eiger import EigerWithStats, ad_setup
from mouse_bluesky.devices.mouse_motors import DualSourceMotor, SampleStageYZ, BeamStop, Slit

# for my IOC, these parameters apply:
AD_IOC = "eiger:"
FILE_BASE_IOC = "/tmp/current/"
FILE_BASE_BLUESKY = "/mnt/iockad/tmp/"

eiger = EigerWithStats(AD_IOC, name="eiger")
ad_setup(eiger)

# Connect to the sample stage and beam stop, which are needed for the measure_yzstage plan.:

sample_stage_yz = SampleStageYZ("newport1:", name="sample_stage_yz")

beam_stop = BeamStop("ims:", name="beam_stop")
s1 = Slit('ims:s1', name="s1")
s2 = Slit('ims:s2', name="s2")
s3 = Slit('ims:s3', name="s3")
s1.wait_for_connection()
s2.wait_for_connection()
s3.wait_for_connection()
dual = DualSourceMotor("ims:dual", name="dual_source_motor")
