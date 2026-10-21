"""Excellon selection and local edits retain unchanged canvas buffers."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch
from time import perf_counter

from PyQt6 import QtWidgets

from appGUI.VisPyVisuals import ShapeCollectionVisual
from appEditors.appExcEditor import AppExcEditor, AppExcEditorUI
from test_exc_editor_history import drill, scene
from test_exc_editor_snapping import snapping_scene
from test_geo_editor_delete_plot import FakeCollection


def render_scene(count=2):
    editor, first, slot = scene()
    if count > 2:
        editor.storage_dict[1.0].insert_many(drill(index * 2) for index in range(2, count))
    editor.shapes = FakeCollection()
    editor.shapes.update_color = Mock()
    editor.tolerance = 0.001
    editor.get_draw_color = lambda: '#112233FF'
    editor.get_sel_color = lambda: '#AABBCCFF'
    for name in ('plot_shape', 'plot_all'):
        setattr(editor, name, MethodType(getattr(AppExcEditor, name), editor))
    return editor, first, slot


def additions(editor):
    return sum(call[0] == 'add' for call in editor.shapes.calls)


def test_render_selection_and_local_edit_reuse_unchanged_keys():
    editor, first, slot = render_scene()
    editor.plot_all()
    original_keys = dict(editor.shapes.data)
    initial = additions(editor)
    editor.selected = [slot]
    editor.plot_all()
    assert additions(editor) == initial
    assert editor.shapes.data == original_keys
    editor.shapes.update_color.assert_called()
    new = drill(20)
    editor.storage_dict[1.0].insert(new)
    editor.plot_all()
    assert additions(editor) == initial + 2
    editor.storage_dict[1.0].remove(new)
    editor.plot_all()
    assert additions(editor) == initial + 2
    assert set(editor.shapes.data) == set(original_keys)
    editor.shapes.clear()
    editor.plot_all()
    assert additions(editor) == initial * 2 + 2


@patch('appGUI.VisPyVisuals.set_state')
def test_real_collection_buffers_and_colors_survive_selection_and_replacement(set_state):
    editor, first, slot = render_scene()
    editor.shapes = ShapeCollectionVisual(layers=1, pool=None,
                                          fcoptions={'global_graphic_engine_3d_no_mp': True})
    editor.plot_all()
    buffers = {key: value['line_pts'] for key, value in editor.shapes.data.items()}
    editor.selected = [slot]
    editor.plot_all()
    for key, points in buffers.items():
        assert editor.shapes.data[key]['line_pts'] is points
    assert {entry['color'] for entry in editor.shapes.data.values()} == {'#112233FF', '#AABBCCFF'}
    editor.storage_dict[1.0].remove(slot)
    editor.plot_all()
    assert all(entry['color'] == '#112233FF' for entry in editor.shapes.data.values())


def test_inspector_reuses_measurements_and_table_items_until_storage_or_filter_changes():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor, first, slot = scene()
    editor.ui = AppExcEditorUI(SimpleNamespace(decimals=4, app_units='MM', resource_location='assets/resources'))
    with patch.object(editor, 'filter_features', wraps=editor.filter_features) as measure:
        editor.refresh_feature_table()
        item = editor.ui.feature_table.item(0, 0)
        editor.selected = [slot]
        editor.refresh_feature_table()
        assert measure.call_count == 1
        assert editor.ui.feature_table.item(0, 0) is item
        assert editor.ui.feature_table.item(1, 0).isSelected()
        editor.storage_dict[1.0].insert(drill(20))
        editor.refresh_feature_table()
        assert measure.call_count == 2
        assert editor.ui.feature_table.rowCount() == 3
        editor.ui.feature_kind.setCurrentIndex(2)
        editor.refresh_feature_table()
        assert measure.call_count == 3
        assert editor.ui.feature_table.rowCount() == 1


def test_representative_retained_vs_cold_workload():
    editor, first, slot = render_scene(2000)
    start = perf_counter()
    editor.plot_all()
    cold = perf_counter() - start
    initial = additions(editor)
    start = perf_counter()
    for selected in ([slot], [first], []):
        editor.selected = selected
        editor.plot_all()
    warm = (perf_counter() - start) / 3
    assert additions(editor) == initial
    print('2000 features: cold %.6fs, retained selection mean %.6fs; geometry additions %d -> %d' %
          (cold, warm, initial, additions(editor)))


def test_external_clear_and_same_sized_repopulation_does_not_alias_owned_keys():
    editor, first, slot = render_scene()
    editor.plot_all()
    initial = additions(editor)
    count = len(editor.shapes.data)
    editor.shapes.clear()
    for index in range(count):
        editor.shapes.add(shape='foreign')
    editor.plot_all()
    assert additions(editor) == initial * 2 + count
    assert 'foreign' not in editor.shapes.items


def test_snap_index_tracks_direct_storage_mutation_without_mouse_move_scans():
    editor, first, slot = snapping_scene()
    assert editor.snap(4.01, 0) == (4, 0)
    original = editor._exc_snap_index
    editor.storage_dict[1.0].remove(slot)
    assert editor.snap(4.01, 0) == (4.01, 0)
    assert editor._exc_snap_index is not original


@patch('appGUI.VisPyVisuals.set_state')
def test_real_buffer_workload_replacement_only_builds_changed_outline(set_state):
    editor, first, slot = render_scene(1000)
    editor.shapes = ShapeCollectionVisual(layers=1, pool=None,
                                          fcoptions={'global_graphic_engine_3d_no_mp': True})
    with patch.object(editor.shapes, 'add', wraps=editor.shapes.add) as add:
        start = perf_counter()
        editor.plot_all()
        cold = perf_counter() - start
        initial = add.call_count
        buffers = {key: value['line_pts'] for key, value in editor.shapes.data.items()}
        editor.selected = [slot]
        start = perf_counter()
        editor.plot_all()
        warm = perf_counter() - start
        assert add.call_count == initial
        editor.storage_dict[1.0].replace(removed=[first], inserted=[drill(3000)])
        editor.plot_all()
        assert add.call_count == initial + 2
        assert sum(editor.shapes.data[key]['line_pts'] is points for key, points in buffers.items()
                   if key in editor.shapes.data) == initial - 2
        print('1000 real-buffer features: cold %.6fs, retained selection %.6fs; replacement adds 2/%d outlines' %
              (cold, warm, initial))
