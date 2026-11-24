import numpy as np
import pytest

from panic_detector.ui.network_view3d import depth_brightness, pick_node, project_points


def test_projection_maps_ndc_corners_to_screen_corners():
    mvp = np.eye(4)  # world == normalised device coordinates
    pts = np.array([[-1.0, 1.0, 0.0], [1.0, -1.0, 0.0], [0.0, 0.0, 0.0]])
    screen, depth = project_points(mvp, pts, width=800, height=600)
    assert np.allclose(screen[0], [0, 0])        # top-left (screen y points down)
    assert np.allclose(screen[1], [800, 600])    # bottom-right
    assert np.allclose(screen[2], [400, 300])    # centre
    assert np.allclose(depth, 1.0)


def test_perspective_divide():
    mvp = np.eye(4)
    mvp[3] = [0, 0, 1, 0]  # w = z: farther points shrink towards the centre
    screen, depth = project_points(mvp, np.array([[1.0, 0.0, 2.0], [1.0, 0.0, 4.0]]), 200, 200)
    assert screen[0, 0] == pytest.approx(150) and screen[1, 0] == pytest.approx(125)
    assert list(depth) == [2.0, 4.0]


def test_pick_hits_bubble_and_prefers_the_nearest():
    screen = np.array([[100.0, 100.0], [104.0, 100.0], [300.0, 300.0]])
    depth = np.array([5.0, 2.0, 1.0])
    sizes = np.array([20.0, 20.0, 10.0])
    assert pick_node(screen, depth, sizes, (102, 100)) == 1      # overlap: nearer node (depth 2) wins
    assert pick_node(screen, depth, sizes, (300, 309)) == 2      # within radius 5 + 4 px tolerance
    assert pick_node(screen, depth, sizes, (300, 311)) is None   # just outside
    assert pick_node(screen, np.array([5.0, 2.0, -1.0]), sizes, (300, 300)) is None  # behind camera


def test_depth_brightness_dims_far_nodes():
    pts = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 5.0], [0.0, 0.0, 10.0]])
    b = depth_brightness(pts, camera=np.array([0.0, 0.0, -10.0]))
    assert b[0] == pytest.approx(1.0) and b[2] == pytest.approx(0.5)
    assert b[0] > b[1] > b[2]


def test_3d_view_in_a_real_window(qtbot, dashboard_data):
    from panic_detector.ui import theme
    from panic_detector.ui.main_window import MainWindow
    from panic_detector.ui.network_view3d import NetworkView3D, opengl_available
    from panic_detector.ui.state import AppState

    if not opengl_available():
        pytest.skip("no desktop OpenGL context on this platform (e.g. headless test run)")
    theme.configure_pyqtgraph()
    state = AppState(dashboard_data, 60, "en")
    w = MainWindow(state, network_view="3d")
    qtbot.addWidget(w)
    w.show()
    view = w.network
    assert isinstance(view, NetworkView3D)
    state.set_index(120)
    qtbot.waitUntil(lambda: np.allclose(view.display, view.target), timeout=3000)
    assert view.display.shape == (len(view.tickers), 3)
    # Clicking exactly on a projected node selects it.
    screen, _ = project_points(view.view.mvp(), view.display, view.view.width(), view.view.height())
    got = []
    view.node_clicked.connect(got.append)
    from PySide6.QtCore import QPointF
    k = int(np.argmax(view.sizes))
    view._clicked(QPointF(*screen[k]))
    assert got and got[0] in view.tickers
    # ...which opens the company card and highlights the bubble.
    assert state.selected == got[0] and view.card.isVisible()
    assert len(view.sel_glow.pos) == 1

    # 2D / 3D switch: the hidden view pauses, the shown one catches up with the date.
    w.view_buttons["2d"].click()
    assert w.network is w.network_2d and w.network_stack.currentWidget() is w.network_2d
    frozen = view.target.copy()
    state.set_index(200)
    assert np.allclose(view.target, frozen)                   # 3-D did not update while hidden
    assert len(w.network_2d.tickers) == len(w.network_2d.target)
    assert w.network_2d.card.isVisible()                      # the selection follows to 2-D
    w.view_buttons["3d"].click()
    assert w.network is view
    assert np.allclose(view.target, state.current.snapshot(200).positions3d)  # caught up
