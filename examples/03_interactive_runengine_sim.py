from __future__ import annotations

from bluesky import RunEngine

from mouse_bluesky.planner.materialize import materialize_plans
from mouse_bluesky.planner.models import PlanSpec


# A tiny demo plan (not the real instrument plan).
def demo_plan(x: int):
    yield ("demo", x)

plan_funcs = {"demo_plan": demo_plan}

specs = [PlanSpec("demo_plan", kwargs={"x": 1}), PlanSpec("demo_plan", kwargs={"x": 2})]
plans = materialize_plans(specs, plan_funcs)

RE = RunEngine({})
for p in plans:
    RE(p)

print("Done.")
