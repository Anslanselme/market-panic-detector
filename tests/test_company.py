import math

import numpy as np
import pytest

from panic_detector.config import load_universe
from panic_detector.i18n import LANGUAGES, load_language


def test_every_company_has_a_description_in_every_language():
    for code in LANGUAGES:
        strings = load_language(code)
        for ticker in load_universe().tickers:
            assert strings.get(f"company.{ticker}", "").strip(), (code, ticker)


def test_profile_matches_a_manual_calculation(dashboard_data):
    from panic_detector.ui.company import company_profile

    data, window, index, ticker = dashboard_data, 60, 200, "AAPL"
    p = company_profile(data, window, index, ticker)
    wd = data.windows[window]
    date = wd.dates[index]
    r = data.returns.loc[:date].iloc[-window:]
    a, spy = r[ticker], r["SPY"]
    assert p.date == date and p.in_network
    assert p.beta == pytest.approx(np.cov(a, spy, ddof=1)[0, 1] / spy.var())
    assert p.volatility == pytest.approx(a.std() * math.sqrt(252))
    assert p.total_return == pytest.approx(math.exp(a.sum()) - 1)
    snap = wd.snapshot(index)
    others = [t for t in snap.tickers if t != ticker]
    assert p.avg_corr == pytest.approx(np.mean([np.corrcoef(a, r[t])[0, 1] for t in others]))


def test_neighbours_are_the_tree_links(dashboard_data):
    from panic_detector.ui.company import company_profile

    wd = dashboard_data.windows[60]
    snap = wd.snapshot(250)
    k = int(np.bincount(snap.edges.ravel()).argmax())  # the hub: several links
    ticker = snap.tickers[k]
    p = company_profile(dashboard_data, 60, 250, ticker)
    expected = {snap.tickers[b if a == k else a] for a, b in snap.edges if k in (a, b)}
    assert {t for t, _ in p.neighbours} == expected
    rhos = [rho for _, rho in p.neighbours]
    assert rhos == sorted(rhos, reverse=True)


def test_late_listing_is_reported_absent(dashboard_data):
    from panic_detector.ui.company import company_profile

    p = company_profile(dashboard_data, 60, 10, "META")  # META has no prices for the first 150 days
    assert not p.in_network and p.neighbours == []
    assert math.isnan(p.beta)
