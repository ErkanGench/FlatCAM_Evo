"""Gerber-local snapping, feature selection and range deletion controls."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.ops import unary_union

from appEditors.appGeoEditor import AppGeoEditor
from appEditors.appGerberEditor import AppGerberEditor
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appParsers.ParseGerber import Gerber
from test_editor_save_modes import gerber_stand_in
from test_gerber_editor_pick import aperture, make_editor
from tests.helpers_objects import app, _headless_qt, make_gerber, NATIVE_GBR  # noqa: F401,E402


def snap_editor(shapes):
    editor = make_editor({10: aperture(shapes)}, grid=True)
    editor.app.call_source = 'grb_editor'
    editor.app.grb_editor = editor
    editor.app.geo_editor.app = editor.app
    editor.app.geo_editor.editor_options = dict(
        grid_snap=False, corner_snap=False, global_snap_max=0.05,
        global_gridx=1.0, global_gridy=1.0)
    editor.app.ui.grid_gap_link_cb.isChecked.return_value = False
    editor.canvas = SimpleNamespace(translate_coords_2=lambda p: (p[0] * 100, p[1] * 100),
                                   translate_coords=lambda p: (p[0] / 100, p[1] / 100))
    return editor


def test_follow_corners_flash_centers_multipart_and_grid_competition():
    editor = snap_editor([
        DrawToolShape({'follow': MultiLineString([[(0, 0), (10, 0)], [(10, 0), (10, 10)]])}),
        DrawToolShape({'follow': Point(20, 20)}),
        DrawToolShape({'solid': box(30, 30, 32, 32)})])
    options = editor.app.geo_editor.editor_options
    options['corner_snap'] = True
    assert editor.snap(10.01, 0.01) == (10, 0)
    assert editor.snap(20.01, 20) == (20, 20)
    assert editor.snap(30.01, 30) == (30.01, 30)
    options.update(grid_snap=True, global_gridx=0.1, global_gridy=0.2)
    assert editor.snap(0.14, 0.14) == pytest.approx((0.1, 0.2))
    editor.app.ui.grid_gap_link_cb.isChecked.return_value = True
    assert editor.snap(0.14, 0.14) == pytest.approx((0.1, 0.1))


def test_feature_rows_select_individual_records_and_sync_without_aperture_signal_loops():
    first = DrawToolShape({'solid': box(0, 0, 2, 3), 'follow': Point(1, 1)})
    second = DrawToolShape({'solid': box(5, 0, 9, 3), 'follow': LineString([(5, 0), (9, 0)])})
    editor = make_editor({10: aperture([first, second]), '11': aperture([first])})
    editor.refresh_features()
    table = editor.ui.features_table
    assert table.rowCount() == 3
    table.selectRow(1)
    assert editor.selected == [second]
    assert editor.calls == {'row': 0, 'sel': 0}
    assert 'LINESTRING' in editor.ui.geo_coords_entry.toPlainText() or 'POLYGON' in editor.ui.geo_coords_entry.toPlainText()
    editor.selected = [first]
    editor.update_ui()
    assert {idx.row() for idx in table.selectionModel().selectedRows()} == {0, 2}
    assert len(editor.ui.apertures_table.selectionModel().selectedRows()) == 2


def range_editor():
    line = LineString([(0, 0), (3, 0), (3, 4)])
    first = DrawToolShape({'solid': box(0, 0, 2, 3), 'follow': line})
    second = DrawToolShape({'solid': box(0, 0, 4, 3), 'follow': Point(1, 1)})
    missing = DrawToolShape({'solid': box(0, 0, 2, 3)})
    editor = make_editor({10: aperture([first, missing]), '11': aperture([second])})
    editor.ui.size_area_chk.setChecked(True)
    editor.ui.size_area_min_entry.setText('6')
    editor.ui.size_area_max_entry.setText('6')
    editor.ui.size_length_chk.setChecked(True)
    editor.ui.size_length_min_entry.setText('7')
    editor.ui.size_length_max_entry.setText('7')
    return editor, first, second, missing


def test_size_ranges_are_inclusive_and_follow_length_is_not_solid_perimeter():
    editor, first, second, missing = range_editor()
    editor.ui.size_select_btn.click()
    assert editor.selected == [first]
    editor.selected = []
    editor.ui.size_length_chk.setChecked(False)
    editor.ui.size_length_min_entry.setText('invalid disabled value')
    assert editor.on_select_by_size() == [first, missing]
    editor.selected = [second]
    # Select searches the whole board, not only the current selection
    assert editor.on_select_by_size() == [first, missing]


@pytest.mark.parametrize('field,value', [
    ('size_area_min_entry', 'nan'), ('size_area_min_entry', '7')])
def test_invalid_ranges_do_not_mutate_selection_geometry_or_history(field, value):
    editor, first, second, missing = range_editor()
    editor.selected = [first, second]
    getattr(editor.ui, field).setText(value)
    revision = editor.geometry_revision
    editor.ui.size_delete_btn.click()
    assert editor.selected == [first, second]
    assert editor.storage_dict[10]['geometry'] == [first, missing]
    assert editor.geometry_revision == revision
    assert not editor.history.undo_stack


def test_filtered_delete_is_one_step_with_original_selection_and_aperture_ownership():
    editor, first, second, missing = range_editor()
    editor.selected = [first, second]
    editor.ui.size_delete_btn.click()
    assert editor.storage_dict[10]['geometry'] == [missing]
    assert editor.storage_dict['11']['geometry'] == [second]
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == [first, missing]
    assert editor.selected == [first, second]
    assert editor.redo()
    assert editor.storage_dict[10]['geometry'] == [missing]


def test_length_only_handles_missing_solids_multipart_and_zero_length_flashes():
    follow = MultiLineString([[(0, 0), (3, 0)], [(0, 0), (0, 4)]])
    track = DrawToolShape({'follow': follow})
    flash = DrawToolShape({'follow': Point(4, 4)})
    missing = DrawToolShape({'solid': box(0, 0, 1, 1)})
    editor = make_editor({10: aperture([track, flash, missing])})
    editor.ui.size_length_chk.setChecked(True)
    editor.ui.size_length_min_entry.setText('7')
    editor.ui.size_length_max_entry.setText('7')
    assert editor.on_select_by_size() == [track]
    editor.selected = []
    editor.ui.size_length_min_entry.setText('0')
    editor.ui.size_length_max_entry.setText('0')
    assert editor.on_select_by_size() == [flash]


def test_filtered_delete_save_reparse_after_undo_redo(app):

    source = make_gerber(app, NATIVE_GBR, name='board')
    first = DrawToolShape({'solid': Point(4, 4).buffer(1, 16), 'follow': Point(4, 4)})
    second = DrawToolShape({'solid': Point(8, 4).buffer(1, 16), 'follow': Point(8, 4)})
    editor = make_editor({10: {'type': 'C', 'size': 2, 'geometry': [first, second]}})
    editor.selected = [first]
    editor.ui.size_width_chk.setChecked(True)
    editor.ui.size_width_entry.setText('2')
    editor.ui.size_tolerance_entry.setText('0')
    editor.on_delete_by_size()
    for mode in ('deleted', 'undo', 'redo'):
        if mode == 'undo':
            assert editor.undo()
        elif mode == 'redo':
            assert editor.redo()
        stand_in = gerber_stand_in(app, source, editor.storage_dict)
        stand_in.loaded_as_regions = getattr(editor, 'loaded_as_regions', False)
        AppGerberEditor.build_edited_gerber(stand_in, 'board', editor.storage_dict)
        result = app.custom_signal.emit.call_args.args[0]
        assert 'error' not in result
        parsed = Gerber(app, steps_per_circle=64)
        assert parsed.parse_lines(result['obj'].source_file.splitlines()) is None
        expected = unary_union([shape.geo['solid'] for shape in editor.storage_dict[10]['geometry']])
        assert unary_union(parsed.solid_geometry).hausdorff_distance(expected) < 0.001
