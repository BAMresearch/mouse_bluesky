import pytest

from mouse_bluesky.planner.models import CollatePolicy
from mouse_bluesky.planner.params import parse_additional_parameters


def test_parse_additional_parameters_plain_strings() -> None:
    raw = {"collate": "ALLOW", "foo": "bar", "num": "123"}
    out = parse_additional_parameters(raw)
    assert out["collate"] == CollatePolicy.ALLOW
    assert out["foo"] == "bar"
    assert out["num"] == "123"  # stays string unless provided via __json__


def test_parse_additional_parameters_json_override() -> None:
    raw = {
        "foo": "bar",
        "__json__": '{"foo": "override", "repeats": 3, "configs": [101, 102], "collate": "FORBID"}',
    }
    out = parse_additional_parameters(raw)
    assert out["foo"] == "override"
    assert out["repeats"] == 3
    assert out["configs"] == [101, 102]
    assert out["collate"] == CollatePolicy.FORBID


def test_parse_additional_parameters_invalid_json_raises() -> None:
    raw = {"__json__": '{"repeats": 3, '}  # broken JSON
    with pytest.raises(ValueError):
        parse_additional_parameters(raw)


def test_parse_additional_parameters_collate_case_insensitive() -> None:
    raw = {"collate": "forbid"}
    out = parse_additional_parameters(raw)
    assert out["collate"] == CollatePolicy.FORBID
