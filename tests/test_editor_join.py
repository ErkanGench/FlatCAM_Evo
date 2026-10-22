"""Toolbar Join and continuous Gerber tracks, including bends and legacy click records."""
from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely import LineString, MultiLineString

from appEditors.appGeoEditor import AppGeoEditor
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appEditors.grb_plugins.GrbTrackBend import sweep_parameters
from appGUI.MainGUI import MainGUI
from tests.test_editor_corner import track_tool_with_storage, track_click
from tests.test_gerber_follow_ops import editor_for, track, flash, footprint
from tests.test_gerber_editor_pick import make_select
from tests.test_geo_editor_join import join_editor
from tests.test_vertex_grips import FakeCollection


@pytest.mark.parametrize('coords', [[(0, 0), (5, 0), (5, 5)], [(0, 0), (5, 0), (8, 4)]])
def test_completed_track_is_one_record_and_drags_across_the_bend(coords):
    tool, storage = track_tool_with_storage(5)
    tool.buf_val, tool.steps_per_circle = 1, 16
    for point in coords:
        track_click(tool, point)
    originals = storage[:]
    editor = editor_for(storage)
    editor.active_tool = tool
    editor.last_aperture_selected = 10
    tool.draw_app = editor
    tool.make()
    editor.on_grb_shape_complete()
    result, = editor.storage_dict[10]['geometry']
    assert list(result.geo['follow'].coords) == coords
    assert editor.undo()
    assert editor.storage_dict[10]['geometry'] == originals
    assert editor.redo()
    result, = editor.storage_dict[10]['geometry']
    editor.selected = [result]
    make_select(editor)
    editor.tool_shape = FakeCollection()
    grips = editor.vertex_grips
    assert grips.press((0, 0), (1, 0), QtCore.Qt.KeyboardModifier.NoModifier)
    grips.release((20, 0), (1, 2))
    moved, = editor.storage_dict[10]['geometry']
    assert list(moved.geo['follow'].coords) == [(x, y + 2) for x, y in coords]


@pytest.mark.parametrize('paths', [
    [[(0, 0), (5, 0)], [(5, 0), (8, 4)]],
    [[(0, 0), (5, 0), (8, 4)], [(8, 4), (13, 4), (16, 8)]],
])
def test_join_bent_records_preserves_copper_and_remains_vertex_editable(paths):
    a, b = [track(coords) for coords in paths]
    editor = editor_for([a, b])
    before = footprint(editor)
    assert editor.apply_path_join(0) != 'fail'
    result, = editor.selected
    assert footprint(editor).equals(before)
    assert sweep_parameters(editor, editor.storage_dict[10], result) == (1, 16)
    assert editor.apply_vertex_edit('move', 1, (5, 1)) != 'fail'
    assert editor.undo() and editor.selected == [result]
    assert editor.undo() and editor.storage_dict[10]['geometry'] == [a, b]


def test_join_select_all_handles_old_duplicate_finish_and_unrelated_flash():
    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (5, 5)])
    duplicate = DrawToolShape(dict(b.geo))
    empty = DrawToolShape({'follow': LineString(), 'solid': LineString().buffer(1)})
    pad = flash(30)
    originals = [empty, a, b, duplicate, pad]
    editor = editor_for(originals[:])
    before = footprint(editor)
    assert editor.apply_path_join(0) != 'fail'
    paths = [s for s in editor.storage_dict[10]['geometry']
             if isinstance(s.geo['follow'], LineString) and not s.geo['follow'].is_empty]
    assert len(paths) == 1
    assert list(paths[0].geo['follow'].coords) == [(0, 0), (5, 0), (5, 5)]
    assert pad in editor.storage_dict[10]['geometry']
    assert footprint(editor).symmetric_difference(before).area < 1e-10
    assert editor.undo() and editor.storage_dict[10]['geometry'] == originals


def test_join_does_not_ignore_a_selected_multiline_branch():
    a, b = track([(0, 0), (5, 0)]), track([(5, 0), (10, 0)])
    follow = MultiLineString([[(5, 0), (5, 5)], [(20, 0), (25, 0)]])
    branch = DrawToolShape({'follow': follow, 'solid': follow.buffer(1, 16)})
    originals = [a, b, branch]
    editor = editor_for(originals[:])
    assert editor.apply_path_join(0) == 'fail'
    assert editor.storage_dict[10]['geometry'] == originals
    assert not editor.history.undo_stack


@pytest.mark.parametrize('theme', ['assets/resources', 'assets/resources/dark_resources'])
def test_toolbar_join_actions_run_existing_selection_operations_after_repopulation(theme):
    editor = editor_for([track([(0, 0), (5, 0)]), track([(5, 0), (5, 5)])])
    editor.app.resource_location = theme
    geo, originals = join_editor([[(0, 0), (5, 0)], [(5, 0), (5, 5)]])
    ui = MagicMock()
    ui.app = editor.app
    ui.grb_edit_toolbar = QtWidgets.QToolBar()
    ui.geo_edit_toolbar = QtWidgets.QToolBar()
    editor.app.ui = ui
    geo.app.ui = ui
    geo.tools = {}
    geo.make_callback = lambda name: lambda: None
    geo.on_join_paths = lambda: AppGeoEditor.on_join_paths(geo)
    for _ in range(2):
        MainGUI.populate_toolbars(ui)
        editor.connect_grb_toolbar_signals()
        AppGeoEditor.connect_geo_toolbar_signals(geo)
        for name, toolbar in [('grb_join_btn', ui.grb_edit_toolbar), ('geo_join_btn', ui.geo_edit_toolbar)]:
            action = getattr(ui, name)
            assert action in toolbar.actions()
            assert not action.icon().isNull()
            assert not action.icon().pixmap(32, 32).isNull()
            assert not action.isCheckable()
    ui.grb_join_btn.trigger()
    assert len(editor.selected) == 1
    ui.geo_join_btn.trigger()
    assert len(geo.selected) == 1
    assert len(editor.history.undo_stack) == len(geo._history_undo) == 1
