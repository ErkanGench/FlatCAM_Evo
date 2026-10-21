"""Gerber counterparts retain native FOLLOW and material ownership semantics."""

import math
from unittest.mock import MagicMock, call

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from shapely.geometry import box, MultiPolygon
from shapely.ops import unary_union

from appEditors import appGerberEditor as module
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appGUI.MainGUI import MainGUI
from test_gerber_editor_clear import editor_save
from test_gerber_editor_pick import make_editor, aperture, pad, event
from test_unify_characterization import app, _headless_qt, make_gerber, NATIVE_GBR, reparse_gerber, assert_poly_equiv  # noqa: F401


class JumpHolder(QtCore.QObject):
    """Stand-in of the app jump signal (no arguments)."""
    signal = QtCore.pyqtSignal()


@pytest.mark.parametrize('same_owner', [True, False])
def test_difference_keeps_cutters_and_order_with_history(same_owner):
    target = DrawToolShape({'solid': MultiPolygon([box(0, 0, 10, 10), box(12, 0, 13, 1)])})
    cutter = DrawToolShape({'solid': box(2, 2, 8, 8)})
    unrelated = pad(20, 20, 1)
    storage = {10: aperture([unrelated, target, cutter] if same_owner else [unrelated, target])}
    if not same_owner:
        storage[11] = aperture([cutter])
    editor = make_editor(storage)
    editor.selected = [target, cutter]
    original = cutter.geo
    result = editor.apply_region_operation('difference_keep')
    assert result != 'fail'
    assert unary_union([s.geo['solid'] for s in result]).equals(target.geo['solid'].difference(cutter.geo['solid']))
    assert sum(len(s.geo['solid'].interiors) for s in result) == 1
    assert editor.storage_dict[10]['geometry'] == ([unrelated, cutter] if same_owner else [unrelated])
    assert editor.storage_dict[10 if same_owner else 11]['geometry'][-1] is cutter
    assert cutter.geo is original
    assert editor.selected == result + [cutter]
    assert len(editor.history.undo_stack) == 1
    assert editor.undo()
    assert editor.selected == [target, cutter]
    assert editor.storage_dict[10]['geometry'][1] is target
    assert editor.redo()
    assert editor.storage_dict[10 if same_owner else 11]['geometry'][-1] is cutter


@pytest.mark.parametrize('failure', ['clear', 'pending', 'single'])
def test_keep_cutters_rejection_is_atomic(failure):
    first, second = DrawToolShape({'solid': box(0, 0, 10, 10)}), pad(2, 2, 1)
    editor = make_editor({10: aperture([first, second])})
    editor.selected = [first, second]
    if failure == 'clear':
        second.geo['clear'] = box(0, 0, 1, 1)
    elif failure == 'pending':
        editor.history.reserve()
    else:
        editor.selected = [first]
    before = editor.geometry_revision
    assert editor.apply_region_operation('difference_keep') == 'fail'
    assert editor.storage_dict[10]['geometry'] == [first, second]
    assert editor.geometry_revision == before
    assert not editor.history.undo_stack


def arc_tool(editor):
    editor.last_aperture_selected = 10
    editor.loaded_as_regions = False
    editor.jump_holder = JumpHolder()
    editor.app.jump_signal = editor.jump_holder.signal
    tool = module.ArcEditorGrb(editor)
    editor.active_tool = tool
    return tool


@pytest.mark.parametrize('mode,points', [
    ('c12', [(0, 0), (1, 0), (0, 1)]),
    ('12c', [(1, 0), (0, 1), (0, 0)]),
    ('132', [(1, 0), (0, 1), (math.sqrt(0.5), math.sqrt(0.5))])])
def test_arc_modes_preview_commit_and_history(mode, points):
    editor = make_editor({10: aperture([])})
    tool = arc_tool(editor)
    tool.mode, tool.direction = mode, 'ccw'
    tool.click(points[0])
    tool.click(points[1])
    preview = tool.utility_geometry(points[2]).geo
    tool.click(points[2])
    assert tool.complete
    assert tool.geometry.geo['solid'].equals(preview['solid'])
    follow = tool.geometry.geo['follow']
    assert follow.geom_type == 'LineString' and follow.is_simple
    assert follow.coords[0] == pytest.approx((1, 0))
    assert follow.coords[-1] == pytest.approx((0, 1))
    assert all(math.hypot(x, y) == pytest.approx(1) for x, y in follow.coords)
    assert tool.geometry.geo['solid'].equals(follow.buffer(0.1 / 1.999, quad_segs=16))
    editor.on_grb_shape_complete()
    assert len(editor.storage_dict[10]['geometry']) == 1
    assert not editor.loaded_as_regions
    assert editor.undo() and editor.storage_dict[10]['geometry'] == []
    assert editor.redo() and len(editor.storage_dict[10]['geometry']) == 1
    tool.clean_up()


@pytest.mark.parametrize('kind,extra', [('R', {}), ('REG', {}), ('C', {'hole': 0.01}),
                                        ('C', {'size': float('nan')})])
def test_arc_rejects_unsupported_apertures(kind, extra):
    editor = make_editor({10: {**aperture([], kind), **extra}})
    tool = arc_tool(editor)
    assert tool.dont_execute and tool.complete
    assert not editor.storage_dict[10]['geometry'] and not editor.history.undo_stack
    tool.clean_up()


@pytest.mark.parametrize('failure', ['collinear', 'coincident', 'stale', 'units', 'aperture', 'pending', 'steps'])
def test_arc_invalid_or_stale_construction_is_atomic(failure):
    editor = make_editor({10: aperture([])})
    if failure == 'steps':
        editor.app.options['gerber_circle_steps'] = 0
    tool = arc_tool(editor)
    if failure == 'steps':
        assert tool.dont_execute
        return
    tool.mode = '132' if failure == 'collinear' else 'c12'
    tool.click((0, 0))
    tool.click((1, 0) if failure != 'coincident' else (0, 0))
    if failure == 'stale':
        editor.history.reset()
    elif failure == 'units':
        editor.app.app_units = 'IN'
    elif failure == 'aperture':
        editor.storage_dict[10]['size'] = 1
    elif failure == 'pending':
        editor.history.reserve()
    tool.click((2, 0) if failure == 'collinear' else (0, 1))
    assert tool.geometry is None
    assert not editor.storage_dict[10]['geometry'] and not editor.history.undo_stack
    tool.clean_up()


def test_arc_mode_direction_cancel_and_owned_jump_connection():
    editor = make_editor({10: aperture([])})
    tool = arc_tool(editor)
    unrelated = MagicMock()
    editor.app.jump_signal.connect(unrelated)
    tool.click((0, 0))
    tool.on_key('M')
    assert tool.mode == '12c' and tool.points == []
    tool.on_key('M')
    assert tool.mode == '132'
    tool.on_key('M')
    assert tool.mode == 'c12'
    tool.on_key('D')
    assert tool.direction == 'ccw'
    tool.on_key('J')
    editor.app.on_jump_to.assert_called_once()
    tool.clean_up()
    editor.app.jump_signal.emit()
    unrelated.assert_called_once()
    assert not editor.history.undo_stack


@pytest.mark.parametrize('operation', ['arc', 'difference_keep'])
@pytest.mark.parametrize('steps,direction', [(16, 'cw'), (64, 'ccw')])
def test_new_actions_native_export_reparse(app, tmp_path, operation, steps, direction):
    editor = make_editor({10: aperture([])})
    editor.app.options['gerber_circle_steps'] = steps
    if operation == 'arc':
        tool = arc_tool(editor)
        tool.direction = direction
        for point in [(0, 0), (2, 0), (0, 2)]:
            tool.click(point)
        editor.on_grb_shape_complete()
        tool.clean_up()
    else:
        first = DrawToolShape({'solid': box(0, 0, 10, 10)})
        cutter = DrawToolShape({'solid': box(2, 2, 8, 8)})
        editor.storage_dict[10]['geometry'] = [first]
        editor.storage_dict[11] = {'type': 'REG', 'size': 0, 'geometry': [cutter]}
        editor.selected = [first, cutter]
        assert editor.apply_region_operation(operation) != 'fail'
    tools = {key: {**value, 'geometry': [s.geo for s in value['geometry']]}
             for key, value in editor.storage_dict.items() if value['geometry']}
    expected = unary_union([s.geo['solid'] for value in editor.storage_dict.values() for s in value['geometry']])
    edited = editor_save(app, make_gerber(app, NATIVE_GBR), tools, loaded_as_regions=editor.loaded_as_regions)
    again = reparse_gerber(app, edited.source_file, tmp_path)
    assert_poly_equiv(again.solid_geometry, expected, abs_tol=1e-4)


def test_arc_real_toolbar_switch_disconnects_cancelled_tool():
    editor = make_editor({10: aperture([])})
    editor.app.ui.grb_add_arc_btn = QtGui.QAction('Arc')
    editor.app.ui.grb_select_btn = QtGui.QAction('Select')
    editor.connect_grb_toolbar_signals()
    editor.select_tool = module.AppGerberEditor.select_tool.__get__(editor)
    editor.last_aperture_selected = 10
    editor.jump_holder = JumpHolder()
    editor.app.jump_signal = editor.jump_holder.signal
    editor.app.ui.grb_add_arc_btn.trigger()
    tool = editor.active_tool
    assert isinstance(tool, module.ArcEditorGrb)
    tool.click((0, 0))
    editor.app.ui.grb_select_btn.trigger()
    assert isinstance(editor.active_tool, module.SelectEditorGrb)
    assert tool._jump_slot is None
    assert not editor.app.ui.grb_add_arc_btn.isChecked()
    assert not editor.history.undo_stack


def test_menu_and_toolbar_dispatch_and_rebuild_do_not_duplicate_menu_signals():
    editor = make_editor()
    menus = {name: getattr(editor.app.ui, name).triggered.connect for name in (
        'grb_add_rectangle_menuitem', 'grb_add_text_menuitem', 'grb_add_arc_menuitem',
        'grb_difference_keep_menuitem')}
    editor.on_region_drawing = MagicMock()
    editor.apply_region_operation = MagicMock()
    for kind in ('rectangle', 'text'):
        setattr(editor.app.ui, 'grb_add_%s_btn' % kind, QtGui.QAction(kind))
    editor.app.ui.grb_difference_keep_btn = QtGui.QAction('Keep Cutters')
    editor.connect_grb_toolbar_signals()
    for kind in ('rectangle', 'text'):
        getattr(editor.app.ui, 'grb_add_%s_btn' % kind).trigger()
        editor.on_region_drawing.assert_called_once_with(kind)
        editor.on_region_drawing.reset_mock()
    editor.app.ui.grb_difference_keep_btn.trigger()
    editor.apply_region_operation.assert_called_once_with('difference_keep')
    editor.apply_region_operation.reset_mock()
    for name, connect in menus.items():
        assert connect.call_count == 1
        action = QtGui.QAction(name)
        action.triggered.connect(connect.call_args.args[0])
        action.trigger()
    assert editor.on_region_drawing.call_args_list == [call('rectangle'), call('text')]
    editor.select_tool.assert_called_once_with('arc')
    editor.apply_region_operation.assert_called_once_with('difference_keep')


def test_repopulated_toolbar_contains_enabled_parent_actions_and_existing_icons():
    editor = make_editor()
    ui = MagicMock()
    ui.app = editor.app
    ui.grb_edit_toolbar = QtWidgets.QToolBar()
    MainGUI.populate_toolbars(ui)
    for name in ('grb_add_rectangle_btn', 'grb_add_text_btn', 'grb_add_arc_btn', 'grb_difference_keep_btn'):
        action = getattr(ui, name)
        assert action in ui.grb_edit_toolbar.actions()
        assert not action.icon().isNull()
        ui.grb_edit_toolbar.setEnabled(True)
        assert ui.grb_edit_toolbar.widgetForAction(action).isEnabled()
        ui.grb_edit_toolbar.setEnabled(False)
        assert not ui.grb_edit_toolbar.widgetForAction(action).isEnabled()


def test_arc_canvas_completion_and_right_click_cancellation():
    editor = make_editor({10: aperture([])})
    editor.app.geo_editor.snap = lambda x, y: (x, y)
    tool = arc_tool(editor)
    for x, y in [(0, 0), (1, 0), (0, 1)]:
        editor.on_canvas_click(event(x, y))
    assert len(editor.storage_dict[10]['geometry']) == 1
    assert len(editor.history.undo_stack) == 1
    editor.select_tool.assert_called_with('select')
    assert tool._jump_slot is None
    editor.undo()
    editor.app.ui.grb_select_btn = QtGui.QAction('Select')
    editor.connect_grb_toolbar_signals()
    editor.select_tool = module.AppGerberEditor.select_tool.__get__(editor)
    tool = arc_tool(editor)
    editor.on_canvas_click(event(0, 0))
    editor.app.ui.popMenu.mouse_is_panning = False
    editor.on_canvas_click_release(event(0, 0, button=2))
    assert isinstance(editor.active_tool, module.SelectEditorGrb)
    assert tool._jump_slot is None
    assert not editor.storage_dict[10]['geometry'] and not editor.history.undo_stack


def test_arc_drag_does_not_start_feature_selection():
    editor = make_editor({10: aperture([])})
    editor.app.geo_editor.snap = lambda x, y: (x, y)
    arc_tool(editor)
    editor.on_canvas_click(event(0, 0))
    editor.on_canvas_move(event(5, 5, dragging=1))
    assert editor.app.selection_type is None
    editor.active_tool.clean_up()
