import pytest

from panic_detector.ui import theme
from panic_detector.ui.colorcheck import delta_e2000, hex_to_rgb, pairwise_distances, rgb_to_lab

# ΔE2000 ≈ 2.3 is a just-noticeable difference; >= 15 is clearly distinct at a glance.
MIN_DISTINCT = 15.0


def test_delta_e2000_reference_pair():
    # Sharma, Wu & Dalal (2005) test data, pair 1.
    assert delta_e2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)) == pytest.approx(2.0425, abs=1e-4)


def test_nvda_is_green():
    r, g, b = hex_to_rgb(theme.LEADER_COLORS["NVDA"])
    assert g > r and g > b


def test_leader_colors_are_distinct_for_normal_vision():
    d = pairwise_distances(theme.LEADER_COLORS)
    worst = min(d, key=d.get)
    assert d[worst] >= MIN_DISTINCT, f"{worst} too close: ΔE2000 = {d[worst]:.1f}"


def test_leader_colors_stand_out_from_background():
    bg = rgb_to_lab(hex_to_rgb(theme.BACKGROUND))
    for ticker, color in theme.LEADER_COLORS.items():
        assert delta_e2000(bg, rgb_to_lab(hex_to_rgb(color))) > 40, ticker


def test_up_and_down_colors_are_distinct():
    d = pairwise_distances({"up": theme.UP, "down": theme.DOWN})
    assert next(iter(d.values())) > 40
