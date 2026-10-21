"""Vertex edits with an address and vertex drags go through apply_vertex_edit: 1 drag is 1 Undo step."""
import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import BufferJoinStyle
from shapely.geometry import MultiPolygon, Polygon, box

from appEditors.appGeoEditor import AppGeoEditor, AppGeoEditorUI
from appEditors.vertex_ops import circle_center, find_arcs, vertex_grips
from tests.test_geo_editor_vertices import vertex_editor


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_address_edits_a_hole_with_one_undo_step():
    hole = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
    editor, original = vertex_editor(Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [hole]))
    assert editor.apply_vertex_edit('move', (0, 1, 0), (1.5, 0.5)) != 'fail'
    assert list(editor.selected[0].geo.interiors[0].coords)[0] == (1.5, 0.5)
    assert editor.undo()
    assert editor.selected == [original]


def test_address_edits_one_part_of_a_multipolygon():
    editor, original = vertex_editor(MultiPolygon([box(0, 0, 1, 1), box(3, 3, 4, 4)]))
    assert editor.apply_vertex_edit('move', (1, 0, 0), (4.5, 3)) != 'fail'
    result = editor.selected[0].geo
    assert result.geoms[0].equals_exact(original.geo.geoms[0], 0.0)
    assert (4.5, 3) in list(result.geoms[1].exterior.coords)


def test_insert_off_segment_only_without_the_segment_rule():
    editor, original = vertex_editor(Polygon([(0, 0), (4, 0), (4, 4), (0, 4)]))
    assert editor.apply_vertex_edit('insert', (0, 0, 0), (2, -1)) == 'fail'
    assert editor.apply_vertex_edit('insert', (0, 0, 0), (2, -1), on_segment=False) != 'fail'
    assert (2, -1) in list(editor.selected[0].geo.exterior.coords)


from appEditors.vertex_grips import VertexGrips
from tests.test_vertex_grips import FakeCollection

PIXEL = 0.01


def drag_editor(geometry):
    """A history editor with real apply_vertex_edit, real VertexGrips and a VisPy-like 4-value translate_coords."""
    editor, original = vertex_editor(geometry)
    editor.active_tool = SimpleNamespace(name='select')
    editor.canvas = SimpleNamespace(pixel_size=lambda: PIXEL, translate_coords=lambda pos: (pos[0], pos[1], 0, 1))
    editor.tool_shape = FakeCollection()
    editor.get_draw_color = lambda: '#00000080'
    editor.get_sel_color = lambda: '#0000FF80'
    editor.reject_busy = lambda: AppGeoEditor.reject_busy(editor)
    editor.snap = lambda x, y: (x, y)
    editor.app.grid_status = lambda: False
    editor.app.plotcanvas = SimpleNamespace(new_shape_collection=lambda layers: FakeCollection())
    editor.vertex_grips = VertexGrips(editor)
    editor.vertex_grips.sync()
    return editor, original


def test_one_drag_is_one_undo_step():
    editor, original = drag_editor(box(0, 0, 4, 4))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (4, 0), QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), (5, -1))
    assert grips.release((20, 0), (5, -1))
    assert (5, -1) in list(editor.selected[0].geo.exterior.coords)
    assert len(editor._history_undo) == 1
    assert grips.shape is editor.selected[0]  # plot_changes() ran sync(): grips on the new shape
    assert editor.undo()
    assert editor.selected == [original]


def test_invalid_drag_does_not_change_the_shape():
    editor, original = drag_editor(box(0, 0, 4, 4))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (4, 0), QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), (0, 4))  # across the square: self-intersection
    assert grips.release((20, 0), (0, 4))
    assert editor.selected == [original]
    assert not editor._history_undo
    assert editor.app.inform.emit.called


def test_canvas_click_hook_gives_the_press_to_the_grips():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock(press=Mock(return_value=True))
    event = SimpleNamespace(pos=(4, 0), button=1)
    assert AppGeoEditor.on_canvas_click(editor, event) is None
    editor.vertex_grips.press.assert_called_once()
    assert editor.press_pos_raw == (4, 0)


def test_canvas_click_release_hook_gives_the_release_to_the_grips():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock(release=Mock(return_value=True))
    editor.press_pos_raw, editor.press_pos_screen = (4, 0), (4, 0)
    event = SimpleNamespace(pos=(5, 0), button=1)
    assert AppGeoEditor.on_canvas_click_release(editor, event) is None
    editor.vertex_grips.release.assert_called_once()
    assert editor.press_pos_raw is None and editor.press_pos_screen is None


def test_right_button_press_cancels_the_drag():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock()
    editor.app.ui = SimpleNamespace(rel_position_label=Mock(), popMenu=SimpleNamespace(mouse_is_panning=False))
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(4, 0), button=2))
    editor.vertex_grips.cancel.assert_called_once()


def test_dialog_edits_a_hole_through_part_and_ring_fields(monkeypatch):
    hole = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
    editor, original = vertex_editor(Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [hole]))
    editor.decimals = 4
    app = SimpleNamespace(decimals=4, app_units='mm', resource_location='', on_editing_finished=Mock())
    editor.ui = AppGeoEditorUI(app)
    editor.ui.vertex_edit_btn.clicked.connect(lambda: AppGeoEditor.on_edit_vertices(editor))

    def exercise(dialog):
        part = dialog.findChild(QtWidgets.QSpinBox, 'vertex_part')
        ring = dialog.findChild(QtWidgets.QSpinBox, 'vertex_ring')
        index = dialog.findChild(QtWidgets.QSpinBox, 'vertex_index')
        x = dialog.findChild(QtWidgets.QLineEdit, 'vertex_x')
        y = dialog.findChild(QtWidgets.QLineEdit, 'vertex_y')
        assert part.maximum() == 0 and ring.maximum() == 1
        ring.setValue(1)
        assert float(x.text()) == 1 and float(y.text()) == 1
        x.setText('1.5')
        y.setText('0.5')
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert list(editor.selected[0].geo.interiors[0].coords)[0] == (1.5, 0.5)
        dialog.reject()
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, 'exec', exercise)
    editor.ui.vertex_edit_btn.click()
    assert editor.undo()
    assert editor.selected == [original]


ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)


def on_some_arc(ring, point):
    """True if point is on the circle of 1 of the arcs of the closed ring."""
    vertices = list(ring.coords)[:-1]
    for arc in find_arcs(vertices, True):
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        if abs(math.dist(center, point) - math.dist(center, vertices[arc.start])) < 1e-9:
            return True
    return False


def test_arc_bend_is_one_undo_step_and_uses_the_circle_steps():
    editor, original = vertex_editor(ROUNDED)
    editor.app.options['geometry_circle_steps'] = 8
    kind, address, middle = next(grip for grip in vertex_grips(ROUNDED) if grip[0] == 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert editor.apply_vertex_edit('arc_mid', address, cursor, on_segment=False) != 'fail'
    result = editor.selected[0].geo
    assert on_some_arc(result.exterior, cursor)
    assert len(result.exterior.coords) < len(ROUNDED.exterior.coords)   # 8 steps: the bent arc has few segments
    assert len(editor._history_undo) == 1
    assert editor.undo()
    assert editor.selected == [original]


def test_arc_middle_drag_through_the_real_editor_is_one_undo_step():
    editor, original = drag_editor(ROUNDED)
    grips = editor.vertex_grips
    kind, address, middle = next(grip for grip in grips.grips if grip[0] == 'arc_mid')
    cursor = (middle[0] - 0.2, middle[1] - 0.2)
    assert grips.press((0, 0), middle, QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), cursor)
    assert grips.release((20, 0), cursor)
    assert on_some_arc(editor.selected[0].geo.exterior, cursor)
    assert len(editor._history_undo) == 1
    assert grips.shape is editor.selected[0]
    assert sum(1 for grip in grips.grips if grip[0] == 'arc_mid') == 4   # the bent corner is still 1 arc
    assert editor.undo()
    assert editor.selected == [original]