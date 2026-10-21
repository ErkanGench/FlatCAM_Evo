"""Native slot endpoint edits replace wrappers, never polygon vertices."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock, MagicMock
from concurrent.futures import ThreadPoolExecutor

import pytest
from PyQt6 import QtWidgets
from shapely import LineString, Point
from shapely.affinity import scale

from appEditors import appExcEditor as exc
from appEditors.appGeoEditor import AppGeoEditor
from appHandlers.appIO import appIO
from test_exc_editor_history import scene
from test_geo_editor_delete_plot import FakeCollection
from test_unify_characterization import app, _headless_qt, make_same_diameter_excellon, reparse_excellon  # noqa: F401


def endpoint_scene():
    editor, first, slot = scene()
    slot.exc_slot = ((4.0, 0.0), (6.0, 1.0))
    slot.exc_slot_geometry = slot.geo
    editor.selected = [slot]
    editor.delete_utility_geometry = Mock()
    editor.ui = SimpleNamespace()
    for name in ('edit_slot_endpoints', 'on_slot_endpoints_apply', 'load_slot_endpoints'):
        method = getattr(exc.AppExcEditor, name, None)
        assert method is not None, 'Native endpoint editing is missing: ' + name
        setattr(editor, name, MethodType(method, editor))
    return editor, first, slot


def test_endpoint_replacement_preserves_order_width_selection_and_history():
    editor, first, slot = endpoint_scene()
    before_counts = list(editor.slot_points_edit[1.0])
    result = editor.edit_slot_endpoints(slot, ((4, 0), (10, 3)))
    replacement = list(editor.storage_dict[1.0].get_objects())[1]
    assert result != 'fail'
    assert replacement is not slot
    assert replacement.exc_slot == ((4, 0), (10, 3))
    assert replacement.exc_slot_geometry is replacement.geo
    assert replacement.geo.equals(LineString(replacement.exc_slot).buffer(0.5))
    assert editor.selected == [replacement]
    assert list(editor.storage_dict[1.0].get_objects())[0] is first
    assert editor.slot_points_edit[1.0] == before_counts
    assert editor.tool2tooldia == {1: 1.0}
    assert editor.history.revision == 1
    assert len(editor.history.undo_stack) == 1
    editor.replot.assert_called_once()
    assert editor.undo()
    assert editor.selected == [slot]
    assert list(editor.storage_dict[1.0].get_objects()) == [first, slot]
    assert slot.exc_slot_geometry is slot.geo
    assert editor.redo()
    assert editor.selected == [replacement]


@pytest.mark.parametrize('endpoints', [((4, 0), (4, 0)), ((float('nan'), 0), (9, 1)),
                                      ((4, 0), (float('inf'), 2)), ((4,), (9, 1))])
def test_invalid_endpoints_are_atomic(endpoints):
    editor, first, slot = endpoint_scene()
    assert editor.edit_slot_endpoints(slot, endpoints) == 'fail'
    assert list(editor.storage_dict[1.0].get_objects()) == [first, slot]
    assert not editor.history.undo_stack
    assert not editor.is_modified
    editor.replot.assert_not_called()


def test_busy_stale_and_non_native_slots_are_not_edited():
    editor, first, slot = endpoint_scene()
    editor.history.pending = (object(), 0, 0, Mock())
    assert editor.edit_slot_endpoints(slot, ((4, 0), (9, 1))) == 'fail'
    editor.history.pending = None
    assert editor.edit_slot_endpoints(slot, ((4, 0), (9, 1)), expected=(99, 99)) == 'fail'
    slot.exc_slot_geometry = None
    assert editor.edit_slot_endpoints(slot, ((4, 0), (9, 1))) == 'fail'
    assert list(editor.storage_dict[1.0].get_objects()) == [first, slot]


def test_numeric_endpoint_controls_use_the_same_operation():
    editor, first, slot = endpoint_scene()
    editor.ui.slot_endpoint_entries = [Mock() for _ in range(4)]
    editor.load_slot_endpoints()
    for entry, value in zip(editor.ui.slot_endpoint_entries, (4, 0, 6, 1)):
        entry.set_value.assert_called_once_with(value)
    for entry, value in zip(editor.ui.slot_endpoint_entries, (4, 0, 9, 7)):
        entry.get_value.return_value = value
    editor.on_slot_endpoints_apply()
    assert editor.selected[0].exc_slot == ((4, 0), (9, 7))
    assert len(editor.history.undo_stack) == 1
    for entry, value in zip(editor.ui.slot_endpoint_entries, (3, -1, 9, 7)):
        entry.get_value.return_value = value
    editor.on_slot_endpoints_apply()
    assert editor.selected[0].exc_slot == ((3, -1), (9, 7))
    assert len(editor.history.undo_stack) == 2


def test_drag_raw_hit_preview_release_cancel_and_stale_guard():
    editor, first, slot = endpoint_scene()
    tool_type = getattr(exc, 'SlotEndpointEditorExc', None)
    assert tool_type is not None, 'Native endpoint drag tool is missing'
    editor.app.geo_editor = SimpleNamespace(editor_options={'global_snap_max': 0.2})
    tool = tool_type(editor)
    tool.click((6.1, 1.0))
    preview = tool.utility_geometry((9, 5))
    assert preview.geo.equals(LineString([(4, 0), (9, 5)]).buffer(0.5))
    assert list(editor.storage_dict[1.0].get_objects())[1] is slot
    tool.click_release((9, 5))
    assert editor.selected[0].exc_slot == ((4, 0), (9, 5))
    assert editor.history.revision == 1
    tool.click((9, 5))
    tool.clean_up()
    tool.click_release((11, 8))
    assert editor.history.revision == 1
    tool.click((9, 5))
    editor.history.reset()
    tool.click_release((12, 8))
    assert editor.history.revision == 1


def test_canvas_press_keeps_endpoint_hit_test_unsnapped():
    editor, first, slot = endpoint_scene()
    tool_type = getattr(exc, 'SlotEndpointEditorExc', None)
    assert tool_type is not None
    editor.app.geo_editor = SimpleNamespace(editor_options={'global_snap_max': 0.2})
    editor.active_tool = tool_type(editor)
    editor.app.grid_status = lambda: True
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: pos)
    editor.snap = Mock(return_value=(20, 20))
    editor.on_canvas_click_left_handler = lambda: editor.active_tool.click(editor.clicked_pos)
    exc.AppExcEditor.on_canvas_click(editor, SimpleNamespace(button=1, pos=(6.05, 1)))
    assert editor.active_tool.utility_geometry((9, 3)) is not None
    editor.snap.assert_not_called()


def test_real_canvas_move_preview_grid_release_and_invalid_preview_cleanup():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor, first, slot = endpoint_scene()
    editor.ui = exc.AppExcEditorUI(SimpleNamespace(decimals=4, app_units='MM', resource_location='assets/resources'))
    editor.app.geo_editor = SimpleNamespace(editor_options={
        'global_snap_max': 0.2, 'grid_snap': True, 'global_gridx': 0.5, 'global_gridy': 0.5})
    editor.app.options.update(global_cursor_width=1, global_cursor_size=10)
    editor.app.defaults = SimpleNamespace(get=lambda key, default: default, factory_defaults={})
    editor.app.grid_status = lambda: True
    editor.app.plotcanvas = Mock()
    editor.app.plotcanvas.native.hasFocus.return_value = True
    editor.app.app_cursor = Mock()
    editor.app.ui = SimpleNamespace(popMenu=SimpleNamespace(mouse_is_panning=False),
                                    grid_gap_link_cb=Mock(isChecked=lambda: True),
                                    rel_position_label=Mock(), update_location_labels=Mock())
    editor.app.selection_type = None
    editor.canvas = SimpleNamespace(translate_coords=lambda pos: pos)
    editor.tool_shape = FakeCollection()
    editor.get_draw_color = lambda: '#112233FF'
    for name in ('on_canvas_click_left_handler', 'snap', 'update_utility_geometry', 'draw_utility_geometry'):
        setattr(editor, name, MethodType(getattr(exc.AppExcEditor, name), editor))
    editor.active_tool = exc.SlotEndpointEditorExc(editor)
    exc.AppExcEditor.on_canvas_click(editor, SimpleNamespace(button=1, pos=(6.05, 1)))
    event = SimpleNamespace(button=1, pos=(8.21, 4.21), is_dragging=True)
    exc.AppExcEditor.on_canvas_move(editor, event)
    assert editor.snap_kind == 'grid'
    assert editor.app.selection_type is None
    assert editor.tool_shape.items[-1].equals(LineString([(4, 0), (8, 4)]).buffer(0.5))
    assert editor.history.revision == 0
    editor.update_utility_geometry((4, 0))
    assert not editor.tool_shape.items
    exc.AppExcEditor.on_exc_click_release(editor, event)
    assert editor.selected[0].exc_slot == ((4, 0), (8, 4))
    assert editor.history.revision == 1


def test_actual_editor_numeric_menu_toolbar_wiring_and_switch_cleanup():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = MagicMock()
    app.decimals, app.app_units, app.resource_location = 4, 'MM', 'assets/resources'
    app.options = {'global_tolerance': 0.001}
    app.defaults = SimpleNamespace(get=lambda key, default: default, factory_defaults={})
    app.ui.exc_editor_menu = QtWidgets.QMenu()
    app.ui.exc_edit_toolbar = QtWidgets.QToolBar()
    app.geo_editor.editor_options = {'global_snap_max': 0.2}
    editor = exc.AppExcEditor(app)
    initial, first, slot = endpoint_scene()
    for name in ('storage_dict', 'selected', 'tool2tooldia', 'olddia_newdia', 'points_edit',
                 'slot_points_edit', 'last_tool_selected', 'current_storage'):
        setattr(editor, name, getattr(initial, name))
    editor.replot = Mock()
    editor.ui.slot_endpoint_load.click()
    editor.ui.slot_endpoint_entries[2].set_value(9)
    editor.ui.slot_endpoint_entries[3].set_value(7)
    editor.ui.slot_endpoint_apply.click()
    assert editor.selected[0].exc_slot == ((4, 0), (9, 7))
    assert len(editor.history.undo_stack) == 1
    assert editor.slot_endpoint_action in app.ui.exc_editor_menu.actions()
    assert editor.slot_endpoint_action in app.ui.exc_edit_toolbar.actions()
    editor.slot_endpoint_action.trigger()
    tool = editor.active_tool
    assert isinstance(tool, exc.SlotEndpointEditorExc)
    tool.click((9, 7))
    assert tool.drag is not None
    editor.select_tool('drill_select')
    assert tool.drag is None
    tool.click_release((20, 20))
    assert editor.history.revision == 1


def test_thread_guard_noop_and_rollback_preserve_native_identity():
    editor, first, slot = endpoint_scene()
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(editor.edit_slot_endpoints, slot, ((4, 0), (9, 3))).result() == 'fail'
    assert editor.edit_slot_endpoints(slot, slot.exc_slot) is None
    assert not editor.history.undo_stack
    with pytest.raises(RuntimeError, match='rollback'):
        with editor.history.operation('Failed composite'):
            editor.edit_slot_endpoints(slot, ((4, 0), (9, 3)))
            raise RuntimeError('rollback')
    assert list(editor.storage_dict[1.0].get_objects()) == [first, slot]
    assert editor.selected == [slot]
    assert slot.exc_slot_geometry is slot.geo
    assert not editor.history.undo_stack


@pytest.mark.parametrize('units', ['MM', 'IN'])
@pytest.mark.parametrize('export_units', ['METRIC', 'INCH'])
def test_edited_resized_slot_roundtrip_both_document_and_export_units(app, tmp_path, units, export_units):
    editor, first, slot = endpoint_scene()
    factor = 25.4 if units == 'IN' else 1.0
    diameter = 1.0 / factor
    slot.geo = scale(slot.geo, xfact=1 / factor, yfact=1 / factor, origin=(0, 0))
    slot.exc_slot = tuple(tuple(v / factor for v in point) for point in slot.exc_slot)
    slot.exc_slot_geometry = slot.geo
    storage = AppGeoEditor.make_storage()
    storage.insert(slot)
    editor.storage_dict = {diameter: storage}
    editor.tool2tooldia = {1: diameter}
    editor.olddia_newdia = {diameter: diameter}
    editor.points_edit, editor.slot_points_edit = {diameter: []}, {diameter: [slot.exc_slot]}
    endpoints = ((4 / factor, 0), (11.1234 / factor, 7.6789 / factor))
    replacement = editor.edit_slot_endpoints(slot, endpoints)
    # 2.54 mm / 0.1 inch is exactly representable in both existing tool-header formats.
    editor.resize_features([replacement], 2.54 / factor)
    resized = editor.selected[0]
    assert resized.exc_slot == endpoints
    assert editor.undo() and editor.redo()
    source = make_same_diameter_excellon(app)
    source.units = units
    app.app_units = units
    editor._save_excellon_in_place = Mock()
    exc.AppExcEditor.update_fcexcellon(editor, source, in_place=True)
    source.tools = editor.new_tools
    app.options['excellon_exp_units'] = export_units
    app.options['excellon_exp_decimals'] = 6
    app.f_handlers = appIO(app)
    assert source.regenerate_source()
    again = reparse_excellon(app, source.source_file, tmp_path)
    back = (25.4 if again.units == 'IN' else 1) / factor
    tool = next(iter(again.tools.values()))
    start, stop = tool['slots'][0]
    assert (start.x * back, start.y * back) == pytest.approx(endpoints[0], abs=0.001 / factor)
    assert (stop.x * back, stop.y * back) == pytest.approx(endpoints[1], abs=0.001 / factor)
    assert tool['tooldia'] * back == pytest.approx(2.54 / factor, abs=0.001 / factor)


def test_suspended_drag_and_edit_are_rejected():
    editor, first, slot = endpoint_scene()
    editor.app.geo_editor = SimpleNamespace(editor_options={'global_snap_max': 0.2})
    editor.history.suspended = True
    tool = exc.SlotEndpointEditorExc(editor)
    tool.click((6, 1))
    assert tool.drag is None
    assert editor.edit_slot_endpoints(slot, ((4, 0), (9, 3))) == 'fail'
    assert list(editor.storage_dict[1.0].get_objects()) == [first, slot]


def test_start_endpoint_drag_keeps_stop_fixed_and_escape_and_clear_cancel():
    editor, first, slot = endpoint_scene()
    editor.app.geo_editor = SimpleNamespace(editor_options={'global_snap_max': 0.2})
    editor.active_tool = tool = exc.SlotEndpointEditorExc(editor)
    tool.click((4, 0))
    tool.click_release((1, -3))
    assert editor.selected[0].exc_slot == ((1, -3), (6, 1))
    tool.click((1, -3))
    tool.on_key('Escape')
    tool.click_release((20, 20))
    assert editor.history.revision == 1
    tool.click((1, -3))
    editor.shapes = Mock()
    editor._slot_numeric_target = (editor.selected[0], editor.selected[0].geo, 0, 1)
    exc.AppExcEditor.clear(editor)
    tool.click_release((20, 20))
    assert tool.drag is None
    assert editor._slot_numeric_target is None
    assert editor.history.revision == 1


@pytest.mark.parametrize('units', ['MM', 'IN'])
def test_source_load_keeps_native_endpoints_and_detaches_editor_replacements(app, units):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor, first, slot = endpoint_scene()
    source = make_same_diameter_excellon(app)
    source.units = units
    factor = 25.4 if units == 'IN' else 1.0
    endpoints = ((1.234567 / factor, -2.345678 / factor), (7.654321 / factor, 5.432198 / factor))
    source.tools = {1: {'tooldia': 1 / factor, 'drills': [Point(0, 0)],
                        'slots': [(Point(endpoints[0]), Point(endpoints[1]))], 'data': {'tag': 'native'}}}
    source.create_geometry()
    source_geometry = source.solid_geometry
    editor.app = app
    app.app_units = units    # the editor takes its units from the application when it loads
    editor.decimals = 8
    editor.dec_format = lambda value: round(float(value), 8)
    editor.deactivate = Mock()
    editor.activate = lambda: editor.storage_dict.clear()
    editor.set_editor_ui = Mock()
    editor.on_tool_edit = Mock()
    editor.ui = SimpleNamespace(tools_table_exc=QtWidgets.QTableWidget(0, 4))
    exc.AppExcEditor.edit_fcexcellon(editor, source)
    loaded = next(shape for storage in editor.storage_dict.values() for shape in storage.get_objects()
                  if hasattr(shape, 'exc_slot'))
    assert loaded.exc_slot == endpoints
    assert loaded.exc_slot_geometry is loaded.geo
    assert not editor.history.undo_stack
    editor.selected = [loaded]
    edited = editor.edit_slot_endpoints(loaded, (endpoints[0], (9 / factor, 8 / factor)))
    assert edited.exc_slot[0] == endpoints[0]
    assert source.tools[1]['slots'][0][1].equals(Point(endpoints[1]))
    assert source.tools[1]['data'] == {'tag': 'native'}
    assert source.solid_geometry is source_geometry
    assert editor.undo()
    assert editor.selected == [loaded]
