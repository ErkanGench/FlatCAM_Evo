"""Select by Size: filter by area / length, Select replaces the selection, Delete is one undo step."""
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString, Point, Polygon, MultiLineString, box

from appEditors import appGeoEditor as geo
from tests.test_geo_editor_join import join_editor
from tests.test_geo_editor_split import qt_application  # noqa: F401  (autouse Qt fixture)


def size_editor(selected_all=True):
    """Editor with: lines of length 1, 3, 10; boxes of area 1, 4, 100; a point."""
    editor, shapes = join_editor([[(0, 0), (1, 0)], [(0, 0), (3, 0)], [(0, 0), (10, 0)]])
    for side in (1, 2, 10):
        shape = geo.DrawToolShape(box(0, 0, side, side))
        editor.storage.insert(shape)
        shapes.append(shape)
    point = geo.DrawToolShape(Point(5, 5))
    editor.storage.insert(point)
    shapes.append(point)
    editor.selected = list(shapes) if selected_all else []
    editor.sync_tree_selection = lambda: geo.AppGeoEditor.sync_tree_selection(editor)
    editor.update_all_vertex_count = lambda: geo.AppGeoEditor.update_all_vertex_count(editor)
    return editor, shapes


def configure(editor, area=None, length=None):
    ui = editor.ui
    ui.size_area_chk.setChecked(area is not None)
    ui.size_length_chk.setChecked(length is not None)
    if area is not None:
        ui.size_min_area_entry.setText(str(area[0]))
        ui.size_max_area_entry.setText(str(area[1]))
    if length is not None:
        ui.size_min_length_entry.setText(str(length[0]))
        ui.size_max_length_entry.setText(str(length[1]))


def last_message(editor):
    return editor.app.inform.emit.call_args.args[0]


def test_function_area_and_length_ranges_are_inclusive_and_typed():
    lines = [geo.DrawToolShape(LineString([(0, 0), (n, 0)])) for n in (1, 3)]
    polys = [geo.DrawToolShape(box(0, 0, n, n)) for n in (1, 2)]
    multi = geo.DrawToolShape(MultiLineString([[(0, 0), (1, 0)], [(0, 1), (2, 1)]]))
    point = geo.DrawToolShape(Point(0, 0))
    allshapes = lines + polys + [multi, point]
    assert geo.shapes_in_size_range(allshapes, (1, 1), None) == [polys[0]]
    assert geo.shapes_in_size_range(allshapes, None, (3, 3)) == [lines[1], multi]
    assert geo.shapes_in_size_range(allshapes, None, None) == []
    assert point not in geo.shapes_in_size_range(allshapes, (0, 1e9), (0, 1e9))


def test_text_style_list_of_polygons_counts_as_polygons():
    text = geo.DrawToolShape([box(0, 0, 1, 1), box(2, 0, 3, 1)])
    mixed = geo.DrawToolShape([box(0, 0, 1, 1), LineString([(0, 0), (1, 0)])])
    assert geo.shapes_in_size_range([text, mixed], (2, 2), None) == [text]


def test_area_filter():
    editor, shapes = size_editor()
    configure(editor, area=(2, 10))
    assert geo.AppGeoEditor.size_filter_matches(editor) == [shapes[4]]


def test_length_filter():
    editor, shapes = size_editor()
    configure(editor, length=(2, 10))
    assert geo.AppGeoEditor.size_filter_matches(editor) == [shapes[1], shapes[2]]


def test_both_filters_combine():
    editor, shapes = size_editor()
    configure(editor, area=(0, 1), length=(0, 1))
    assert geo.AppGeoEditor.size_filter_matches(editor) == [shapes[0], shapes[3]]


def test_empty_result_message_and_selection_cleared():
    editor, shapes = size_editor()
    configure(editor, area=(500, 600))
    assert geo.AppGeoEditor.on_select_by_size(editor) == []
    assert editor.selected == []
    assert last_message(editor) == '0 shapes match'


def test_scope_is_selection_when_present_else_all():
    editor, shapes = size_editor()
    configure(editor, length=(0, 100))
    editor.selected = [shapes[0], shapes[3]]
    assert geo.AppGeoEditor.size_filter_matches(editor) == [shapes[0]]
    editor.selected = []
    assert len(geo.AppGeoEditor.size_filter_matches(editor)) == 3


def test_select_searches_whole_board_so_it_can_widen_the_selection():
    editor, shapes = size_editor(selected_all=False)
    editor.plot_changes = Mock()
    configure(editor, length=(0, 2))
    assert geo.AppGeoEditor.on_select_by_size(editor) == [shapes[0]]
    configure(editor, length=(2, 100))
    assert geo.AppGeoEditor.on_select_by_size(editor) == [shapes[1], shapes[2]]


def test_delete_acts_on_selection_when_present():
    editor, shapes = size_editor(selected_all=False)
    configure(editor, length=(0, 100))
    editor.selected = [shapes[0]]
    assert geo.AppGeoEditor.on_delete_by_size(editor) == [shapes[0]]
    assert shapes[1] in set(editor.storage.get_objects())


def test_select_replaces_selection_tree_and_plot():
    editor, shapes = size_editor(selected_all=False)
    editor.plot_changes = Mock()
    configure(editor, length=(2, 100))
    result = geo.AppGeoEditor.on_select_by_size(editor)
    assert result == [shapes[1], shapes[2]]
    assert editor.selected == result
    assert last_message(editor) == '2 shapes match'
    editor.plot_changes.assert_called_once()
    assert not editor._history_undo


def test_delete_is_one_undo_step():
    editor, shapes = size_editor(selected_all=False)
    configure(editor, area=(0, 5), length=(0, 5))
    assert len(geo.AppGeoEditor.on_delete_by_size(editor)) == 4
    remaining = set(editor.storage.get_objects())
    assert remaining == {shapes[2], shapes[5], shapes[6]}
    assert len(editor._history_undo) == 1
    assert last_message(editor) == '4 shapes deleted'
    assert editor.undo()
    assert set(editor.storage.get_objects()) == set(shapes)
    assert editor.redo()
    assert set(editor.storage.get_objects()) == remaining


def test_delete_without_match_changes_nothing():
    editor, shapes = size_editor(selected_all=False)
    configure(editor, area=(500, 600))
    assert geo.AppGeoEditor.on_delete_by_size(editor) == []
    assert set(editor.storage.get_objects()) == set(shapes)
    assert not editor._history_undo


@pytest.mark.parametrize('low,high', [('abc', '5'), ('1', ''), ('-1', '5'), ('nan', '5'), ('inf', 'inf'), ('5', '1')])
@pytest.mark.parametrize('action', ['on_select_by_size', 'on_delete_by_size'])
def test_invalid_input_warns_and_changes_nothing(action, low, high):
    editor, shapes = size_editor()
    editor.selected = shapes[:2]
    editor.ui.size_area_chk.setChecked(True)
    editor.ui.size_min_area_entry.setText(low)
    editor.ui.size_max_area_entry.setText(high)
    assert getattr(geo.AppGeoEditor, action)(editor) == 'fail'
    assert 'WARNING' in last_message(editor)
    assert editor.selected == shapes[:2]
    assert set(editor.storage.get_objects()) == set(shapes)
    assert not editor._history_undo


def test_no_filter_enabled_warns():
    editor, shapes = size_editor()
    configure(editor)
    assert geo.AppGeoEditor.on_select_by_size(editor) == 'fail'
    assert 'WARNING' in last_message(editor)
    assert editor.selected == shapes
