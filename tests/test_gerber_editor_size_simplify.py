"""Gerber size selection and atomic, aperture-preserving batch simplification."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6 import QtWidgets
from shapely.geometry import LineString, Point, Polygon, box

from appEditors.appGerberEditor import SimplifyEditorGrb
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from test_gerber_editor_pick import aperture, make_editor


def size_editor():
    small = DrawToolShape({'solid': box(0, 0, 2, 3)})
    wide = DrawToolShape({'solid': box(0, 0, 4, 3)})
    empty = DrawToolShape({'solid': Polygon()})
    follow = DrawToolShape({'follow': Point(0, 0)})
    editor = make_editor({10: aperture([small, empty]), '11': aperture([wide, follow])})
    editor.ui.size_width_chk.setChecked(True)
    editor.ui.size_width_entry.setText('2')
    editor.ui.size_height_entry.setText('3')
    editor.ui.size_tolerance_entry.setText('0')
    editor.plot_selection = MagicMock()
    return editor, small, wide


def test_size_selection_button_filters_solid_bounds_and_syncs_rows():
    editor, small, wide = size_editor()
    revision = editor.geometry_revision
    editor.ui.size_select_btn.click()
    assert editor.selected == [small]
    assert [row.row() for row in editor.ui.apertures_table.selectionModel().selectedRows()] == [0]
    editor.plot_selection.assert_called_once_with()
    editor.plot_all.assert_not_called()
    assert editor.calls == {'row': 0, 'sel': 0}
    assert editor.geometry_revision == revision


def test_size_filters_combine_and_select_searches_whole_board():
    editor, small, wide = size_editor()
    editor.selected = [wide]
    # Select ignores the current selection, so repeating it never only narrows
    assert editor.on_select_by_size() == [small]
    editor.ui.size_width_entry.setText('4,05')
    editor.ui.size_tolerance_entry.setText('0,1')
    editor.ui.size_height_chk.setChecked(True)
    assert editor.on_select_by_size() == [wide]
    editor.selected = [wide, small]
    editor.ui.size_height_entry.setText('8')
    assert editor.on_select_by_size() == []


def test_disabled_size_filter_is_not_validated_and_height_alone_works():
    editor, small, wide = size_editor()
    editor.ui.size_width_chk.setChecked(False)
    editor.ui.size_width_entry.setText('not a number')
    editor.ui.size_height_chk.setChecked(True)
    assert editor.on_select_by_size() == [small, wide]


@pytest.mark.parametrize('field,value', [
    ('size_width_entry', 'nan'), ('size_width_entry', '-1'),
    ('size_width_entry', 'inf'), ('size_width_entry', ''),
    ('size_tolerance_entry', '-0.1'), ('size_tolerance_entry', 'nan'),
    ('size_tolerance_entry', 'inf'), ('size_tolerance_entry', 'wrong'),
])
def test_invalid_size_input_preserves_selection(field, value):
    editor, small, wide = size_editor()
    editor.selected = [wide]
    getattr(editor.ui, field).setText(value)
    assert editor.on_select_by_size() == 'fail'
    assert editor.selected == [wide]
    editor.plot_selection.assert_not_called()


def test_size_selection_requires_an_explicit_filter():
    editor, small, wide = size_editor()
    editor.ui.size_width_chk.setChecked(False)
    editor.selected = [small]
    assert editor.on_select_by_size() == 'fail'
    assert editor.selected == [small]


def simplify_tool(editor, tolerance=0.1):
    tool = SimplifyEditorGrb.__new__(SimplifyEditorGrb)
    tool.app = editor.app
    tool.draw_app = editor
    tool.ui = SimpleNamespace(geo_tol_entry=MagicMock(), geo_coords_entry=MagicMock(),
                              geo_vertex_entry=MagicMock())
    tool.ui.geo_tol_entry.get_value.return_value = tolerance
    return tool


def run_job(editor):
    job = editor.app.worker_task.emit.call_args.args[0]
    job['fcn'](*job['params'])
    QtWidgets.QApplication.processEvents()


class CountingStorage(list):
    def __init__(self, shapes):
        super().__init__(shapes)
        self.writes = 0

    def __contains__(self, item):
        raise AssertionError('No per-shape storage membership scans')

    def __setitem__(self, key, value):
        self.writes += 1
        return super().__setitem__(key, value)


def test_simplification_batches_storage_preserves_components_metadata_and_selection():
    solid = box(0, 0, 4, 4)
    follow = LineString([(0, 0), (1, 0.01), (2, 0)])
    clear = box(1, 1, 2, 2)
    first = DrawToolShape({'solid': solid, 'follow': follow, 'clear': clear, 'tag': 'keep'})
    second = DrawToolShape({'solid': box(10, 10, 12, 12), 'follow': None})
    untouched = DrawToolShape({'solid': box(20, 20, 22, 22)})
    editor = make_editor({10: aperture([first, untouched]), '11': aperture([second])})
    lists = [CountingStorage([first, untouched]), CountingStorage([second])]
    editor.storage_dict[10]['geometry'], editor.storage_dict['11']['geometry'] = lists
    metadata = [dict(editor.storage_dict[key]) for key in (10, '11')]
    editor.selected = [first, second]
    revision = editor.geometry_revision
    editor.get_pick_index()
    simplify_tool(editor).on_simplification_click()
    run_job(editor)
    assert [storage.writes for storage in lists] == [1, 1]
    assert editor.geometry_revision == revision + 1
    assert editor.is_modified
    assert lists[0][1] is untouched
    assert editor.selected == [lists[0][0], lists[1][0]]
    for key, before, storage in zip((10, '11'), metadata, lists):
        assert editor.storage_dict[key]['geometry'] is storage
        assert {k: v for k, v in editor.storage_dict[key].items() if k != 'geometry'} == {
            k: v for k, v in before.items() if k != 'geometry'}
    for key, geometry in [('solid', solid), ('follow', follow), ('clear', clear)]:
        assert lists[0][0].geo[key].equals(geometry.simplify(0.1))
    assert lists[0][0].geo['tag'] == 'keep'
    assert lists[1][0].geo['follow'] is None
    assert first.geo['follow'] is follow
    editor.plot_all.assert_called_once_with()
    assert editor.calls == {'row': 0, 'sel': 0}
    assert editor.get_pick_index()[1][0][2] is lists[0][0]


def test_simplification_failure_does_not_delete_any_selected_shape():
    first = DrawToolShape({'solid': box(0, 0, 2, 2)})
    bad = MagicMock()
    bad.simplify.side_effect = ValueError('bad geometry')
    second = DrawToolShape({'solid': bad})
    editor = make_editor({10: aperture([first, second])})
    editor.selected = [first, second]
    revision = editor.geometry_revision
    simplify_tool(editor).on_simplification_click()
    run_job(editor)
    assert editor.storage_dict[10]['geometry'] == [first, second]
    assert editor.selected == [first, second]
    assert editor.geometry_revision == revision
    assert not editor.is_modified
    editor.plot_all.assert_not_called()
    editor.app.inform.emit.assert_called()


@pytest.mark.parametrize('tolerance', [-1, float('nan'), float('inf')])
def test_simplification_rejects_invalid_tolerance(tolerance):
    editor = make_editor({10: aperture([DrawToolShape({'solid': box(0, 0, 1, 1)})])})
    editor.selected = list(editor.storage_dict[10]['geometry'])
    simplify_tool(editor, tolerance).on_simplification_click()
    editor.app.worker_task.emit.assert_not_called()


def test_simplification_ignores_unowned_selection_and_rejects_stale_result():
    first = DrawToolShape({'solid': box(0, 0, 2, 2)})
    orphan = DrawToolShape({'solid': box(0, 0, 1, 1)})
    editor = make_editor({10: aperture([first])})
    editor.selected = [orphan]
    simplify_tool(editor).on_simplification_click()
    editor.app.worker_task.emit.assert_not_called()
    editor.selected = [first]
    simplify_tool(editor).on_simplification_click()
    editor.touch_geometry()
    run_job(editor)
    assert editor.storage_dict[10]['geometry'] == [first]
    assert editor.selected == [first]
    editor.plot_all.assert_not_called()


def test_simplification_worker_commits_only_when_gui_processes_the_result():
    first = DrawToolShape({'solid': box(0, 0, 2, 2)})
    editor = make_editor({10: aperture([first])})
    editor.selected = [first]
    simplify_tool(editor).on_simplification_click()
    job = editor.app.worker_task.emit.call_args.args[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(job['fcn'], *job['params']).result(timeout=10)
    assert editor.storage_dict[10]['geometry'] == [first]
    editor.plot_all.assert_not_called()
    QtWidgets.QApplication.processEvents()
    assert editor.storage_dict[10]['geometry'][0] is not first
    editor.plot_all.assert_called_once_with()


def test_simplification_shared_shape_keeps_both_aperture_owners():
    first = DrawToolShape({'solid': box(0, 0, 2, 2)})
    editor = make_editor({10: aperture([first]), '11': aperture([first])})
    editor.selected = [first]
    simplify_tool(editor).on_simplification_click()
    run_job(editor)
    replacement = editor.storage_dict[10]['geometry'][0]
    assert editor.storage_dict['11']['geometry'] == [replacement]
    assert editor.selected == [replacement]
    assert len(editor.ui.apertures_table.selectionModel().selectedRows()) == 2


@pytest.mark.parametrize('change', ['replace_storage', 'append_shape'])
def test_simplification_rejects_changed_storage_before_any_batch_write(change):
    first = DrawToolShape({'solid': box(0, 0, 2, 2)})
    second = DrawToolShape({'solid': box(3, 0, 5, 2)})
    editor = make_editor({10: aperture([first]), '11': aperture([second])})
    editor.selected = [first, second]
    revision = editor.geometry_revision
    simplify_tool(editor).on_simplification_click()
    if change == 'replace_storage':
        editor.storage_dict['11']['geometry'] = [second]
    else:
        editor.storage_dict['11']['geometry'].append(first)
    run_job(editor)
    assert editor.storage_dict[10]['geometry'] == [first]
    assert editor.selected == [first, second]
    assert editor.geometry_revision == revision
    editor.plot_all.assert_not_called()
