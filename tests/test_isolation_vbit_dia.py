"""Isolation plugin: V-shape tool diameter (on_update_tool_dia, on_tool_add, on_tool_default_add).

The tests build the real ToolIsolation headless (offscreen Qt, MagicMock app) and drive the production methods.
"""

import json
import math
import os
import sys
from copy import deepcopy

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6 import QtWidgets  # noqa: E402

from defaults import AppDefaults  # noqa: E402
from appPlugins.ToolIsolation import ToolIsolation  # noqa: E402
from test_plugin_geometry_bases import make_tool_app  # noqa: E402

V = ToolIsolation.V_SHAPE_INDEX if hasattr(ToolIsolation, 'V_SHAPE_INDEX') else 5


def v_dia(tip, angle, cut_z):
    return round(tip + 2 * abs(cut_z) * math.tan(math.radians(angle / 2)), 4)


def v_data(tip=0.1, angle=60, cut_z=-0.1, shape=V):
    data = {k: deepcopy(v) for k, v in AppDefaults().defaults.items() if k.startswith('tools_')}
    data.update(tools_mill_tool_shape=shape, tools_mill_vtipdia=tip, tools_mill_vtipangle=angle,
                tools_mill_cutz=cut_z)
    return data


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def tool(qapp, tmp_path):
    app = make_tool_app()
    app.dec_format = lambda value, decimals=4: round(float(value), decimals)
    db_path = tmp_path / 'tools.FlatDB'
    db_path.write_text('{}', encoding='utf-8')
    app.tools_database_path = lambda: str(db_path)
    t = ToolIsolation(app)
    t.db_path = db_path
    t.decimals = 4
    t.default_data = v_data()
    t.ui.v_frame.show()
    # the frame is only "visible" when its parents are shown
    t.ui.v_frame.isVisible = lambda: True
    return t


def add_tool_row(t, uid, dia, data=None):
    t.iso_tools[uid] = {'tooldia': dia, 'data': deepcopy(data if data is not None else t.default_data),
                        'solid_geometry': []}


def select_uid(t, uid):
    t.build_ui()
    for row in range(t.ui.tools_table.rowCount()):
        if int(t.ui.tools_table.item(row, 3).text()) == uid:
            t.ui.tools_table.setCurrentCell(row, 1)
            return row
    raise AssertionError('uid not in table')


SIGNALS = ('cutz_entry', 'tipdia_entry', 'tipangle_entry')


def own_receivers(t, name):
    return t.ui.__dict__[name].receivers(t.ui.__dict__[name].editingFinished)


def baseline(qapp):
    """Receivers a bare widget has on editingFinished (its own, not ours)."""
    ui = ToolIsolation(make_tool_app()).ui
    ui_receivers = {n: getattr(ui, n).receivers(getattr(ui, n).editingFinished) for n in SIGNALS}
    return ui_receivers


def our_receiver_count(t):
    """Number of connections of the 3 V signals that go to on_update_tool_dia (1 each when connected once)."""
    counts = {}
    for name in SIGNALS:
        widget = getattr(t.ui, name)
        n = widget.receivers(widget.editingFinished)
        # disconnect ours, see how many remain: the difference is our connection count
        ours = 0
        while True:
            try:
                widget.editingFinished.disconnect(t.on_update_tool_dia)
            except TypeError:
                break
            ours += 1
        counts[name] = (ours, n)
        for _ in range(ours):
            widget.editingFinished.connect(t.on_update_tool_dia)
    return {k: v[0] for k, v in counts.items()}


def assert_connected_once(t):
    assert our_receiver_count(t) == {n: 1 for n in SIGNALS}
    # total receivers = the widget's own receiver + ours
    for name in SIGNALS:
        widget = getattr(t.ui, name)
        assert widget.receivers(widget.editingFinished) == 2


def count_calls(t):
    calls = []
    real = ToolIsolation.on_update_tool_dia

    def wrapper():
        calls.append(1)
        return real(t)

    t.ui_disconnect()  # drop the connection to the original method first
    t.on_update_tool_dia = wrapper
    t.ui_connect()
    return calls


# ------------------------------------------------------------------ helper

# ------------------------------------------------------------------ on_update_tool_dia

def test_update_changes_diameter(tool):
    add_tool_row(tool, 1, 0.5)
    row = select_uid(tool, 1)
    tool.ui.tipdia_entry.set_value(0.2)
    tool.ui.tipangle_entry.set_value(60)
    tool.ui.cutz_entry.set_value(-0.1)
    tool.on_update_tool_dia()
    expected = v_dia(0.2, 60, -0.1)
    assert tool.iso_tools[1]['tooldia'] == expected
    assert tool.iso_tools[1]['data']['tools_iso_tooldia'] == expected
    assert float(tool.ui.tools_table.item(row, 1).text()) == expected
    assert_connected_once(tool)


def test_update_clash_with_other_tool_warns_and_keeps(tool):
    clash = v_dia(0.2, 60, -0.1)
    add_tool_row(tool, 1, 0.5)
    add_tool_row(tool, 2, clash)
    row = select_uid(tool, 1)
    tool.ui.tipdia_entry.set_value(0.2)
    tool.ui.tipangle_entry.set_value(60)
    tool.ui.cutz_entry.set_value(-0.1)
    tool.app.inform.emit.reset_mock()
    tool.on_update_tool_dia()
    assert tool.app.inform.emit.call_count == 1
    assert 'WARNING' in tool.app.inform.emit.call_args[0][0]
    assert tool.iso_tools[1]['tooldia'] == 0.5
    assert float(tool.ui.tools_table.item(row, 1).text()) == 0.5
    assert_connected_once(tool)


def test_one_edit_runs_handler_once(tool):
    add_tool_row(tool, 1, 0.5)
    select_uid(tool, 1)
    calls = count_calls(tool)
    for name in SIGNALS:
        del calls[:]
        getattr(tool.ui, name).editingFinished.emit()
        assert len(calls) == 1, name
    # also after the early-return paths and the normal path
    tool.ui.tools_table.setCurrentCell(-1, -1)
    tool.on_update_tool_dia()
    select_uid(tool, 1)
    tool.ui.tipdia_entry.set_value(0.3)
    tool.on_update_tool_dia()
    del calls[:]
    tool.ui.tipangle_entry.editingFinished.emit()
    assert len(calls) == 1


# ------------------------------------------------------------------ add paths

def test_default_add_zero_dia_v_shape(tool):
    tool.on_tool_default_add(dia=0)
    assert list(tool.iso_tools) == [1]
    expected = v_dia(0.1, 60, -0.1)
    assert tool.iso_tools[1]['tooldia'] == expected
    assert tool.iso_tools[1]['data']['tools_iso_tooldia'] == expected
    assert float(tool.ui.tools_table.item(0, 1).text()) == expected
    assert_connected_once(tool)


def test_default_add_zero_dia_not_v_shape_warns(tool):
    tool.default_data = v_data(shape=0)
    tool.app.inform.emit.reset_mock()
    tool.on_tool_default_add(dia=0)
    assert tool.iso_tools == {}
    assert 'WARNING' in tool.app.inform.emit.call_args[0][0]


def test_add_zero_dia_v_shape_from_defaults(tool):
    # empty Tools DB: no match, the default tool is added with the V diameter
    tool.on_tool_add(custom_dia=0)
    expected = v_dia(0.1, 60, -0.1)
    assert list(tool.iso_tools) == [1]
    assert tool.iso_tools[1]['tooldia'] == expected
    assert tool.iso_tools[1]['data']['tools_iso_tooldia'] == expected
    assert float(tool.ui.tools_table.item(0, 1).text()) == expected
    assert_connected_once(tool)


def test_add_zero_dia_final_diameter_from_matched_record(tool):
    provisional = v_dia(0.1, 60, -0.1)
    record = {'name': 'v', 'tooldia': provisional,
              'data': v_data(tip=0.2, angle=90, cut_z=-0.3)}
    record['data'].update(tool_target=3, tol_min=0.0, tol_max=0.0)
    other = {'name': 'other', 'tooldia': 5.0, 'data': v_data()}
    other['data'].update(tool_target=3, tol_min=0.0, tol_max=0.0)
    tool.db_path.write_text(json.dumps({'1': record, '2': other}), encoding='utf-8')

    loads = []
    module = sys.modules["appPlugins.ToolIsolation"]
    real_load = module.load_tools_database
    module.load_tools_database = lambda *a, **k: (loads.append(1), real_load(*a, **k))[1]
    try:
        tool.on_tool_add(custom_dia=0)
    finally:
        module.load_tools_database = real_load

    expected = v_dia(0.2, 90, -0.3)
    assert expected != provisional
    assert len(loads) == 1
    assert tool.iso_tools[1]['tooldia'] == expected
    assert tool.iso_tools[1]['data']['tools_iso_tooldia'] == expected
    assert tool.iso_tools[1]['data']['tools_mill_vtipdia'] == 0.2
    assert float(tool.ui.tools_table.item(0, 1).text()) == expected
    assert_connected_once(tool)

