import numpy as np
import pytest

# The synthetic `dashboard_data` fixture lives in conftest.py (shared with test_network3d.py).


@pytest.fixture
def window(qtbot, dashboard_data):
    from panic_detector.ui import theme
    from panic_detector.ui.main_window import MainWindow
    from panic_detector.ui.state import AppState

    theme.configure_pyqtgraph()
    state = AppState(dashboard_data, 60, "en")
    w = MainWindow(state, network_view="2d")
    qtbot.addWidget(w)
    w.show()
    return w


def test_window_opens_with_translated_title(window):
    assert window.title.text() == window.state.tr("app.title")
    assert window.windowTitle() == "MARKET PANIC DETECTOR"


def test_date_change_updates_kpis_and_cursors(window):
    state = window.state
    state.set_index(30)
    assert window.kpis.date.value.text() == f"{state.current.dates[30]:%Y-%m-%d}"
    assert window.timeline.slider.value() == 30
    assert window.corr_chart.cursor.value() == pytest.approx(state.current.x[30])
    assert window.prices.cursor.value() == pytest.approx(state.current.x[30])
    expected = f"{state.current.metrics['mean_corr'].iloc[30]:.3f}"
    assert window.kpis.corr.value.text() == expected


def test_change_shows_arrow_with_colour(window):
    window.state.set_index(100)
    html = window.kpis.corr.sub.text()
    assert ("▲" in html) or ("▼" in html) or ("■" in html)


def test_slider_moves_the_date(window):
    window.timeline.slider.setValue(42)
    assert window.state.index == 42


def test_playback_advances(qtbot, window):
    state = window.state
    state.set_index(0)
    window.timeline.toggle()
    qtbot.waitUntil(lambda: state.index >= 3, timeout=3000)
    window.timeline.toggle()
    assert not window.timeline.timer.isActive()


def test_window_switch_keeps_the_date(window):
    state = window.state
    state.set_index(len(state.current) - 50)
    date = state.current.dates[state.index]
    state.set_window(250)
    assert state.current.window == 250
    assert state.current.dates[state.index] == date
    assert window.window_buttons[250].isChecked()


def test_network_has_n_minus_one_edges(window):
    snap = window.state.current.snapshot(window.state.index)
    assert len(snap.edges) == len(snap.tickers) - 1


def _index_with_regime(state, regime):
    hits = [k for k, r in enumerate(state.current.metrics["regime"]) if r == regime]
    if not hits:
        pytest.skip(f"no {regime} day in the synthetic data")
    return hits[len(hits) // 2]


def test_links_turn_red_in_panic_only():
    from panic_detector.ui import theme
    from panic_detector.ui.network_view import edge_color

    red = edge_color("panic", 99.0)[0]
    calm = edge_color("calm", 20.0)[0]
    assert red.name().upper() == theme.TAILLIGHT
    assert calm.red() < 200
    tension = edge_color("tension", 75.0)[0]
    assert calm.red() < tension.red() < red.red()  # warms up through TENSION


def test_pulse_gets_faster_with_stress(window):
    view = window.network
    periods = {}
    for regime in ("calm", "tension", "panic"):
        view.regime = regime
        periods[regime] = view.pulse_period()
    assert periods["calm"] == pytest.approx(3.0)  # ~1 breath every 3 s
    assert periods["calm"] > periods["tension"] > periods["panic"]


def test_node_size_grows_with_links():
    from panic_detector.ui.network_view import node_sizes

    sizes = node_sizes(np.array([1, 2, 5, 20]))
    assert list(sizes) == sorted(sizes) and sizes[-1] <= 30


def test_nodes_glide_to_new_positions(qtbot, window):
    state, view = window.state, window.network
    state.set_index(200)
    qtbot.wait(50)
    state.set_index(260)  # 60-day jump: the layout has moved
    assert not np.allclose(view.display, view.target)
    qtbot.waitUntil(lambda: np.allclose(view.display, view.target), timeout=3000)


def test_animations_off_means_instant_and_static(qtbot, window):
    state, view = window.state, window.network
    state.set_animations(False)
    state.set_index(150)
    assert np.allclose(view.display, view.target)
    opacity = view.halo.opacity()
    qtbot.wait(200)
    assert view.halo.opacity() == opacity  # no breathing
    state.set_animations(True)


def test_glitch_only_in_panic_and_with_animations(window):
    state = window.state
    state.set_index(_index_with_regime(state, "panic"))
    assert window.title.glitching and window.kpis.regime.badge.glitching
    state.set_animations(False)
    assert not window.title.glitching and not window.kpis.regime.badge.glitching
    state.set_animations(True)
    calm = [k for k, r in enumerate(state.current.metrics["regime"]) if r != "panic"]
    state.set_index(calm[0])
    assert not window.title.glitching


def test_hover_tooltip_is_translated(window):
    view = window.network
    ticker = view.tickers[0]
    text = view._tip(0, 0, ticker)
    stock = window.state.data.stocks[ticker]
    assert ticker in text and stock.name in text and "Links" in text
    window.state.set_language("fr")
    assert "Liens" in view._tip(0, 0, ticker)
    window.state.set_language("en")


def test_network_labels_do_not_overlap():
    from panic_detector.ui.network_view import spread_labels_2d

    anchors = np.array([[0.0, 0.0], [5.0, 2.0], [10.0, -3.0], [200.0, 0.0]])
    widths = np.array([40.0, 40.0, 40.0, 40.0])
    out = spread_labels_2d(anchors, widths, height_px=15)
    for a in range(4):
        for b in range(a + 1, 4):
            dx, dy = np.abs(out[b] - out[a])
            assert dx >= 40 or dy >= 15 - 1e-9
    assert np.allclose(out[3], anchors[3])  # isolated label untouched


def test_in_place_move_matches_set_data(window):
    from panic_detector.ui.network_view import move_spots

    view = window.network
    new = view.display + 0.5
    assert move_spots(view.nodes, new)
    assert np.allclose(np.c_[view.nodes.data["x"], view.nodes.data["y"]], new)
    assert not move_spots(view.nodes, new[:-1])  # count mismatch -> caller falls back to setData


# ----------------------------------------------------------------------------- languages

def _visible_texts(window) -> list[str]:
    """Every user-facing string currently shown, HTML stripped."""
    import re

    import pyqtgraph as pg
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel

    texts = [window.windowTitle()]
    for w in window.findChildren(QLabel):
        texts.append(w.text())
    for w in window.findChildren(QAbstractButton):
        texts.append(w.text())
    for w in window.findChildren(QComboBox):
        texts += [w.itemText(k) for k in range(w.count())]
    for chart in (window.corr_chart, window.lambda_chart, window.prices, window.network):
        texts += [it.toPlainText() for it in chart.plot.items if isinstance(it, pg.TextItem)]
    view = window.network
    texts += [view._tip(0, 0, t) for t in view.tickers[:5]]
    clean = [re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ") for t in texts]
    return [t for t in clean if t.strip()]


def test_all_strings_and_icons_render_without_boxes(qapp):
    from panic_detector.i18n import LANGUAGES, load_language
    from panic_detector.ui import theme

    if not theme.available_families(theme.CJK_FAMILIES):
        pytest.skip("no Simplified-Chinese font installed on this machine")
    icons = "".join(theme.REGIME_ICONS.values()) + theme.ARROW_UP + theme.ARROW_DOWN + theme.ARROW_FLAT + "●▶❚λ…"
    for code in LANGUAGES:
        text = "".join(load_language(code).values()) + icons
        assert theme.missing_glyphs(text) == set(), code
    # Sanity check that the test can fail: Consolas alone has no Chinese.
    assert "恐" in theme.missing_glyphs("恐慌", ["Consolas"]) or "Consolas" not in theme.available_families(["Consolas"])


@pytest.mark.parametrize("code", ["fr", "zh_CN"])
def test_language_switch_is_live_and_complete(window, code):
    """After switching, no English interface string is left anywhere on screen."""
    from panic_detector.i18n import load_language
    from panic_detector.ui import theme

    state = window.state
    state.set_index(_index_with_regime(state, "panic"))
    en, target = load_language("en"), load_language(code)
    state.set_language(code)
    shown = "\n".join(_visible_texts(window))
    leftovers = [en[k] for k in en if en[k] != target[k] and len(en[k]) > 3
                 and "{" not in en[k] and en[k] in shown]
    assert not leftovers, f"English strings still shown in {code}: {leftovers}"
    assert target["app.title"] in shown and target["regime.panic"] in shown
    if theme.available_families(theme.CJK_FAMILIES):
        assert theme.missing_glyphs(shown) == set()
    state.set_language("en")
    assert en["app.title"] in "\n".join(_visible_texts(window))


def test_no_hardcoded_english_in_chinese_ui(window):
    import re

    state = window.state
    state.set_language("zh_CN")
    word = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
    # Proper nouns stay as they are: tickers, company names, language names.
    names = " ".join(s.name for s in state.data.stocks.values()) + " English Français"
    allowed = set(state.data.stocks) | set(word.findall(names))
    words = {w for t in _visible_texts(window) for w in word.findall(t)}
    state.set_language("en")
    assert words <= allowed, f"untranslated words: {sorted(words - allowed)}"


# ----------------------------------------------------------------------------- company card

def test_clicking_a_bubble_opens_its_card(window):
    view, state = window.network, window.state
    state.set_index(250)
    k = view.tickers.index("AAPL")
    point = view.nodes.points()[k]
    view.nodes.sigClicked.emit(view.nodes, [point], None)  # same signal as a real mouse click
    assert state.selected == "AAPL"
    card = view.card
    assert card.isVisible()
    assert "Apple" in card.title.text()
    assert card.description.text() == state.tr("company.AAPL")
    # Its links are highlighted: two points per tree link touching AAPL.
    links = int((view.edges == k).any(axis=1).sum())
    assert len(view.sel_edges.getData()[0]) == 2 * links
    state.set_selected(None)


def test_card_neighbour_link_escape_and_date(qtbot, window):
    from PySide6.QtCore import Qt

    state, card = window.state, window.network.card
    state.set_index(250)
    state.set_selected("JPM")
    first = card.stats.text()
    neighbour = card.neighbours.text().split("ticker:")[1].split("'")[0]
    card._open_link(f"ticker:{neighbour}")
    assert state.selected == neighbour and neighbour in card.title.text()
    state.set_index(300)
    assert "300" not in first and card.stats.text() != first  # figures follow the date
    qtbot.keyClick(window, Qt.Key.Key_Escape)
    assert state.selected is None and not card.isVisible()


def test_card_is_translated_live(window):
    state, card = window.state, window.network.card
    state.set_selected("NVDA")
    state.set_language("fr")
    assert card.description.text() == state.tr("company.NVDA")
    assert "Bêta" in card.stats.text()
    state.set_language("zh_CN")
    assert "贝塔" in card.stats.text()
    state.set_language("en")
    state.set_selected(None)


@pytest.mark.parametrize("code", ["en", "fr", "zh_CN"])
def test_card_content_is_never_clipped(window, code):
    state, card = window.state, window.network.card
    state.set_index(250)
    state.set_language(code)
    state.set_selected("BRK-B")  # long name and description
    blocks = [card.title, card.sector, card.description, card.stats, card.neighbours]
    assert all(b.wordWrap() for b in blocks)  # nothing may be cut at the card's right edge
    for upper, lower in zip(blocks, blocks[1:]):
        assert upper.geometry().bottom() < lower.geometry().top(), (upper, lower)
        assert lower.height() >= lower.heightForWidth(lower.width()) - 1
    assert card.neighbours.geometry().bottom() <= card.height()
    state.set_selected(None)
    state.set_language("en")


def test_view_switch_falls_back_to_2d_without_opengl(window):
    from panic_detector.ui.network_view import NetworkView

    if window.has_3d:
        pytest.skip("OpenGL available: covered by test_network3d.py")
    assert isinstance(window.network, NetworkView)
    assert window.view_buttons["2d"].isChecked()
    assert not window.view_buttons["3d"].isEnabled()
    assert window.view_buttons["3d"].toolTip() == window.state.tr("controls.no_opengl")
    window.set_network_view("3d")  # asking anyway keeps the 2-D view
    assert window.network is window.network_2d


def test_film_overlay_covers_window_but_lets_clicks_through(window):
    from PySide6.QtCore import Qt

    root = window.centralWidget()
    film = window.film
    assert film.geometry() == root.rect()
    assert film.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    play = window.timeline.play
    centre = play.mapTo(root, play.rect().center())
    assert root.childAt(centre) is play  # the overlay never swallows a click


def test_price_axis_has_no_ticks_after_last_date(window):
    axis = window.prices.plot.getAxis("bottom")
    x0, x1 = window.prices.plot.vb.viewRange()[0]
    assert x1 > axis.last_x  # the view extends past the data (room for labels)...
    ticks = [v for _spacing, vals in axis.tickValues(x0, x1, 800) for v in vals]
    assert ticks and max(ticks) <= axis.last_x  # ...but no year is printed there


def test_end_labels_are_spread_apart():
    from panic_detector.ui.price_chart import spread_labels

    out = spread_labels({"A": 1.0, "B": 1.01, "C": 1.02, "D": 3.0}, min_gap=0.1)
    ys = sorted(out.values())
    assert all(b - a >= 0.1 - 1e-12 for a, b in zip(ys, ys[1:]))
    assert out["D"] == pytest.approx(3.0, abs=0.1)  # far labels barely move


def test_language_switch_retranslates(window):
    window.state.set_language("fr")
    assert window.title.text() == "DÉTECTEUR DE PANIQUE"
    assert "Lecture" in window.timeline.play.text()
    window.state.set_language("en")
