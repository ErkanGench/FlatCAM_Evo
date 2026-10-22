"""GEO04: shared snap coordinates, explicit acquisition units and cached line segments."""
from types import SimpleNamespace
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import LineString, MultiLineString, Point

from appEditors.appGeoEditor import AppGeoEditor, AppGeoEditorUI, DrawToolShape, FCPath
from tests.test_geo_editor_history import editor_with_history


def snapping_editor(geometry=(), **options):
    editor = editor_with_history([DrawToolShape(geo) for geo in geometry])
    editor.app.call_source = 'geo_editor'
    editor.app.grid_status = lambda: True
    editor.app.ui = SimpleNamespace(grid_gap_link_cb=SimpleNamespace(isChecked=lambda: False))
    editor.ui = SimpleNamespace(snap_type_label=Mock())
    editor.editor_options = dict(grid_snap=False, corner_snap=False, midpoint_snap=False,
                                 segment_snap=False, snap_radius_px=8.0, global_snap_max=0.05,
                                 global_gridx=1.0, global_gridy=1.0)
    editor.editor_options.update(options)
    editor.snap = lambda x, y: AppGeoEditor.snap(editor, x, y)
    return editor


def canvas(scale):
    return SimpleNamespace(translate_coords_2=lambda pos: (pos[0] * scale, pos[1] * scale),
                           translate_coords=lambda pos: (pos[0] / scale, pos[1] / scale))




def test_master_gate_does_not_change_legacy_direct_corner_or_grid_snapping():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], corner_snap=True,
                             midpoint_snap=True, segment_snap=True)
    editor.app.grid_status = lambda: False
    assert editor.snap(0.02, 0.01) == (0, 0)
    assert editor.active_snap_type == 'corner'
    editor.editor_options['grid_snap'] = True
    assert editor.snap(1.1, 1.2) == (1, 1)
    assert editor.active_snap_type == 'grid'
    assert editor._snap_cache is None


def test_midpoint_of_each_polyline_segment():
    editor = snapping_editor([LineString([(0, 0), (10, 0), (10, 10)])], midpoint_snap=True)
    assert editor.snap(5.01, 0.01) == (5, 0)
    assert editor.active_snap_type == 'midpoint'
    assert editor.snap(10.01, 5.01) == (10, 5)


def test_projection_is_clamped_to_segment_not_extended_line():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], segment_snap=True)
    assert editor.snap(3, 0.02) == pytest.approx((3, 0))
    assert editor.active_snap_type == 'segment'
    assert editor.snap(-0.02, 0) == (0, 0)
    assert editor.snap(-1, 0) == (-1, 0)






def test_competition_nearest_wins_and_type_ties_have_stable_priority():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True,
                             segment_snap=True, grid_snap=True)
    assert editor.snap(5, 0.02) == (5, 0)
    assert editor.active_snap_type == 'midpoint'
    assert editor.snap(4.99, 0.02) == pytest.approx((4.99, 0))
    assert editor.active_snap_type == 'segment'
    editor.editor_options['corner_snap'] = True
    assert editor.snap(0, 0.02) == (0, 0)
    assert editor.active_snap_type == 'corner'






@pytest.mark.parametrize('linked', [True, False])
def test_empty_storage_zero_grid_and_existing_corner_behavior(linked):
    editor = snapping_editor(grid_snap=True, corner_snap=True, midpoint_snap=True,
                             segment_snap=True, global_gridx=0, global_gridy=0)
    editor.app.ui.grid_gap_link_cb.isChecked = lambda: linked
    assert editor.snap(0.12, 0.34) == (0.12, 0.34)
    editor.add_shape(DrawToolShape(LineString([(0, 0), (10, 0)])))
    editor.editor_options.update(grid_snap=False)
    assert editor.snap(0.02, 0.01) == (0.02, 0)
    editor.editor_options.update(segment_snap=False)
    assert editor.snap(0.02, 0.01) == (0, 0)
    editor.canvas = canvas(10000)
    assert editor.snap(0.02, 0.01) == (0, 0)  # corner distance is still model units


def test_grid_link_and_grid_corner_competition_regressions():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], grid_snap=True,
                             corner_snap=True, global_gridx=0.1, global_gridy=0.2)
    assert editor.snap(0.14, 0.14) == pytest.approx((0.1, 0.2))
    editor.app.ui.grid_gap_link_cb.isChecked = lambda: True
    assert editor.snap(0.14, 0.14) == pytest.approx((0.1, 0.1))
    assert editor.snap(0.01, 0.01) == (0, 0)


def test_cache_reused_and_invalidated_on_commit_undo_redo_and_reset():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True)
    assert editor.snap(5, 0.01) == (5, 0)
    cached = editor._snap_cache
    editor.storage.get_objects = Mock(wraps=editor.storage.get_objects)
    for _ in range(20):
        assert editor.snap(5, 0.01) == (5, 0)
    editor.storage.get_objects.assert_not_called()
    assert editor._snap_cache is cached
    original = list(editor.storage.get_objects())[0]
    replacement = DrawToolShape(LineString([(20, 0), (30, 0)]))
    editor.replace_shapes(removed=[original], inserted=[replacement])
    assert editor.snap(5, 0.01) == (5, 0.01)
    assert editor.snap(25, 0.01) == (25, 0)
    assert editor.undo()
    assert editor.snap(5, 0.01) == (5, 0)
    assert editor.redo()
    assert editor.snap(5, 0.01) == (5, 0.01)
    editor.reset_history()
    assert editor._snap_cache is None


def test_cache_rollback_and_storage_replacement():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True)
    editor.snap(5, 0.01)
    with pytest.raises(ValueError):
        with editor.history_operation():
            editor.replace_shapes(inserted=[DrawToolShape(LineString([(20, 0), (30, 0)]))])
            editor.snap(25, 0.01)
            raise ValueError('rollback')
    assert editor.snap(25, 0.01) == (25, 0.01)
    editor.storage = AppGeoEditor.make_storage()
    assert editor.snap(5, 0.01) == (5, 0.01)








