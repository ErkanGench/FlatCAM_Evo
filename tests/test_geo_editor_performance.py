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




def test_buffer_accepts_multiline_sources():
    shape = DrawToolShape(MultiLineString([[(0, 0), (1, 0)], [(0, 2), (1, 2)]]))
    editor = batch_editor([shape], selected=[shape])
    editor.app.options.update({'geometry_circle_steps_mode': 'fixed', 'geometry_circle_steps': 32})

    BufferSelectionTool.buffer(SimpleNamespace(app=editor.app, draw_app=editor), 0.1, 'round')

    assert len(list(editor.storage.get_objects())) == 3
    editor.storage.replace.assert_called_once()




















def test_batch_translation_preserves_mixed_dimensions_and_none():
    line_2d = LineString([(0, 0), (1, 1)])
    line_3d = LineString([(0, 0, 7), (1, 1, 8)])

    result = translate_geometry([line_2d, None, line_3d], 2, 3)

    assert list(result[0].coords) == [(2, 3), (3, 4)]
    assert result[1] is None
    assert list(result[2].coords) == [(2, 3, 7), (3, 4, 8)]
    assert list(translate_geometry(line_3d, 2, 3).coords) == [(2, 3, 7), (3, 4, 8)]




def test_buffer_follows_the_adaptive_circle_preference():
    counts = {}
    for mode, distance in (('adaptive', 0.05), ('adaptive', 5.0), ('fixed', 0.05), ('fixed', 5.0)):
        shape = DrawToolShape(LineString([(0, 0), (1, 0)]))
        editor = batch_editor([shape], selected=[shape])
        editor.app.options.update({'geometry_circle_steps_mode': mode, 'geometry_circle_steps': 32})
        BufferSelectionTool.buffer(SimpleNamespace(app=editor.app, draw_app=editor), distance, 'round')
        counts[(mode, distance)] = max(len(s.geo.coords) for s in editor.storage.get_objects()
                                       if s.geo.geom_type in ('LinearRing', 'LineString'))

    assert counts[('adaptive', 0.05)] < counts[('adaptive', 5.0)]
    assert counts[('fixed', 0.05)] == counts[('fixed', 5.0)]
