import networkx as nx
import numpy as np
import pandas as pd
import pytest
from scipy.sparse.csgraph import minimum_spanning_tree as scipy_mst

from panic_detector.metrics import rolling_correlations
from panic_detector.network import (
    StableLayout,
    correlation_distance,
    minimum_spanning_tree,
    stress,
    tree_path_distances,
)


def block_correlation(n=50, seed=0, t=300):
    """Correlation of returns with a market factor and 5 sector factors."""
    rng = np.random.default_rng(seed)
    sectors = np.arange(n) % 5
    market = rng.standard_normal((t, 1))
    sector = rng.standard_normal((t, 5))[:, sectors]
    r = 0.5 * market + 0.6 * sector + rng.standard_normal((t, n))
    return np.corrcoef(r, rowvar=False), [f"S{i}" for i in range(n)]


def test_distance_formula():
    corr = np.array([[1.0, 0.0, -1.0], [0.0, 1.0, 0.5], [-1.0, 0.5, 1.0]])
    d = correlation_distance(corr)
    assert d[0, 0] == 0.0
    assert d[0, 1] == pytest.approx(np.sqrt(2))
    assert d[0, 2] == pytest.approx(2.0)
    assert d[1, 2] == pytest.approx(1.0)


@pytest.mark.parametrize("n", [5, 30, 50])
def test_mst_has_n_minus_one_edges_and_is_a_tree(n):
    corr, tickers = block_correlation(n)
    tree = minimum_spanning_tree(corr, tickers)
    assert tree.number_of_nodes() == n
    assert tree.number_of_edges() == n - 1
    assert nx.is_tree(tree)


def test_mst_total_length_matches_scipy():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    dist = correlation_distance(corr)
    reference = scipy_mst(np.triu(dist, k=1)).sum()
    assert tree.size(weight="weight") == pytest.approx(reference)


def test_mst_links_same_sector_stocks():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    same = sum(int(u[1:]) % 5 == int(v[1:]) % 5 for u, v in tree.edges())
    assert same >= 0.8 * tree.number_of_edges()


def test_layout_reproduces_tree_distances():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    pos = StableLayout().step(tree, tickers)
    target = tree_path_distances(tree, tickers)
    drawn = np.linalg.norm(pos[:, None] - pos[None], axis=-1)
    iu = np.triu_indices(len(tickers), 1)
    assert np.corrcoef(target[iu], drawn[iu])[0, 1] > 0.9
    # Drawn edges are close to their correlation distance (hubs with many leaves
    # cannot be drawn exactly in 2-D, so a few edges get stretched).
    idx = {t: i for i, t in enumerate(tickers)}
    errors = [abs(drawn[idx[u], idx[v]] / d["weight"] - 1) for u, v, d in tree.edges(data=True)]
    assert np.median(errors) < 0.2
    assert np.percentile(errors, 90) < 0.5


def test_layout_is_stable_from_one_day_to_the_next():
    rng = np.random.default_rng(3)
    t, n = 700, 30
    sectors = np.arange(n) % 4
    r = (0.4 * rng.standard_normal((t, 1)) + 0.5 * rng.standard_normal((t, 4))[:, sectors]
         + rng.standard_normal((t, n)))
    returns = pd.DataFrame(r, index=pd.bdate_range("2015-01-01", periods=t),
                           columns=[f"S{i}" for i in range(n)])
    layout = StableLayout()
    positions = [layout.step(minimum_spanning_tree(wc.corr, wc.tickers), wc.tickers)
                 for wc in rolling_correlations(returns, 250)]
    extent = np.mean([np.ptp(p, axis=0).max() for p in positions])
    moves = [np.linalg.norm(b - a, axis=1).mean() for a, b in zip(positions, positions[1:])]
    # A random re-layout would move nodes by roughly half the extent; we require < 3 %.
    assert np.median(moves) < 0.03 * extent
    assert np.percentile(moves, 95) < 0.10 * extent


def test_layout_is_deterministic():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    assert np.allclose(StableLayout().step(tree, tickers), StableLayout().step(tree, tickers))


def test_new_listing_is_placed_near_its_neighbour():
    corr, tickers = block_correlation(n=20)
    layout = StableLayout()
    sub = tickers[1:]
    layout.step(minimum_spanning_tree(corr[1:, 1:], sub), sub)
    tree = minimum_spanning_tree(corr, tickers)
    pos = layout.step(tree, tickers)
    neighbour = next(iter(tree.neighbors("S0")))
    gap = np.linalg.norm(pos[0] - pos[tickers.index(neighbour)])
    assert gap < 2 * tree["S0"][neighbour]["weight"]


def test_3d_layout_shape_and_better_fit_than_2d():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    target = tree_path_distances(tree, tickers)
    pos2 = StableLayout(dim=2).step(tree, tickers)
    pos3 = StableLayout(dim=3).step(tree, tickers)
    assert pos2.shape == (50, 2) and pos3.shape == (50, 3)
    assert np.allclose(pos3.mean(axis=0), 0.0, atol=1e-9)
    # A third dimension gives more room: tree distances are reproduced at least as well.
    assert stress(pos3, target) < stress(pos2, target)
    assert np.allclose(StableLayout(dim=3).step(tree, tickers), pos3)  # deterministic


def test_3d_layout_is_stable_from_one_day_to_the_next():
    rng = np.random.default_rng(3)
    t, n = 700, 30
    sectors = np.arange(n) % 4
    r = (0.4 * rng.standard_normal((t, 1)) + 0.5 * rng.standard_normal((t, 4))[:, sectors]
         + rng.standard_normal((t, n)))
    returns = pd.DataFrame(r, index=pd.bdate_range("2015-01-01", periods=t),
                           columns=[f"S{i}" for i in range(n)])
    layout = StableLayout(dim=3)
    positions = [layout.step(minimum_spanning_tree(wc.corr, wc.tickers), wc.tickers)
                 for wc in rolling_correlations(returns, 250)]
    extent = np.mean([np.ptp(p, axis=0).max() for p in positions])
    moves = [np.linalg.norm(b - a, axis=1).mean() for a, b in zip(positions, positions[1:])]
    assert np.median(moves) < 0.03 * extent
    assert np.percentile(moves, 95) < 0.10 * extent


def test_new_listing_is_placed_near_its_neighbour_in_3d():
    corr, tickers = block_correlation(n=20)
    layout = StableLayout(dim=3)
    sub = tickers[1:]
    layout.step(minimum_spanning_tree(corr[1:, 1:], sub), sub)
    tree = minimum_spanning_tree(corr, tickers)
    pos = layout.step(tree, tickers)
    neighbour = next(iter(tree.neighbors("S0")))
    assert np.linalg.norm(pos[0] - pos[tickers.index(neighbour)]) < 2 * tree["S0"][neighbour]["weight"]


def test_smacof_reduces_stress():
    corr, tickers = block_correlation()
    tree = minimum_spanning_tree(corr, tickers)
    target = tree_path_distances(tree, tickers)
    rng = np.random.default_rng(0)
    from panic_detector.network import smacof
    x0 = rng.standard_normal((len(tickers), 2))
    assert stress(smacof(target, x0), target) < 0.2 * stress(x0, target)
