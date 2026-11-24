import numpy as np
import pandas as pd
import pytest

from panic_detector.eventstudy import (
    event_window,
    find_drawdowns,
    forward_log_return,
    fresh_events,
    non_overlapping,
    past_change,
    past_log_return,
    predictive_test,
)


def series(values, start="2020-01-01"):
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)))


def test_find_drawdowns_detects_completed_and_open_events():
    #        0    1    2   3   4    5    6    7   8    9    10   11
    path = [100, 105, 98, 90, 94, 106, 103, 108, 99, 95, 93.5, 96]
    s = series(path)
    events = find_drawdowns(s, 0.10)
    assert len(events) == 2
    first, second = events
    assert first.peak == s.index[1] and first.cross == s.index[3]
    # 90 -> 94 is only +4.4 %; 106 is the first close >= 99 (= 90 * 1.1).
    assert first.trough == s.index[3] and first.rebound == s.index[5]
    assert first.depth == pytest.approx(90 / 105 - 1)
    # 108 -> 95 is -12 % (cross), trough 93.5 (-13.4 %), no 10 % rebound yet.
    assert second.peak == s.index[7] and second.trough == s.index[10]
    assert second.cross == s.index[9] and second.rebound is None


def test_declines_below_threshold_are_ignored():
    s = series([100, 90.2, 100.5, 91, 101])  # -9.8 % and -9.45 %
    assert find_drawdowns(s, 0.10) == []


def test_second_decline_counts_without_a_new_all_time_high():
    # 100 -> 50 (-50 %), rebound to 80 (+60 %), then 80 -> 64 (-20 %), all below 100.
    s = series([100, 70, 50, 65, 80, 72, 64, 75])
    events = find_drawdowns(s, 0.10)
    assert [e.peak for e in events] == [s.index[0], s.index[4]]
    assert events[1].depth == pytest.approx(64 / 80 - 1)


def test_fresh_events_drop_aftershocks():
    s = series([100, 70, 50, 65, 80, 72, 64, 75] + [80 + i for i in range(40)] + [100, 85, 95])
    events = find_drawdowns(s, 0.10)
    assert len(events) == 3
    # Second event peaks 1 day after the first rebound: its pre-peak window overlaps.
    fresh = fresh_events(events, s.index, before=5)
    assert [e.peak for e in fresh] == [events[0].peak, events[2].peak]


def test_sign_test():
    from panic_detector.eventstudy import sign_test

    out = sign_test(pd.Series([60, 70, 80, 90, 95, 99, 40]))
    assert out["above"] == 6 and out["below"] == 1 and out["n"] == 7
    assert out["p"] == pytest.approx(0.125)


def test_event_window_alignment_and_edges():
    s = series(np.arange(10))
    w = event_window(s, s.index[2], before=3, after=2)
    assert list(w.index) == [-3, -2, -1, 0, 1, 2]
    assert np.isnan(w.loc[-3])
    assert w.loc[0] == 2 and w.loc[2] == 4


def test_forward_return_and_past_change_use_the_right_side_of_t():
    p = series([100, 110, 121, 133.1])
    fwd = forward_log_return(p, 1)
    assert fwd.iloc[0] == pytest.approx(np.log(1.1))
    assert np.isnan(fwd.iloc[-1])  # no future at the end
    x = past_change(series([1.0, 3.0, 6.0]), 1)
    assert np.isnan(x.iloc[0]) and x.iloc[2] == 3.0  # only past values
    past = past_log_return(p, 1)
    assert np.isnan(past.iloc[0])
    assert past.iloc[1] == pytest.approx(np.log(1.1))  # positive after a rise
    # Past return at t+h equals the forward return at t.
    assert np.allclose(past.shift(-1).dropna(), fwd.dropna())


def test_non_overlapping_sampling():
    df = pd.DataFrame({"x": range(100)})
    s = non_overlapping(df, 20)
    assert s["x"].tolist() == [0, 20, 40, 60, 80]
    assert non_overlapping(df, 20, start=5)["x"].tolist() == [5, 25, 45, 65, 85]


def test_predictive_test_finds_a_real_relation_and_not_a_fake_one():
    rng = np.random.default_rng(0)
    n, h = 4_000, 20
    idx = pd.bdate_range("2005-01-01", periods=n)
    x = pd.Series(rng.standard_normal(n), index=idx)
    y_related = pd.Series(0.5 * x.to_numpy() + rng.standard_normal(n), index=idx)
    y_noise = pd.Series(rng.standard_normal(n), index=idx)

    real = predictive_test(x, y_related, h, "x")
    assert real.pearson_r > 0.3 and real.pearson_p < 1e-6 and real.nw_p < 1e-6
    assert real.n_nonoverlap == n // h

    fake = predictive_test(x, y_noise, h, "x")
    assert fake.pearson_p > 0.01 and fake.nw_p > 0.01


def test_newey_west_is_wider_than_naive_on_overlapping_returns():
    """Overlapping 20-day returns are autocorrelated; HAC must not overstate significance."""
    import statsmodels.api as sm

    rng = np.random.default_rng(1)
    n, h = 3_000, 20
    idx = pd.bdate_range("2005-01-01", periods=n + h)
    daily = pd.Series(rng.standard_normal(n + h), index=idx)
    x = daily.rolling(h).sum()                        # overlapping signal
    y = daily.rolling(h).sum().shift(-h)              # overlapping forward sum
    res = predictive_test(x, y, h, "x")
    data = pd.concat({"x": x, "y": y}, axis=1).dropna()
    naive = sm.OLS(data["y"], sm.add_constant(data["x"])).fit()
    assert abs(res.nw_t) < abs(naive.tvalues["x"])
