"""Geometry editor batch edits: real storage and geometry, recording canvas."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
import shapely
from shapely import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, box
from shapely.ops import unary_union

from appEditors.appGeoEditor import AppGeoEditor, FCMove, FCCopy, FCEraser, DrawToolShape, FCCircle, FCRectangle
from appEditors.geo_plugins.GeoBufferPlugin import BufferSelectionTool
from appEditors.geo_plugins.GeoPaintPlugin import PaintOptionsTool
from appEditors.geo_plugins.GeoTransformationPlugin import TransformEditorTool
from camlib import Geometry, translate_geometry
from test_geo_editor_delete_plot import line, selection_editor
from test_geo_editor_copy import copy_tool, radio


def batch_editor(shapes, selected=()):
    editor = selection_editor(shapes, selected=selected)
    editor.app.proc_container = SimpleNamespace(new=lambda *args: nullcontext())
    editor.app.inform = Mock()
    editor.app.inform_shell = Mock()
    editor.app.worker_task = SimpleNamespace(emit=lambda job: job['fcn'](*job['params']))
    editor.build_ui_sig = Mock()
    editor._collect_shape = lambda shape, dest: AppGeoEditor._collect_shape(editor, shape, dest)
    editor.add_shape = lambda shape, **kwargs: AppGeoEditor.add_shape(editor, shape, **kwargs)
    editor.transform_shapes = lambda *args, **kwargs: AppGeoEditor.transform_shapes(editor, *args, **kwargs)
    editor.storage.replace = Mock(wraps=editor.storage.replace)
    editor.flatten = lambda *args, **kwargs: AppGeoEditor.flatten(editor, *args, **kwargs)
    return editor


@pytest.mark.parametrize('method,args', [
    ('on_rotate_action', (30, (0, 0))),
    ('on_flip', ('Y', (0, 0))),
    ('on_skew', ('X', 20, 0, (0, 0))),
    ('on_scale', ('X', 2, 1, (0, 0))),
    ('on_offset', ('X', 100)),
    ('on_buffer_action', (0.2, 1)),
])
def test_transform_commits_and_renders_once(method, args):
    shapes = [line(x) for x in range(10)]
    shapes[0].data['name'] = 'keep this name'
    editor = batch_editor(shapes, selected=shapes[:2])
    tool = SimpleNamespace(app=editor.app, draw_app=editor)

    getattr(TransformEditorTool, method)(tool, *args)

    assert editor.storage.replace.call_count == 1
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)
    assert sum(call[0] == 'add' for call in editor.shapes.calls) == 2
    assert sum(call[0] == 'redraw' for call in editor.shapes.calls) == 1
    assert len(editor.selected) == 2
    assert editor.selected[0].data['name'] == 'keep this name'
    assert editor.selected[0].data['bounds'] == editor.selected[0].geo.bounds
    editor.build_ui_sig.emit.assert_called_once()


def test_transform_refreshes_snap_points_without_leaving_old_points():
    shape = line(0)
    editor = batch_editor([shape], selected=[shape])
    tool = SimpleNamespace(app=editor.app, draw_app=editor)

    TransformEditorTool.on_offset(tool, 'X', 100)

    assert editor.storage.nearest((100, 0))[0] == (100, 0)
    assert editor.storage.nearest((0, 0))[0] == (100, 0)
    assert editor.selected[0].geo.equals(LineString([(100, 0), (100, 1)]))


@pytest.mark.parametrize('tool_class', [FCMove, FCCopy])
def test_move_copy_without_selection_queries_nearest_once(tool_class):
    shapes = [line(x) for x in range(20)]
    editor = batch_editor(shapes)
    editor.app.jump_signal = Mock()
    editor.storage.nearest = Mock(wraps=editor.storage.nearest)
    tool = tool_class.__new__(tool_class)
    tool.draw_app, tool.storage = editor, editor.storage
    tool.has_selection = False
    tool.set_origin = Mock()

    tool.click((0, 0))

    editor.storage.nearest.assert_called_once_with((0, 0))
    assert editor.selected == [shapes[0]]
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)


@pytest.mark.parametrize('mode', ['n', 'a'])
@pytest.mark.parametrize('limit', [1, 30])
def test_copy_final_position_uses_destination_not_preview(mode, limit):
    tool = copy_tool([line(0), line(1)], mode=mode)
    tool.sel_limit = limit
    tool.click((5, 5))
    tool.utility_geometry((6, 6))

    tool.click((8, 9))

    expected = [3, 4] if mode == 'n' else [3, 4, 13, 14, 23, 24]
    assert [shape.geo.bounds[0] for shape in tool.geometry] == expected
    assert all(shape.geo.bounds[1] == 4 for shape in tool.geometry)


def test_large_array_preview_uses_bounding_box():
    tool = copy_tool([line(0)], mode='a')
    tool.copy_tool.ui.array_size_entry = radio(100000)
    tool.origin = (0, 0)
    tool.array_util_geometry = Mock(side_effect=AssertionError('full array built during preview'))

    preview = tool.utility_geometry((1, 2))

    assert preview.geo.bounds == (1, 2, 1, 3)
    tool.array_util_geometry.assert_not_called()


def test_copy_2d_array_uses_relative_offsets():
    tool = copy_tool([line(0)], mode='a')
    ui = tool.copy_tool.ui
    ui.array_type_radio = radio('2D')
    ui.placement_radio = radio('o')
    ui.rows, ui.columns = radio(2), radio(2)
    ui.spacing_rows, ui.spacing_columns = radio(0), radio(0)
    ui.offsetx_entry, ui.offsety_entry = radio(10), radio(20)
    tool.sel_limit = 0
    tool.click((5, 5))
    tool.click((8, 9))

    assert [shape.geo.bounds[:2] for shape in tool.geometry] == [(3, 4), (13, 4), (3, 24), (13, 24)]


@pytest.mark.parametrize('method', ['buffer', 'buffer_int', 'buffer_ext'])
def test_buffer_inserts_results_in_one_batch(method):
    shapes = [DrawToolShape(box(x * 3, 0, x * 3 + 2, 2).exterior) for x in range(5)]
    editor = batch_editor(shapes, selected=shapes)
    editor.app.options['geometry_circle_steps'] = 32
    tool = SimpleNamespace(app=editor.app, draw_app=editor)

    getattr(BufferSelectionTool, method)(tool, 0.1, 'round')

    editor.storage.replace.assert_called_once()
    editor.build_ui_sig.emit.assert_called_once()
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)
    assert len(list(editor.storage.get_objects())) > len(shapes)


def test_buffer_accepts_multiline_sources():
    shape = DrawToolShape(MultiLineString([[(0, 0), (1, 0)], [(0, 2), (1, 2)]]))
    editor = batch_editor([shape], selected=[shape])
    editor.app.options['geometry_circle_steps'] = 32

    BufferSelectionTool.buffer(SimpleNamespace(app=editor.app, draw_app=editor), 0.1, 'round')

    assert len(list(editor.storage.get_objects())) == 3
    editor.storage.replace.assert_called_once()


def test_paint_flattens_multipart_sources_and_commits_once(monkeypatch):
    shape = DrawToolShape(MultiPolygon([box(0, 0, 2, 2), box(4, 0, 6, 2)]))
    editor = batch_editor([shape], selected=[shape])
    editor.app.options['geometry_circle_steps'] = 32
    paths = []

    def clear(editor, polygon, **kwargs):
        x, y = polygon.centroid.coords[0]
        path = LineString([(x - 0.5, y), (x + 0.5, y)])
        paths.append(path)
        return SimpleNamespace(get_objects=lambda: [path])

    monkeypatch.setattr(Geometry, 'clear_polygon_lines', clear)
    tool = SimpleNamespace(app=editor.app, fcdraw=editor)

    PaintOptionsTool.paint(tool, 0.2, 0.1, 0.0, False, False, 'Lines')

    assert len(paths) == 2
    editor.storage.replace.assert_called_once()
    editor.build_ui_sig.emit.assert_called_once()
    added = [s.geo for s in editor.storage.get_objects() if s is not shape]
    assert len(added) == 2
    assert unary_union(added).equals(unary_union(paths))
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)


@pytest.mark.parametrize('method', ['union', 'intersection', 'intersection_2', 'subtract', 'subtract_2', 'cutpath'])
def test_boolean_edits_update_storage_and_canvas_once(method):
    shapes = [DrawToolShape(box(0, 0, 5, 5)), DrawToolShape(box(1, 1, 2, 2)),
              DrawToolShape(box(3, 1, 4, 2))]
    # Difference/intersection_2 must also accept polygons rather than only closed lines.
    editor = batch_editor(shapes, selected=shapes)

    getattr(AppGeoEditor, method)(editor)

    editor.storage.replace.assert_called_once()
    editor.build_ui_sig.emit.assert_called_once()
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)
    assert len(list(editor.storage.get_objects())) > 0


def test_shape_completion_does_not_replot_unchanged_shapes():
    shapes = [line(x) for x in range(10)]
    editor = batch_editor(shapes)
    editor.active_tool = SimpleNamespace(geometry=[line(20)], keeps_direction=True)
    editor.delete_utility_geometry = Mock()
    editor.tool_shape = Mock()

    AppGeoEditor.on_shape_complete(editor)

    assert sum(call[0] == 'add' for call in editor.shapes.calls) == 1
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)


def test_eraser_queries_spatial_candidates_and_refreshes_snapping(monkeypatch):
    target = DrawToolShape(box(0, 0, 10, 10))
    others = [DrawToolShape(box(x, 0, x + 1, 1)) for x in range(20, 120)]
    editor = batch_editor([target] + others, selected=[target])
    tree, refs = AppGeoEditor.get_pick_index(editor)
    query = Mock(wraps=tree.query)
    editor.get_pick_index = Mock(return_value=(SimpleNamespace(query=query), refs))
    editor.delete_utility_geometry = Mock()
    editor.app.jump_signal = Mock()
    eraser = FCEraser.__new__(FCEraser)
    eraser.draw_app, eraser.storage = editor, editor.storage
    eraser.destination = (0, 0)
    eraser.utility_geometry = lambda data: SimpleNamespace(geo=[box(-1, -1, 5, 11)])
    intersects = Mock(wraps=shapely.intersects)
    monkeypatch.setattr(shapely, 'intersects', intersects)

    eraser.make()

    query.assert_called_once()
    assert query.call_args.kwargs['predicate'] == 'intersects'
    intersects.assert_not_called()  # the exact predicate runs inside STRtree, not a Python scene scan
    editor.storage.replace.assert_called_once()
    editor.build_ui_sig.emit.assert_called_once()
    assert len(editor.selected) == 1
    assert editor.selected[0].geo.bounds[0] == pytest.approx(5, abs=1e-6)
    assert editor.storage.nearest((0, 0))[0][0] == pytest.approx(5, abs=1e-6)
    assert all(shape in list(editor.storage.get_objects()) for shape in others)
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)


@pytest.mark.parametrize('tool_class,plugin_name', [(FCCircle, 'circle_tool'), (FCRectangle, 'rect_tool')])
def test_shape_edit_selection_does_not_duplicate_nearest(tool_class, plugin_name, monkeypatch):
    shapes = [line(x) for x in range(20)]
    editor = batch_editor(shapes)
    editor.app.jump_signal = Mock()
    editor.storage.nearest = Mock(wraps=editor.storage.nearest)
    tool = tool_class.__new__(tool_class)
    tool.draw_app, tool.storage = editor, editor.storage
    setattr(tool, plugin_name, SimpleNamespace(ui=SimpleNamespace(x_entry=Mock(), y_entry=Mock())))
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        lambda: QtCore.Qt.KeyboardModifier.ShiftModifier)

    tool.click((0, 0))

    editor.storage.nearest.assert_called_once_with((0, 0))
    assert editor.selected == [shapes[0]]
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)


def test_plot_multipart_and_nested_geometry_keeps_collection_and_layer():
    editor = batch_editor([])
    editor.shapes.add = Mock(wraps=editor.shapes.add)
    geometry = [MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)]),
                [DrawToolShape(LineString([(4, 0), (4, 1)]))]]

    keys = AppGeoEditor.plot_shape(editor, storage=editor.shapes, geometry=geometry, layer=2)

    assert len(keys) == 3
    assert all(call.kwargs['layer'] == 2 for call in editor.shapes.add.call_args_list)


def test_collect_geometry_collection_ignores_points_and_indexes_paths():
    editor = batch_editor([])
    geometry = GeometryCollection([box(0, 0, 1, 1), LineString([(2, 0), (2, 1)]), Point(3, 0)])

    editor.add_shape(geometry)

    assert len(list(editor.storage.get_objects())) == 2
    assert editor.storage.nearest((2, 0))[0] == (2, 0)


def test_circular_array_recomputes_at_the_final_destination():
    tool = copy_tool([line(0)], mode='a')
    tool.copy_tool.ui.array_type_radio = radio('circular')
    tool.copy_tool.ui.array_dir_radio = radio('CCW')
    tool.copy_tool.ui.angle_entry = radio(90)
    tool.click((5, 5))
    tool.utility_geometry((6, 5))

    tool.click((8, 9))

    assert len(tool.geometry) == 3
    for shape, expected in zip(tool.geometry, [(3, 4), (-4, 3), (-3, -4)]):
        assert tuple(shape.geo.coords[0]) == pytest.approx(expected)


def test_copy_preserves_z_coordinates_with_batch_translation():
    shape = DrawToolShape(LineString([(0, 0, 7), (1, 1, 8)]))
    tool = copy_tool([shape])
    tool.click((0, 0))
    tool.click((2, 3))

    assert list(tool.geometry[0].geo.coords) == [(2, 3, 7), (3, 4, 8)]
    assert list(shape.geo.coords) == [(0, 0, 7), (1, 1, 8)]


def test_batch_translation_preserves_mixed_dimensions_and_none():
    line_2d = LineString([(0, 0), (1, 1)])
    line_3d = LineString([(0, 0, 7), (1, 1, 8)])

    result = translate_geometry([line_2d, None, line_3d], 2, 3)

    assert list(result[0].coords) == [(2, 3), (3, 4)]
    assert result[1] is None
    assert list(result[2].coords) == [(2, 3, 7), (3, 4, 8)]
    assert list(translate_geometry(line_3d, 2, 3).coords) == [(2, 3, 7), (3, 4, 8)]


def test_orientation_looks_up_shapes_once_and_batches_the_replacement():
    shapes = [line(x) for x in range(20)]
    ring = DrawToolShape(box(25, 0, 26, 1).exterior)
    shapes.append(ring)
    editor = batch_editor(shapes, selected=shapes)
    editor.ui = SimpleNamespace(tw=SimpleNamespace(selectedItems=lambda: [
        SimpleNamespace(text=lambda column, shape=shape: str(id(shape))) for shape in shapes]))
    editor.shapes_by_tree_id = lambda: AppGeoEditor.shapes_by_tree_id(editor)
    editor.storage.get_objects = Mock(wraps=editor.storage.get_objects)

    AppGeoEditor.on_change_orientation(editor)

    editor.storage.replace.assert_called_once()
    assert editor.storage.get_objects.call_count <= 2  # lookup and incremental plot
    result = list(editor.storage.get_objects())
    assert len(result) == len(shapes)
    for before, after in zip(shapes, result):
        assert list(after.geo.coords) == list(before.geo.coords)[::-1]
    assert not any(call[0] == 'clear' for call in editor.shapes.calls)
