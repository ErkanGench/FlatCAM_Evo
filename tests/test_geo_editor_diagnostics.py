"""Selected contour inspection never changes editor geometry or undo/redo."""
from copy import deepcopy
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString, Polygon, GeometryCollection

from appEditors import appGeoEditor as geo
from tests.test_geo_editor_join import join_editor
from tests.test_geo_editor_history import run_worker
from tests.test_geo_editor_split import qt_application


def inspect(editor, tolerance=0):
    return geo.AppGeoEditor.diagnose_selected(editor, tolerance)


def test_open_closed_duplicates_zero_and_self_intersection():
    editor, shapes = join_editor([
        [(0, 0), (1, 0)], [(1, 0), (0, 0)],
        [(3, 0), (4, 0), (4, 1), (3, 0)],
        [(5, 0), (5, 0)], [(6, 0), (7, 1), (6, 1), (7, 0)]])
    report = inspect(editor)
    assert report['duplicate'] == shapes[:2]
    assert report['zero_length'] == [shapes[3]]
    assert shapes[4] in report['invalid']
    assert report['open'] == [shapes[0], shapes[1], shapes[4]]
    assert len(report['endpoints']) == 6
    assert shapes[2] not in report['open']


def test_empty_invalid_polygon_and_nested_geometry():
    editor, shapes = join_editor([[(0, 0), (1, 0)]])
    shapes[0].geo = GeometryCollection([
        LineString(), Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])])
    report = inspect(editor)
    assert report['empty'] == shapes
    assert report['invalid'] == shapes
    assert not report['open']


def test_near_endpoints_use_explicit_tolerance_without_closing_paths():
    editor, shapes = join_editor([[(0, 0), (1, 0)], [(1.05, 0), (2, 0)]])
    assert not inspect(editor, 0)['near_endpoints']
    assert len(inspect(editor, 0.1)['near_endpoints']) == 1
    assert inspect(editor, 0.1)['open'] == shapes
    assert list(shapes[1].geo.coords)[0] == (1.05, 0)


@pytest.mark.parametrize('tolerance', [-1, float('nan'), float('inf'), 'bad', None])
def test_invalid_tolerance_is_rejected(tolerance):
    editor, shapes = join_editor([[(0, 0), (1, 0)]])
    assert inspect(editor, tolerance) == 'fail'
    assert editor.selected == shapes
    assert not editor._history_undo


def test_inspection_preserves_state_history_redo_and_cache():
    editor, shapes = join_editor([[(0, 0), (1, 0)], [(1, 0), (2, 0)]])
    assert editor.apply_path_join(0) != 'fail'
    assert editor.undo()
    undo, redo = list(editor._history_undo), list(editor._history_redo)
    before = [(s.geo.wkb, deepcopy(s.data)) for s in shapes]
    cache = editor._snap_cache = object()
    editor.storage.replace = Mock(wraps=editor.storage.replace)
    inspect(editor, 0.1)
    assert editor.selected == shapes
    assert set(editor.storage.get_objects()) == set(shapes)
    assert [(s.geo.wkb, s.data) for s in shapes] == before
    assert editor._history_undo == undo and editor._history_redo == redo
    assert editor._snap_cache is cache
    editor.storage.replace.assert_not_called()
    assert editor.redo()


def test_visible_action_feedback_tree_and_busy_guard():
    editor, shapes = join_editor([[(0, 0), (1, 0)], [(1.05, 0), (2, 0)]])
    editor.sync_tree_selection = lambda: geo.AppGeoEditor.sync_tree_selection(editor)
    geo.AppGeoEditor.build_ui(editor)
    editor.ui.diagnostics_btn.clicked.connect(lambda: geo.AppGeoEditor.on_diagnostics(editor))
    assert 'current units' in editor.ui.diagnostics_tolerance_entry.toolTip()
    editor.ui.diagnostics_tolerance_entry.setText('0.1')
    editor.submit_worker(Mock(), [])
    assert inspect(editor) == 'fail'
    editor.ui.diagnostics_btn.click()
    assert not editor.ui.diagnostics_result.text()
    run_worker(editor)
    editor.ui.diagnostics_btn.click()
    text = editor.ui.diagnostics_result.text()
    assert 'Open paths (information): 2' in text
    assert 'Near endpoint pairs: 1' in text
    for index, shape in enumerate(shapes):
        assert str(id(shape)) in text
        assert 'Open paths (information)' in editor.ui.tw.topLevelItem(index).toolTip(1)
    assert editor.selected == shapes
    assert not editor._history_undo


def test_unselected_geometry_is_not_inspected():
    editor, shapes = join_editor([[(0, 0), (1, 0)], [(1, 0), (0, 0)]])
    editor.selected = shapes[:1]
    assert not inspect(editor)['duplicate']
    editor.selected = []
    assert inspect(editor) == 'fail'
