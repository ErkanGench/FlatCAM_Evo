"""Paint plugin controller: tool table, parameters copy, selection state."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from shapely import box

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6 import QtWidgets

from appPlugins.ToolPaint.Paint import ToolPaint


def _item(text='', row=0):
    item = MagicMock()
    item.text.return_value = str(text)
    item.row.return_value = row
    return item


def _stub(tools, **extra):
    """A ToolPaint stand-in: `tools` is {uid: diameter}; the table rows follow the dict order."""
    paint_tools = {uid: {'tooldia': dia, 'data': {'tools_mill_tool_shape': 0}, 'solid_geometry': []}
                   for uid, dia in tools.items()}
    uids = list(tools)
    table = MagicMock()
    table.rowCount.return_value = len(uids)
    cells = {}
    for row, uid in enumerate(uids):
        cells[(row, 1)] = _item(tools[uid], row)
        cells[(row, 3)] = _item(uid, row)
    table.item.side_effect = lambda r, c: cells[(r, c)]
    app = MagicMock()
    app.dec_format.side_effect = lambda v, d: float('%.*f' % (d, v))
    stub = SimpleNamespace(
        app=app, decimals=4, paint_tools=paint_tools, blockSignals=MagicMock(), build_ui=MagicMock(),
        ui=SimpleNamespace(tools_table=table), cells=cells)
    for key, value in extra.items():
        setattr(stub, key, value)
    return stub


def _edit(stub, row, text):
    stub.cells[(row, 1)].text.return_value = text
    ToolPaint.on_tool_edit(stub, stub.cells[(row, 1)])


def test_rebuild_ui_keeps_the_shared_tool_dict():
    stub = _stub({3: 1.0, 7: 0.5})
    shared = stub.paint_tools
    with patch('appPlugins.ToolPaint.Paint.QtCore.QTimer'):
        ToolPaint.rebuild_ui(stub)
    assert stub.paint_tools is shared
    assert sorted(shared) == [1, 2]
    assert shared[1]['tooldia'] == 1.0 and shared[2]['tooldia'] == 0.5


def test_tool_edit_rejects_a_duplicate_of_any_other_tool():
    stub = _stub({1: 2.0, 2: 1.0, 3: 0.5})
    _edit(stub, 0, '0.5')   # duplicates the last tool, not the first one checked
    assert stub.paint_tools[1]['tooldia'] == 2.0
    _edit(stub, 0, '1.0')   # duplicates a middle tool
    assert stub.paint_tools[1]['tooldia'] == 2.0
    _edit(stub, 0, '1.5')
    assert stub.paint_tools[1]['tooldia'] == 1.5
    stub.build_ui.assert_called()


def test_tool_edit_rejects_non_positive_and_non_finite_diameters():
    stub = _stub({1: 2.0, 2: 1.0})
    for text in ('0', '-1', 'nan', 'inf', 'abc'):
        _edit(stub, 0, text)
        assert stub.paint_tools[1]['tooldia'] == 2.0, text
    assert stub.blockSignals.call_args_list[-1].args == (False,)


def test_tool_add_rejects_non_positive_and_non_finite_diameters():
    stub = _stub({1: 2.0}, default_data={})
    stub.ui.new_tooldia_entry = MagicMock()
    for dia in (0, -1.0, float('nan'), float('inf')):
        ToolPaint.on_tool_add(stub, custom_dia=dia)
        ToolPaint.on_tool_default_add(stub, dia=dia)
    assert list(stub.paint_tools) == [1]


def test_apply_to_all_copies_only_the_form_parameters_of_the_selected_row():
    stub = _stub({1: 2.0, 2: 1.0})
    stub.paint_tools[1]['data'].update(tools_paint_overlap=0.1, extra_key='one')
    stub.paint_tools[2]['data'].update(tools_paint_overlap=0.7, extra_key='two', tools_mill_tool_shape=3)
    stub.form_fields = {'tools_paint_overlap': MagicMock()}
    stub.ui.tools_table.selectedItems.return_value = [_item(row=1)]
    stub.ui.tools_table.currentRow.return_value = 0     # differs from the row the form shows
    ToolPaint.on_apply_param_to_all_clicked(stub)
    assert stub.paint_tools[1]['data']['tools_paint_overlap'] == 0.7
    assert stub.paint_tools[1]['data']['extra_key'] == 'one'
    assert stub.paint_tools[1]['data']['tools_mill_tool_shape'] == 0
    stub.build_ui.assert_called()


def test_delete_with_nothing_selected_warns_and_keeps_the_tools():
    stub = _stub({1: 2.0, 2: 1.0})
    stub.ui.tools_table.selectedItems.return_value = []
    ToolPaint.on_tool_delete(stub)
    assert list(stub.paint_tools) == [1, 2]
    assert 'success' not in str(stub.app.inform.emit.call_args)


def test_delete_by_row_number_removes_the_tool_of_that_row():
    stub = _stub({4: 2.0, 9: 1.0})
    ToolPaint.on_tool_delete(stub, rows_to_delete=1)
    assert list(stub.paint_tools) == [4]


def test_tool_shape_combo_is_stored_in_the_tool_data(qapp):
    stub = _stub({1: 2.0, 2: 1.0})
    combo = QtWidgets.QComboBox()
    combo.addItems(["C1", "C2", "C3", "C4", "B", "V", "L"])
    combo.setCurrentIndex(5)
    stub.sender = lambda: combo
    stub.ui.tools_table.indexAt.return_value = SimpleNamespace(row=lambda: 1, column=lambda: 2)
    ToolPaint.on_tooltable_cell_widget_change(stub)
    assert stub.paint_tools[2]['data']['tools_mill_tool_shape'] == 5
    assert stub.paint_tools[2]['tool_type'] == 'V'
    assert stub.paint_tools[1]['data']['tools_mill_tool_shape'] == 0


def test_reset_selection_state_clears_a_half_made_selection():
    points = [(0, 0)]
    stub = SimpleNamespace(first_click=True, cursor_pos=(1, 1), mouse_is_dragging=True, points=points,
                           poly_drawn=True, delete_moving_selection_shape=MagicMock(),
                           delete_tool_selection_shape=MagicMock())
    ToolPaint.reset_selection_state(stub)
    assert (stub.first_click, stub.cursor_pos, stub.mouse_is_dragging, stub.poly_drawn) == (False, None, False, False)
    assert stub.points is points and points == []
    stub.delete_moving_selection_shape.assert_called_once()


def test_tools_table_follows_the_uid_order_in_default_order():
    from appPlugins.ToolPaint.Paint import tool_rows_order
    tools = {2: {'tooldia': 0.5}, 1: {'tooldia': 2.0}, 3: {'tooldia': 1.0}}
    assert tool_rows_order(tools, 0, 4) == [1, 2, 3]
    assert tool_rows_order(tools, 1, 4) == [2, 3, 1]
    assert tool_rows_order(tools, 2, 4) == [1, 3, 2]


def test_beginner_level_unchecks_and_hides_check_validity_advanced_restores_it():
    ui = SimpleNamespace(
        valid_cb=MagicMock(), rest_cb=MagicMock(), level=MagicMock(), add_tool_frame=MagicMock(),
        apply_param_to_all=MagicMock(), tools_table=MagicMock())
    stub = SimpleNamespace(ui=ui, app=SimpleNamespace(options={'tools_paint_check_valid': True}))
    ToolPaint.on_level_changed(stub, False)
    ui.valid_cb.set_value.assert_called_with(False)
    ui.valid_cb.hide.assert_called_once()
    ToolPaint.on_level_changed(stub, True)
    ui.valid_cb.set_value.assert_called_with(True)
    ui.valid_cb.show.assert_called_once()


def test_closing_the_plugin_mid_selection_gives_the_canvas_back():
    stub = _stub({1: 1.0}, area_sel_disconnect_flag=True, poly_sel_disconnect_flag=False, grid_status_memory=False,
                 poly_dict={1: 'zone'}, reset_selection_state=MagicMock(), clear_preview=MagicMock(),
                 on_mouse_release=MagicMock(), on_mouse_move=MagicMock(), on_key_press=MagicMock())
    stub.end_selection = lambda: ToolPaint.end_selection(stub)
    ToolPaint.on_plugin_cleanup(stub)
    assert stub.area_sel_disconnect_flag is False
    stub.app.plotcanvas.graph_event_disconnect.assert_any_call('mouse_release', stub.on_mouse_release)
    stub.app.plotcanvas.graph_event_connect.assert_any_call('mouse_release',
                                                            stub.app.on_mouse_click_release_over_plot)
    stub.app.ui.notebook.setDisabled.assert_called_with(False)
    assert stub.poly_dict == {}
    stub.reset_selection_state.assert_called_once()


# ----------------------------------------------------------------------------------------------------------------------
# Preview: the plugin is built headless (offscreen Qt, MagicMock app) like the NCC panel tests
# ----------------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def painter(qapp, tmp_path):
    import functools
    from copy import deepcopy
    from PyQt6.QtCore import QStringListModel
    from appMain import App
    from defaults import AppDefaults
    from test_plugin_geometry_bases import make_tool_app

    class Collection(QStringListModel):
        def __init__(self):
            super().__init__()
            self.objects, self.selected = {}, []

        def get_selected(self):
            return self.selected

        def get_active(self):
            return None

        def get_list(self):
            return list(self.objects.values())

        def get_names(self):
            return list(self.objects)

        def get_by_name(self, name):
            return self.objects.get(name)

    app = make_tool_app()
    app.collection = Collection()
    app.options = deepcopy(AppDefaults.factory_defaults)
    app.defaults = SimpleNamespace(get=AppDefaults.factory_defaults.get, report_usage=lambda *args: None,
                                   factory_defaults=AppDefaults.factory_defaults)
    app.dec_format = functools.partial(App.dec_format, app)
    app.tools_database_path.return_value = str(tmp_path / "missing_tools_db.json")
    app.worker_task.emit.side_effect = lambda task: task['fcn'](*task['params'])
    app.abort_flag = False
    app.plotcanvas.new_shape_collection.side_effect = lambda **kwargs: MagicMock()
    app.options["tools_paint_tooldia"] = "1.0"
    t = ToolPaint(app)
    t.decimals = 4
    t.set_tool_ui()
    t.build_ui()
    t.ui.tools_table.selectAll()
    board = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 4, 4), box(10, 0, 14, 4)],
                            obj_options={'name': 'board'}, multigeo=False, tools={})
    ref = SimpleNamespace(kind='geometry', solid_geometry=[box(-1, -1, 5, 5)], obj_options={'name': 'ref'})
    app.collection.objects.update(board=board, ref=ref)
    t.ui.obj_combo.currentText = lambda: 'board'
    t.ui.reference_combo.currentText = lambda: 'ref'
    return t


def _drawn_area(t):
    t.on_preview()
    store = t._preview_shapes
    if store is None:
        return 0.0
    area = sum(call.args[0].area for call in store.add.call_args_list)
    store.add.reset_mock()
    return area


def test_preview_draws_the_area_to_paint_after_the_offset_and_is_cleared(painter):
    painter.ui.select_method_combo.set_value(0)     # All
    assert _drawn_area(painter) == pytest.approx(32.0)
    for tool in painter.paint_tools.values():
        tool['data']['tools_paint_offset'] = 0.5
    assert _drawn_area(painter) == pytest.approx(18.0)

    # Reference Object: only the board polygons inside the reference
    painter.ui.select_method_combo.set_value(3)
    assert _drawn_area(painter) == pytest.approx(9.0)

    # Area Selection previews the zones of the last run: none yet
    painter.ui.select_method_combo.set_value(2)
    painter.app.worker_task.emit.reset_mock()
    painter.on_preview()
    assert painter.app.inform.emit.call_args.args[0].startswith('[WARNING_NOTCL]')
    painter.app.worker_task.emit.assert_not_called()
    # the zones of the last Area Selection run: only the part of the board inside them
    painter.last_zones = [box(-1, -1, 2, 5)]
    assert _drawn_area(painter) == pytest.approx(3.0)

    # a result that arrives after the object changed is not drawn
    painter.ui.select_method_combo.set_value(0)
    tasks = []
    painter.app.worker_task.emit.side_effect = tasks.append
    painter.on_preview()
    painter.on_source_changed()
    tasks[0]['fcn'](*tasks[0]['params'])
    painter._preview_shapes.add.assert_not_called()

    # a Reset clears it
    painter._preview_shapes.clear.reset_mock()
    painter._preview_drawn = True
    painter.set_tool_ui()
    painter._preview_shapes.clear.assert_called()
