"""ExcellonObject.on_plot_cb_click_table: update_visibility returns None; a tool without shapes is skipped."""
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers_objects import (  # noqa: F401,E402
    _headless_qt, make_app, make_app_0b, make_excellon, no_shape_collection,
)
from appObjects.ExcellonObject import ExcellonObject
from shapely.geometry import Point


class FakeShapes:
    def __init__(self):
        self.visibility_calls = []
        self.redraws = 0

    def update_visibility(self, state, indexes=None):
        self.visibility_calls.append((state, indexes))
        return None     # like the real implementations

    def redraw(self):
        self.redraws += 1


def _prepare(checked_by_tool, without_row=()):
    obj = make_excellon(make_app())
    tool_keys = list(obj.tools)
    obj.ui_connect = Mock()
    obj.ui_disconnect = Mock()
    obj.shapes = FakeShapes()

    items = {}
    cells = {}
    row = 0
    for key in tool_keys:
        if key in without_row:
            continue
        items[row] = Mock(text=Mock(return_value=str(key)))
        cells[row] = Mock(isChecked=Mock(return_value=checked_by_tool[key]))
        row += 1
    # like the real table: 2 total rows (drills, slots) with an empty id cell and no plot checkbox
    for _ in range(2):
        items[row] = Mock(text=Mock(return_value=''))
        cells[row] = None
        row += 1
    table = Mock()
    table.rowCount.return_value = row
    table.item.side_effect = lambda row, col: items[row]
    table.cellWidget.side_effect = lambda row, col: cells[row]
    obj.ui = Mock(tools_table=table)
    return obj, tool_keys


def test_visibility_is_set_per_tool_with_its_indexes():
    keys = list(make_excellon(make_app()).tools)
    assert len(keys) >= 2
    obj, keys = _prepare({k: (i % 2 == 0) for i, k in enumerate(keys)})
    obj.shape_indexes_dict = {k: [100 + i] for i, k in enumerate(keys)}

    obj.on_plot_cb_click_table()

    assert obj.shapes.visibility_calls == [(i % 2 == 0, [100 + i]) for i in range(len(keys))]
    assert obj.shapes.redraws == 1
    obj.ui_connect.assert_called_once()


def test_tool_without_a_table_row_keeps_its_visibility_and_reads_no_other_row():
    keys = list(make_excellon(make_app()).tools)
    assert len(keys) >= 3
    # the 2nd tool has no row; the 1st is checked, the 3rd is not
    checked = {k: (i == 0) for i, k in enumerate(keys)}
    obj, keys = _prepare(checked, without_row=(keys[1],))
    obj.shape_indexes_dict = {k: [100 + i] for i, k in enumerate(keys)}

    obj.on_plot_cb_click_table()

    expected = [(checked[k], [100 + i]) for i, k in enumerate(keys) if i != 1]
    assert obj.shapes.visibility_calls == expected
    assert obj.shapes.redraws == 1
    obj.ui_connect.assert_called_once()


def _plot_ready_excellon_object():
    app = make_app_0b()
    obj = ExcellonObject('exc', app)
    ui = Mock()
    ui.multicolored_cb.get_value.return_value = False
    ui.solid_cb.get_value.return_value = True
    ui.plot_cb.get_value.return_value = True
    obj.ui = ui
    obj.obj_options.update({'multicolored': False, 'solid': True, 'plot': True})
    obj.tools = {1: {'tooldia': 1.0, 'solid_geometry': [Point(0, 0).buffer(0.5)]}}
    obj.solid_geometry = [Point(0, 0).buffer(0.5)]
    obj.add_shapes_batch = Mock(return_value=[11])
    obj.shapes = Mock(_indexes=[])
    return obj


class TestSmallBugs_0B6:
    def test_excellon_plot_respects_explicit_visible_false(self, no_shape_collection):
        obj = _plot_ready_excellon_object()
        obj.plot(visible=False)
        assert obj.add_shapes_batch.called
        assert obj.add_shapes_batch.call_args.kwargs['visible'] is False
