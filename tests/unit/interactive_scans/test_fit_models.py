from __future__ import annotations

from mouse_bluesky.interactive_scans.fit_models import (
    capillary_init_guess,
    edge_init_guess,
    guess_sigma,
    peak_or_valley_init_guess,
)


def test_guess_sigma_is_positive() -> None:
    assert guess_sigma(-1.0, 1.0) > 0.0


def test_peak_guess_contains_expected_keys() -> None:
    guess = peak_or_valley_init_guess("gaussian", start=-1.0, stop=1.0, invert=False)
    assert set(guess) >= {"bkg_c", "p_amplitude", "p_center", "p_sigma"}


def test_edge_guess_respects_down_direction() -> None:
    guess = edge_init_guess(start=-1.0, stop=1.0, direction="down")
    assert guess["edge_sigma"] < 0.0


def test_capillary_guess_orders_centers() -> None:
    guess = capillary_init_guess(start=-2.0, stop=2.0)
    assert guess["cap_center1"] < guess["cap_center2"]
