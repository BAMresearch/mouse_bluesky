import pytest

from mouse_bluesky.planner.materialize import materialize_plans
from mouse_bluesky.planner.models import PlanSpec


def plan_a(x: int):
    yield ("a", x)


def plan_b(y: str):
    yield ("b", y)


def test_materialize_plans_success() -> None:
    specs = [
        PlanSpec(name="plan_a", kwargs={"x": 1}),
        PlanSpec(name="plan_b", kwargs={"y": "hi"}),
    ]
    plans = materialize_plans(specs, {"plan_a": plan_a, "plan_b": plan_b})
    assert list(plans[0]) == [("a", 1)]
    assert list(plans[1]) == [("b", "hi")]


def test_materialize_plans_unknown_raises() -> None:
    specs = [PlanSpec(name="nope", kwargs={})]
    with pytest.raises(ValueError):
        materialize_plans(specs, {"plan_a": plan_a})
