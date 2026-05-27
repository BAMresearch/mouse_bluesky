# prepare interactive mode for use
from bluesky.callbacks import LiveTable
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks.mpl_plotting import (
    LivePlot,  # yet another one of the magic plotters.
    LiveScatter,  # yet another one of the magic plotters.
)
from bluesky.preprocessors import run_decorator

from mouse_bluesky.devices.eiger import ad_configure_exposure

if "bec" not in globals():
    bec = BestEffortCallback()
    # RE.subscribe(bec)
import lmfit  # basic
import matplotlib
import matplotlib.pyplot as plt
from lmfit.models import (  # there's a host of predefined models, check them out! don't know how to use them though
    LinearModel,
    RectangleModel,
    StepModel,
)
from scipy.special import (
    erf,  # the error function, which is the integral of a Gaussian. we will use this to model the edges of our features.
)

step_fit_model = StepModel(form="erf") + LinearModel()  # this is a model that is the sum of a rectangle and a line.
step_fit_params = step_fit_model.make_params(
    center=dict(
        value=0
    ),  # the center of the step, which is the position of the edge. we will fit this parameter to find the edge position.
    amplitude=dict(
        value=0.01, min=-1, max=1
    ),  # the height of the step. we will fit this parameter to find the edge height.
    sigma=dict(value=0.1, min=0.01, max=1),  # the width of the step.
    slope=dict(value=0, vary=False),  # the slope of the line.
    intercept=dict(
        value=1, expr="-amplitude"
    ),  # the intercept of the line. we will fit this parameter to find the background level.
)  # this is a container for the parameters of the model, which we will use to fit our data.

gap_fit_model = RectangleModel(form="erf") + LinearModel()  # this is a model that is the sum of a rectangle and a line.
gap_fit_params = gap_fit_model.make_params(
    center1=dict(
        value=0
    ),  # the center of the step, which is the position of the edge. we will fit this parameter to find the edge position.
    center2=dict(
        value=0
    ),  # the center of the step, which is the position of the edge. we will fit this parameter to find the edge position.
    amplitude=dict(
        value=0.01, min=-1, max=1
    ),  # the height of the step. we will fit this parameter to find the edge height.
    sigma1=dict(value=0.1, min=0.01, max=1),  # the width of the step.
    sigma2=dict(expr="sigma1"),  # the width of the step.
    slope=dict(value=0, vary=False),  # the slope of the line.
    intercept=dict(
        value=1, expr="-amplitude"
    ),  # the intercept of the line. we will fit this parameter to find the background level.
)  # this is a container for the parameters of the model, which we will use to fit our data.

# RE(ad_configure_exposure(eiger, exposure_time=1, output_path="tmp/scans"))  # set the exposure time of the detector to 0.1 seconds for interactive scans.
# define a bluesky plan to reset the detector roistat area


@run_decorator()
def reset_roistat_area():
    """Reset the roistat area of the Eiger detector."""
    yield from bps.mv(
        eiger.roistat1_1.min_.x,
        200,
        eiger.roistat1_1.min_.y,
        200,
        eiger.roistat1_1.size.x,
        800,
        eiger.roistat1_1.size.y,
        800,
    )  # reset the roistat area to the full detector area.


@run_decorator()
def open_shutter():
    """Open the shutter of the x-ray generator."""
    yield from bps.mv(cu_generator.shutter, 1)  # open the shutter of the x-ray generator.


@run_decorator()
def close_shutter():
    """Close the shutter of the x-ray generator."""
    yield from bps.mv(cu_generator.shutter, 0)  # close the shutter of the x-ray generator.


# define a step scan and a gap scan.
