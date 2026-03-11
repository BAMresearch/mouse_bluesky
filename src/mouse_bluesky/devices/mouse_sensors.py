# shutter:
from ophyd import Component as Cpt
from ophyd import Device, EpicsSignal, EpicsSignalRO


class PressureGauge(Device):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    pressure = Cpt(EpicsSignalRO, "pressure", kind='hinted')

class Arduino(Device):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    temperature_env = Cpt(EpicsSignalRO, "t0", kind='hinted')
    temperature_stage = Cpt(EpicsSignalRO, "t1", kind='hinted')
    temperature_aux = Cpt(EpicsSignalRO, "t2", kind='hinted')
    digital_output_0 = Cpt(EpicsSignal, "do0", kind='hinted')
    digital_output_1 = Cpt(EpicsSignal, "do1", kind='hinted')
    digital_output_2 = Cpt(EpicsSignal, "do2", kind='hinted')
    digital_output_3 = Cpt(EpicsSignal, "do3", kind='hinted')
    digital_output_4 = Cpt(EpicsSignal, "do4", kind='hinted')
    digital_output_5 = Cpt(EpicsSignal, "do5", kind='hinted')
    digital_output_6 = Cpt(EpicsSignal, "do6", kind='hinted')
    digital_output_7 = Cpt(EpicsSignal, "do7", kind='hinted')
    digital_input_0 = Cpt(EpicsSignalRO, "di0", kind='hinted')
    digital_input_1 = Cpt(EpicsSignalRO, "di1", kind='hinted')
    digital_input_2 = Cpt(EpicsSignalRO, "di2", kind='hinted')
    digital_input_3 = Cpt(EpicsSignalRO, "di3", kind='hinted')
    digital_input_4 = Cpt(EpicsSignalRO, "di4", kind='hinted')
    digital_input_5 = Cpt(EpicsSignalRO, "di5", kind='hinted')
    digital_input_6 = Cpt(EpicsSignalRO, "di6", kind='hinted')
    digital_input_7 = Cpt(EpicsSignalRO, "di7", kind='hinted')
    digital_in_out_0 = Cpt(EpicsSignal, "dio0", kind='hinted')
    digital_in_out_1 = Cpt(EpicsSignal, "dio1", kind='hinted')
    digital_in_out_2 = Cpt(EpicsSignal, "dio2", kind='hinted')
    digital_in_out_3 = Cpt(EpicsSignal, "dio3", kind='hinted')
    digital_in_out_4 = Cpt(EpicsSignal, "dio4", kind='hinted')
    digital_in_out_5 = Cpt(EpicsSignal, "dio5", kind='hinted')
    digital_in_out_6 = Cpt(EpicsSignal, "dio6", kind='hinted')
    digital_in_out_7 = Cpt(EpicsSignal, "dio7", kind='hinted')
    analog_output_0 = Cpt(EpicsSignal, "ao0", kind='hinted')
    analog_output_1 = Cpt(EpicsSignal, "ao1", kind='hinted')
    analog_output_2 = Cpt(EpicsSignal, "ao2", kind='hinted')
    analog_output_3 = Cpt(EpicsSignal, "ao3", kind='hinted')
    analog_input_0 = Cpt(EpicsSignalRO, "ai0", kind='hinted')
    analog_input_1 = Cpt(EpicsSignalRO, "ai1", kind='hinted')
    analog_input_2 = Cpt(EpicsSignalRO, "ai2", kind='hinted')
    analog_input_3 = Cpt(EpicsSignalRO, "ai3", kind='hinted')
    