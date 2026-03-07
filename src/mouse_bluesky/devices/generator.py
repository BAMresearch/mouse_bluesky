# shutter: 
from ophyd import Component as Cpt
from ophyd import Device
from ophyd import EpicsSignal, EpicsSignalRO


class XrayGenerator(Device):

    def __init__(self, *args, **kwargs): 
        super().__init__(*args, **kwargs)

    shutter = Cpt(EpicsSignal, "shutter", kind='hinted')
    voltage = Cpt(EpicsSignalRO, "voltage_RBV", kind='hinted')
    current = Cpt(EpicsSignalRO, "current_RBV", kind='hinted')