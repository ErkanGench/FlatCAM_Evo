"""Excellon snaps use a local cached spatial index, never Geometry storage."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString

from appEditors.appExcEditor import AppExcEditor
from appEditors.appGeoEditor import AppGeoEditor
from test_exc_editor_history import scene


def snapping_scene():
    editor, drill, slot = scene()
    slot.exc_slot = ((4, 0), (6, 1))
    slot.exc_slot_geometry = slot.geo
    editor.snap = MethodType(AppExcEditor.snap, editor)
    editor.app.grid_status = lambda: True
    editor.app.geo_editor = SimpleNamespace(editor_options={'global_snap_max': 0.3, 'grid_snap': False},
                                           storage=Mock())
    editor.ui = SimpleNamespace(snap_modes={kind: Mock(isChecked=Mock(return_value=True))
                                           for kind in ('center', 'endpoint', 'midpoint', 'nearest')},
                                snap_result=Mock())
    return editor, drill, slot


def test_cache_reuse_edit_undo_reset_and_grid_priority():
    editor, drill, slot = snapping_scene()
    editor.snap(4, 0)
    tree = editor._exc_snap_index
    storage = editor.storage_dict[1.0]
    original = storage.get_objects
    storage.get_objects = Mock(side_effect=AssertionError('Unexpected mouse-move scan'))
    for _ in range(100):
        assert editor.snap(4.01, 0) == (4, 0)
    assert editor._exc_snap_index is tree
    storage.get_objects = original
    editor.selected = [slot]
    editor.delete_selected()
    assert editor.snap(4.01, 0) == (4.01, 0)
    editor.undo()
    assert editor.snap(4.01, 0) == (4, 0)
    editor.history.reset()
    assert editor._exc_snap_index is None
    options = editor.app.geo_editor.editor_options
    options.update(grid_snap=True, global_gridx=0.1, global_gridy=0.1)
    editor.app.ui = SimpleNamespace(grid_gap_link_cb=Mock(isChecked=Mock(return_value=True)))
    assert editor.snap(4.11, 0) == pytest.approx((4.1, 0))
    assert editor.snap_kind == 'grid'
    editor.app.grid_status = lambda: False
    assert editor.snap(4.01, 0.01) == (4.01, 0.01)
    assert editor.snap_kind is None


@pytest.mark.parametrize('tool_name', ['drill_select', 'slot_add'])
def test_canvas_click_picks_raw_but_places_at_local_snap(tool_name):
    editor, _, _ = snapping_scene()
    editor.active_tool = SimpleNamespace(name=tool_name)
    editor.canvas = SimpleNamespace(translate_coords=lambda point: point)
    editor.on_canvas_click_left_handler = Mock()
    AppExcEditor.on_canvas_click(editor, SimpleNamespace(button=1, pos=(4.01, 0.01)))
    assert editor.clicked_pos == ((4.01, 0.01) if tool_name == 'drill_select' else (4, 0))
    editor.on_canvas_click_left_handler.assert_called_once()
