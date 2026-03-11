from ophyd import Component as Cpt

# https://blueskyproject.io/ophyd/user/tutorials/device.html
from ophyd import (
    Device,
    EpicsMotor,
    # EpicsSignal,
    # EpicsSignalRO,
    PseudoPositioner,
    PseudoSingle,
    # PVPositioner,
    # SoftPositioner,
)
from ophyd.pseudopos import pseudo_position_argument, real_position_argument

# https://blueskyproject.io/ophyd/user/tutorials/device.html

# An example of interacting with a Modbus device using EPICs https://codebase.helmholtz.cloud/hzb/epics/ioc/source/SISSY1ManipulatorIOCSource


class SampleStageYZ(Device):

    """
    This device connects to the sample stage. Names are constructed by concatenation
    """
    def __init__(self, *args, **kwargs):  # slit_number:int|None = None
        super().__init__(*args, **kwargs)

    y = Cpt(EpicsMotor, "ysam")
    z = Cpt(EpicsMotor, "zsam")


class DualSourceMotor(Device):
    """
    This device connects to the sample stage. Names are constructed by concatenation
    """
    def __init__(self, *args, **kwargs):  # slit_number:int|None = None
        super().__init__(*args, **kwargs)

    dual = Cpt(EpicsMotor, "dual")


class Slit(PseudoPositioner):  # Device
    """
    This device connects to the sample stage. Names are constructed by concatenation
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    h_gap = Cpt(PseudoSingle, limits=(-5, 10), egu='mm')
    h_pos = Cpt(PseudoSingle, limits=(-5, 5), egu='mm')
    v_gap = Cpt(PseudoSingle, limits=(-5, 10), egu='mm')
    v_pos = Cpt(PseudoSingle, limits=(-5, 5), egu='mm')

    top = Cpt(EpicsMotor, "top")
    bot = Cpt(EpicsMotor, "bot")
    left = Cpt(EpicsMotor, "hl")
    right = Cpt(EpicsMotor, "hr")

    @pseudo_position_argument
    def forward(self, pseudo_pos):
        "Given a position in the psuedo coordinate system, transform to the real coordinate system."
        return self.RealPosition(
            top=pseudo_pos.v_pos + pseudo_pos.v_gap / 2,
            bot=pseudo_pos.v_pos - pseudo_pos.v_gap / 2,
            left=pseudo_pos.h_pos + pseudo_pos.h_gap / 2,
            right=pseudo_pos.h_pos - pseudo_pos.h_gap / 2
        )

    @real_position_argument
    def inverse(self, real_pos):
        "Given a position in the real coordinate system, transform to the pseudo coordinate system."
        return self.PseudoPosition(
            v_gap=real_pos.top - real_pos.bot,
            v_pos=(real_pos.top + real_pos.bot)/2,
            h_gap=real_pos.left - real_pos.right,
            h_pos=(real_pos.left + real_pos.right)/2,
        )

# usage:
# s1 = Slit('ims:s1', name = "s1")
# s2 = Slit('ims:s2', name = "s2")
# s3 = Slit('ims:s3', name = "s3")
# s1.wait_for_connection()
# s2.wait_for_connection()
# s3.wait_for_connection()


class BeamStop(Device):

    """
    This device connects to the sample stage. Names are constructed by concatenation
    """
    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)
        self.old_pos = 291.59
        self.out_position = 270
        self.in_position = 291.59

    bsr = Cpt(EpicsMotor, "bsr")
    bsz = Cpt(EpicsMotor, "bsz")

    def move_out(self):
        self.old_pos = self.bsr.user_readback.get()
        return self.bsr.move(270)

    def move_in(self):
        return self.bsr.move(self.old_pos)


class DetectorMotions(Device):

    """
    This device connects to the detector stage. Names are constructed by concatenation
    """
    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)

    x = Cpt(EpicsMotor, "detx")
    y = Cpt(EpicsMotor, "dety")
    z = Cpt(EpicsMotor, "detz")

