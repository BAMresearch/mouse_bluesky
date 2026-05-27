# prepare interactive mode for use
from bluesky.callbacks import LiveTable
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks.mpl_plotting import (
    LivePlot,  # yet another one of the magic plotters.
    LiveScatter,  # yet another one of the magic plotters.
)

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


# define a step scan and a gap scan.
