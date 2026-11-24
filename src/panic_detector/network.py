"""Correlation network: Mantegna (1999) minimum spanning tree and a date-to-date stable layout.

Distance d_ij = sqrt(2 (1 - rho_ij)) turns correlations into a metric: 0 for perfectly
correlated stocks, sqrt(2) for uncorrelated ones, 2 for perfectly anti-correlated ones.

Layout (2-D or 3-D): node positions are fitted by stress majorization (SMACOF) to the
weighted path distances of the tree, warm-started from the previous day's positions and
then rotated back onto them (Procrustes). Distances are in absolute units, so the
drawing visibly shrinks when correlations rise.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence

import networkx as nx
import numpy as np


def correlation_distance(corr: np.ndarray) -> np.ndarray:
    return np.sqrt(np.clip(2.0 * (1.0 - corr), 0.0, None))


def minimum_spanning_tree(corr: np.ndarray, tickers: Sequence[str]) -> nx.Graph:
    """MST of the complete graph weighted by correlation distance (Kruskal, networkx).

    Edges carry 'weight' (distance) and 'rho' (correlation).
    """
    n = len(tickers)
    dist = correlation_distance(corr)
    rows, cols = np.triu_indices(n, k=1)
    graph = nx.Graph()
    graph.add_nodes_from(tickers)
    graph.add_edges_from(
        (tickers[i], tickers[j], {"weight": float(dist[i, j]), "rho": float(corr[i, j])})
        for i, j in zip(rows, cols)
    )
    return nx.minimum_spanning_tree(graph, weight="weight", algorithm="kruskal")


def tree_path_distances(tree: nx.Graph, nodes: Sequence[str]) -> np.ndarray:
    """Weighted path lengths between every pair of nodes of the tree."""
    return np.asarray(nx.floyd_warshall_numpy(tree, nodelist=list(nodes), weight="weight"))


def classical_mds(dist: np.ndarray, dim: int = 2) -> np.ndarray:
    """Torgerson embedding in `dim` dimensions, used only to initialise the very first layout."""
    n = len(dist)
    centering = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * centering @ (dist**2) @ centering
    vals, vecs = np.linalg.eigh(b)
    order = np.argsort(vals)[::-1][:dim]
    return vecs[:, order] * np.sqrt(np.clip(vals[order], 1e-12, None))


def stress(x: np.ndarray, dist: np.ndarray) -> float:
    d = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=-1)
    mask = ~np.eye(len(dist), dtype=bool)
    w = 1.0 / dist[mask] ** 2
    return float(np.sum(w * (d[mask] - dist[mask]) ** 2))


def smacof(
    dist: np.ndarray,
    x0: np.ndarray,
    max_iter: int = 300,
    tol: float = 1e-6,
    anchors: np.ndarray | None = None,
    stiffness: float = 0.0,
) -> np.ndarray:
    """Stress majorization with weights 1/d^2 (Gansner, Koren & North 2004).

    With `anchors`, minimises stress + mu * sum_i ||x_i - anchor_i||^2 ("anchored"
    stress, as in dynamic graph drawing), where mu = stiffness * mean node weight.
    This keeps nodes near their previous positions when near-tied tree edges swap.
    """
    n = len(dist)
    target = np.maximum(dist, 1e-9)
    w = 1.0 / target**2
    np.fill_diagonal(w, 0.0)
    v = -w.copy()
    np.fill_diagonal(v, w.sum(axis=1))
    anchored = anchors is not None and stiffness > 0
    if anchored:
        mu = stiffness * float(np.mean(np.diag(v)))
        system = np.linalg.inv(v + mu * np.eye(n))
        pull = mu * anchors
    else:
        system = np.linalg.pinv(v)
    x = x0.astype(float).copy()

    def objective(y: np.ndarray) -> float:
        s = stress(y, target)
        return s + mu * float(np.sum((y - anchors) ** 2)) if anchored else s

    prev = objective(x)
    for _ in range(max_iter):
        d = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=-1)
        np.fill_diagonal(d, 1.0)
        b = -w * target / np.maximum(d, 1e-12)
        np.fill_diagonal(b, 0.0)
        np.fill_diagonal(b, -b.sum(axis=1))
        x = system @ (b @ x + pull) if anchored else system @ b @ x
        cur = objective(x)
        if prev - cur <= tol * max(prev, 1e-12):
            break
        prev = cur
    return x


def procrustes_rotation(x: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Proper rotation (no reflection) that best maps centred x onto centred reference."""
    xc, rc = x - x.mean(axis=0), reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(xc.T @ rc)
    if np.linalg.det(u @ vt) < 0:
        u[:, -1] *= -1
    return u @ vt


def _unit_direction(name: str, dim: int) -> np.ndarray:
    """Deterministic pseudo-random unit vector for a ticker (same on every run)."""
    v = np.random.default_rng(zlib.crc32(name.encode())).standard_normal(dim)
    return v / np.linalg.norm(v)


class StableLayout:
    """Sequential layout of daily trees in 2-D or 3-D, each initialised from the previous day."""

    def __init__(self, max_iter: int = 300, tol: float = 1e-6, stiffness: float = 1.0, dim: int = 2) -> None:
        self.max_iter = max_iter
        self.tol = tol
        self.stiffness = stiffness
        self.dim = dim
        self.previous: dict[str, np.ndarray] = {}

    def _initial_positions(self, tree: nx.Graph, nodes: Sequence[str], dist: np.ndarray) -> np.ndarray:
        if not self.previous:
            return classical_mds(dist, self.dim)
        x0 = np.zeros((len(nodes), self.dim))
        missing = []
        for i, node in enumerate(nodes):
            if node in self.previous:
                x0[i] = self.previous[node]
            else:
                missing.append(i)
        for i in missing:
            # New listing: start next to its closest neighbour already placed.
            neighbours = [nodes.index(nb) for nb in tree.neighbors(nodes[i]) if nb in self.previous]
            anchor = x0[neighbours[0]] if neighbours else x0[[j for j in range(len(nodes)) if j not in missing]].mean(axis=0)
            x0[i] = anchor + 0.3 * _unit_direction(nodes[i], self.dim)
        return x0

    def step(self, tree: nx.Graph, nodes: Sequence[str]) -> np.ndarray:
        nodes = list(nodes)
        dist = tree_path_distances(tree, nodes)
        x0 = self._initial_positions(tree, nodes, dist)
        # Anchor to yesterday's positions (new listings anchor to their start point).
        anchors = x0 if self.previous else None
        x = smacof(dist, x0, self.max_iter, self.tol, anchors=anchors, stiffness=self.stiffness)
        common = [i for i, node in enumerate(nodes) if node in self.previous]
        if len(common) >= 3:
            ref = np.array([self.previous[nodes[i]] for i in common])
            rot = procrustes_rotation(x[common], ref)
            x = (x - x[common].mean(axis=0)) @ rot + ref.mean(axis=0)
        x -= x.mean(axis=0)
        self.previous = {node: x[i] for i, node in enumerate(nodes)}
        return x
