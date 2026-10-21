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


@pytest.mark.parametrize('mode', ['midpoint_snap', 'segment_snap'])
@pytest.mark.parametrize('master_enabled', [False, True])
def test_motion_and_click_dispatch_agree_with_grid_master(monkeypatch, mode, master_enabled):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(QtWidgets.QApplication, 'keyboardModifiers',
                        staticmethod(lambda: QtCore.Qt.KeyboardModifier.NoModifier))
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], **{mode: True})
    editor.app.grid_status = lambda: master_enabled
    editor.canvas = canvas(100)
    editor.canvas.cursor_color = '#000000'
    editor.canvas.on_update_text_hud = Mock()
    editor.app.plotcanvas = editor.canvas
    editor.app.geo_editor = editor
    editor.app.app_cursor = Mock()
    editor.app.jump_signal = Mock()
    editor.app.ui.popMenu = SimpleNamespace(mouse_is_panning=False)
    editor.app.ui.rel_position_label = Mock()
    editor.app.ui.update_location_labels = Mock()
    editor.pos = None
    editor.update_utility_geometry = Mock()
    tool = FCPath.__new__(FCPath)
    tool.draw_app, tool.name, tool.points, tool.complete = editor, 'path', [], False
    tool.draw_cursor_data = Mock()
    editor.active_tool = tool
    event = SimpleNamespace(pos=(500, 2), button=1, is_dragging=False)
    expected = (5, 0) if master_enabled else (5, 0.02)

    AppGeoEditor.on_canvas_move(editor, event)
    assert (editor.snap_x, editor.snap_y) == expected
    assert tuple(editor.app.mouse_pos) == expected
    editor.update_utility_geometry.assert_called_once_with(data=expected)
    tool.draw_cursor_data.assert_called_once_with(pos=expected)
    AppGeoEditor.on_canvas_click(editor, event)
    assert tool.points == [expected]
    assert (editor.snap_x, editor.snap_y) == expected
    assert editor.active_snap_type == (mode.removesuffix('_snap') if master_enabled else None)
    if not master_enabled:
        assert editor._snap_cache is None
    assert application is not None


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


@pytest.mark.parametrize('scale', [10, 100, 1000])
def test_pixel_acquisition_tracks_zoom_without_reinterpreting_corner_preference(scale):
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True)
    editor.canvas = canvas(scale)
    assert editor.snap(5, 7 / scale) == (5, 0)
    assert editor.snap_acquisition == 'pixels'
    assert editor.snap(5, 9 / scale) == (5, 9 / scale)
    assert editor.editor_options['global_snap_max'] == 0.05


def test_explicit_compatibility_fallback_and_feedback():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True)
    editor.canvas = SimpleNamespace(translate_coords_2=Mock(side_effect=RuntimeError('no live canvas')))
    assert editor.snap(5, 0.04) == (5, 0)
    assert editor.snap_acquisition == 'world'
    assert 'model units' in editor.ui.snap_type_label.setText.call_args.args[0]
    assert editor.snap(5, 0.06) == (5, 0.06)
    assert editor.active_snap_type is None


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


def test_equal_distance_segments_use_coordinates_not_tree_traversal_order():
    lines = [LineString([(0, 0.02), (10, 0.02)]), LineString([(0, -0.02), (10, -0.02)])]
    for geometry in (lines, list(reversed(lines))):
        editor = snapping_editor(geometry, segment_snap=True)
        assert editor.snap(3, 0) == (3, -0.02)


def test_disabled_modes_and_other_app_context_do_not_acquire_editor_geometry():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])])
    assert editor.snap(5, 0.01) == (5, 0.01)
    editor.editor_options['midpoint_snap'] = True
    editor.app.call_source = 'app'
    assert editor.snap(5, 0.01) == (5, 0.01)


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


def test_worker_owned_mutation_does_not_scan_or_block_mouse_snapping():
    editor = snapping_editor([LineString([(0, 0), (10, 0)])], midpoint_snap=True)
    entered, release = Event(), Event()

    def worker():
        with editor._history_lock:
            entered.set()
            release.wait(5)

    thread = Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(2)
        editor.storage.get_objects = Mock(side_effect=AssertionError('storage is being mutated'))
        assert editor.snap(5, 0.01) == (5, 0.01)
        editor.storage.get_objects.assert_not_called()
    finally:
        release.set()
        thread.join(2)


def test_large_scene_warm_snap_queries_only_local_segments():
    editor = snapping_editor([LineString([(i * 20, 0), (i * 20 + 10, 0)]) for i in range(5000)],
                             midpoint_snap=True, segment_snap=True)
    editor.canvas = canvas(100)
    assert editor.snap(5, 0.01) == (5, 0)
    editor.storage.get_objects = Mock(side_effect=AssertionError('warm snap must not scan scene'))
    editor.canvas.translate_coords_2 = Mock(wraps=editor.canvas.translate_coords_2)
    for _ in range(10):
        assert editor.snap(5, 0.01) == (5, 0)
    assert editor.canvas.translate_coords_2.call_count <= 30
    editor.storage.get_objects.assert_not_called()


def test_multiline_degenerate_segments_and_polygonized_curves_are_only_segments():
    editor = snapping_editor([MultiLineString([[(0, 0), (0, 0), (10, 0)], [(10, 0), (10, 10)]]),
                              Point(50, 50).buffer(1)], midpoint_snap=True, segment_snap=True)
    assert editor.snap(5, 0.01) == (5, 0)
    assert editor.snap(50, 50) == (50, 50)
    assert editor.active_snap_type is None


def test_ui_modes_are_opt_in_and_document_acquisition_and_priority():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ui = AppGeoEditorUI(SimpleNamespace(decimals=4, app_units='MM', resource_location=''))
    assert not ui.midpoint_snap_cb.isChecked()
    assert not ui.segment_snap_cb.isChecked()
    assert ui.snap_radius_entry.get_value() == 8
    assert 'global_snap_max' in ui.snap_radius_entry.toolTip()
    assert 'corner' in ui.snap_type_label.toolTip().lower()
    assert application is not None
