"""Regression tests for the Excellon Editor defect fixes: units, menu actions, tool table, history labels, warnings,
translated labels and the diagnostics tolerance. Headless: the editor is real, the app is a stand-in."""

from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from PyQt6 import QtWidgets
from shapely.affinity import translate
from shapely.geometry import Point

from appEditors.appExcEditor import AppExcEditor
from appEditors.appGeoEditor import AppGeoEditor
from defaults import AppDefaults
from test_exc_editor_history import drill, scene
from test_unify_characterization import _headless_qt  # noqa: F401  (autouse: patches the canvas shape collection)

EDITOR_ACTION_LABELS = ('Undo', 'Redo', 'Edit slot endpoints', 'Rotate selected features', 'Mirror X',
                        'Mirror Y', 'Scale selected features')


def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def qt_editor(app_units='MM'):
    """A real AppExcEditor on a stand-in app with real menu and toolbar (same setup as test_exc_selected_transforms)."""
    qapp()
    app = MagicMock()
    app.decimals, app.app_units, app.resource_location = 4, app_units, 'assets/resources'
    app.dec_format = lambda value, decimals=None: round(float(value), 4 if decimals is None else decimals)
    app.defaults = AppDefaults()
    app.options = dict(app.defaults.defaults)
    app.ui.exc_editor_menu = QtWidgets.QMenu()
    app.ui.exc_edit_toolbar = QtWidgets.QToolBar()
    return app, AppExcEditor(app)


def bind(editor, *names):
    """The scene() stand-in has only some AppExcEditor methods: bind the named ones from the real class."""
    for name in names:
        setattr(editor, name, MethodType(getattr(AppExcEditor, name), editor))


def warned(editor):
    """True when the app was told a WARNING_NOTCL message (the inform signal is a Mock)."""
    return any('WARNING_NOTCL' in str(call.args[0]) for call in editor.app.inform.emit.call_args_list if call.args)


def native_obj(units, tooldia, xy):
    """Minimal stand-in for an ExcellonObject with one tool and one drill, in the given units."""
    return SimpleNamespace(units=units, obj_options={'name': 'job'}, diameterless=False, visible=True,
                           geo_steps_per_circle=64, zeros='L',
                           tools={1: {'tooldia': tooldia, 'drills': [Point(*xy)], 'slots': []}})


# ---------------------------------------------------------------------------------------------------------------
# 1. units: edit_fcexcellon takes the units from the app at edit time
# ---------------------------------------------------------------------------------------------------------------

def test_editor_created_in_mm_edits_in_object_in_inches_without_scaling():
    app, editor = qt_editor('MM')
    app.app_units = 'IN'
    editor.edit_fcexcellon(native_obj('IN', 0.04, (1.0, 2.0)))
    assert editor.units == 'IN'
    assert list(editor.points_edit) == [0.04]
    drill = editor.points_edit[0.04][0]
    assert (drill.x, drill.y) == pytest.approx((1.0, 2.0))
    # the '+' drill symbol is as wide as the tool, so an unscaled 0.04 in tool gives 0.04 bounds
    assert editor.storage_dict[0.04].get_objects()
    bounds = list(editor.storage_dict[0.04].get_objects())[0].geo.bounds
    assert bounds[2] - bounds[0] == pytest.approx(0.04)


@pytest.mark.parametrize('units,tooldia,xy', [('MM', 0.8, (3.25, -1.5)), ('IN', 0.04, (1.0, 2.0))])
def test_load_then_save_round_trip_is_identity(units, tooldia, xy):
    app, editor = qt_editor(units)
    editor.edit_fcexcellon(native_obj(units, tooldia, xy))
    editor._save_excellon_in_place = Mock()
    editor.update_fcexcellon(SimpleNamespace(geo_steps_per_circle=64), in_place=True)
    tool = editor.new_tools[1]
    assert tool['tooldia'] == pytest.approx(tooldia)
    assert (tool['drills'][0].x, tool['drills'][0].y) == pytest.approx(xy)


# ---------------------------------------------------------------------------------------------------------------
# 2. building the editor twice leaves one set of editor actions
# ---------------------------------------------------------------------------------------------------------------

def test_building_editor_twice_leaves_one_set_of_editor_actions():
    app, first = qt_editor('MM')
    second = AppExcEditor(app)
    menu_texts = [action.text() for action in app.ui.exc_editor_menu.actions() if action.text()]
    toolbar_texts = [action.text() for action in app.ui.exc_edit_toolbar.actions() if action.text()]
    for label in EDITOR_ACTION_LABELS:
        assert menu_texts.count(label) == 1, label
        assert toolbar_texts.count(label) == 1, label
    # the actions in the menu are the ones of the newest editor only
    assert second.undo_action in app.ui.exc_editor_menu.actions()
    assert first.undo_action not in app.ui.exc_editor_menu.actions()


# ---------------------------------------------------------------------------------------------------------------
# 3. transform keeps tool2tooldia sorted; the next add lands on its own row
# ---------------------------------------------------------------------------------------------------------------

def test_scale_keeps_tool_table_sorted_and_next_add_selects_its_row():
    editor, drill, slot = scene()
    editor.transform_features = MethodType(AppExcEditor.transform_features, editor)
    editor.ui = SimpleNamespace(addtool_entry=Mock(), tools_table_exc=MagicMock())
    editor.units, editor.dec_format = 'MM', lambda value: round(value, 4)
    editor.selected = [slot]
    # the slot moves to 0.5 mm: it sorts before the 1.0 mm drill
    assert editor.transform_features('scale', 0.5) != 'fail'
    assert editor.tool2tooldia == {1: 0.5, 2: 1.0}
    assert list(editor.tool2tooldia.values()) == sorted(editor.tool2tooldia.values())

    def rebuild_like_build_ui():
        # build_ui() rebuilds tool2tooldia in diameter order from the table; the scene's build_ui is a Mock
        editor.tool2tooldia = {index: dia for index, dia in enumerate(sorted(editor.storage_dict), 1)}

    editor.build_ui = Mock(side_effect=rebuild_like_build_ui)
    AppExcEditor.on_tool_add(editor, tooldia=0.75)
    assert editor.tool2tooldia == {1: 0.5, 2: 0.75, 3: 1.0}
    assert editor.last_tool_selected == 2
    editor.ui.tools_table_exc.selectRow.assert_called_with(1)


# ---------------------------------------------------------------------------------------------------------------
# 4. diameters are rounded to self.decimals on add and on edit
# ---------------------------------------------------------------------------------------------------------------

def test_tool_add_rounds_diameter_to_decimals():
    editor, drill, slot = scene()
    editor.ui = SimpleNamespace(addtool_entry=Mock(), tools_table_exc=MagicMock())
    editor.units, editor.decimals, editor.dec_format = 'MM', 4, lambda value: round(value, 4)
    AppExcEditor.on_tool_add(editor, tooldia=0.81234)
    assert 0.8123 in editor.storage_dict
    assert 0.81234 not in editor.storage_dict
    assert editor.olddia_newdia[0.8123] == 0.8123


def test_tool_edit_rounds_diameter_to_decimals():
    editor, drill, slot = scene()
    editor.ui = SimpleNamespace(tools_table_exc=MagicMock())
    editor.storage_dict = {1.0: AppGeoEditor.make_storage()}
    editor.olddia_newdia = {1.0: 1.0}
    editor.tool2tooldia = {1: 1.0}
    editor.ui.tools_table_exc.currentItem().text.return_value = '0.81234'
    editor.ui.tools_table_exc.currentRow.return_value = 0
    AppExcEditor.on_tool_edit(editor, Mock())
    assert list(editor.storage_dict) == [0.8123]
    assert editor.tool2tooldia == {1: 0.8123}


# ---------------------------------------------------------------------------------------------------------------
# 5. nested operation labels: the innermost real operation names the step; still one undo step
# ---------------------------------------------------------------------------------------------------------------

def test_nested_move_inside_generic_draw_records_inner_label_as_one_step():
    editor, first, second = scene()
    with editor.history.operation('Draw features', True) as accepted:
        assert accepted
        with editor.history.operation('Move features') as inner:
            assert inner
            first.geo = translate(first.geo, xoff=3)
    assert len(editor.history.undo_stack) == 1
    assert editor.history.undo_stack[0]['label'] == 'Move features'
    assert editor.undo()
    assert len(editor.history.undo_stack) == 0


def test_generic_label_kept_when_no_inner_real_operation():
    editor, first, second = scene()
    with editor.history.operation('Draw features', True):
        editor.storage_dict[1.0].insert(drill(9))
    assert len(editor.history.undo_stack) == 1
    assert editor.history.undo_stack[0]['label'] == 'Draw features'


# ---------------------------------------------------------------------------------------------------------------
# 6. activate() hides the app corner snap button
# ---------------------------------------------------------------------------------------------------------------

def test_activate_hides_corner_snap_button():
    app, editor = qt_editor('MM')
    app.ui.corner_snap_btn.reset_mock()
    editor.activate()
    app.ui.corner_snap_btn.setVisible.assert_called_with(False)


# ---------------------------------------------------------------------------------------------------------------
# 7. warnings instead of silent failures
# ---------------------------------------------------------------------------------------------------------------

def test_save_while_save_pending_warns_and_fails():
    editor, first, second = scene()
    bind(editor, 'update_fcexcellon')
    editor.history.pending = (object(), 0, 0, Mock())
    assert editor.update_fcexcellon(Mock(), in_place=True) == 'fail'
    assert warned(editor)


def test_save_from_worker_thread_warns_and_fails():
    editor, first, second = scene()
    bind(editor, 'update_fcexcellon')
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(editor.update_fcexcellon, Mock(), True).result() == 'fail'
    assert warned(editor)


def test_slot_endpoint_apply_after_slot_changed_warns():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(slot_endpoint_entries=[Mock() for _ in range(4)])
    bind(editor, 'on_slot_endpoints_apply')
    editor.load_slot_endpoints = Mock()
    stale_geo = second.geo.buffer(1.0)
    editor._slot_numeric_target = (second, stale_geo, (editor.history.session, editor.history.revision), 0)
    assert editor.on_slot_endpoints_apply() == 'fail'
    assert warned(editor)
    assert not editor.history.undo_stack


def test_history_rollback_refreshes_when_only_selection_changed():
    editor, first, second = scene()
    with pytest.raises(ValueError):
        with editor.history.operation('Select then fail'):
            editor.selected = [second]
            raise ValueError('boom')
    assert editor.selected == [first]
    editor.build_ui.assert_called()


def test_history_rollback_refreshes_when_only_aliases_changed():
    editor, first, second = scene()
    with pytest.raises(ValueError):
        with editor.history.operation('Alias then fail'):
            editor.olddia_newdia[5.0] = 5.0
            raise ValueError('boom')
    assert 5.0 not in editor.olddia_newdia
    editor.build_ui.assert_called()


# ---------------------------------------------------------------------------------------------------------------
# 9. translated display and units-aware diagnostics tolerance
# ---------------------------------------------------------------------------------------------------------------

def test_feature_table_shows_translated_type_labels():
    editor, first, second = scene()
    editor.ui = SimpleNamespace(feature_table=QtWidgets.QTableWidget(0, 6),
                                tools_table_exc=QtWidgets.QTableWidget(0, 4))
    editor.feature_filter_values = lambda: {'kind': 'all', 'selected_only': False}
    editor.refresh_feature_table()
    table = editor.ui.feature_table
    labels = {table.item(row, 1).text() for row in range(table.rowCount())}
    assert labels == {'Drill', 'Slot'}


def test_set_editor_ui_diagnostics_tolerance_follows_current_units():
    app, editor = qt_editor('MM')
    editor.edited_obj = SimpleNamespace(diameterless=False, tools={}, obj_options={'name': 'job'})
    editor.points_edit, editor.slot_points_edit = {}, {}
    app.app_units = 'IN'
    editor.set_editor_ui()
    assert editor.units == 'IN'
    assert editor.ui.diagnostics_tolerance.get_value() == pytest.approx(0.00004)
    app.app_units = 'MM'
    editor.set_editor_ui()
    assert editor.ui.diagnostics_tolerance.get_value() == pytest.approx(0.001)
