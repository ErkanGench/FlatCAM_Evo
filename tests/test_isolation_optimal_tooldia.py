"""Isolation plugin: the tool diameter found by the Optimal button (find_safe_tooldia_worker).

The distances between the copper polygons are rounded to the app decimals, so the smallest one can be up to half a unit
of the last decimal larger than the real gap (0.15996 -> 0.16). The tests build the real ToolIsolation headless
(offscreen Qt, MagicMock app) and drive the Optimal button and the Check validity step
(find_safe_tooldia_multiprocessing) on pads with known gaps.
"""

import functools
import os
import sys
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6 import QtWidgets  # noqa: E402
from shapely import box  # noqa: E402

from appMain import App  # noqa: E402
from defaults import AppDefaults  # noqa: E402
from appPlugins.ToolIsolation import ToolIsolation  # noqa: E402
from test_plugin_geometry_bases import make_tool_app  # noqa: E402

DEC = 4
UNIT = 10 ** -DEC


def gerber_tools(gap):
    # 3 pads; the smallest gap is between the first 2
    pads = [box(0, 0, 1, 1), box(1 + gap, 0, 2, 1), box(0, 1 + 3 * gap, 1, 2)]
    return {10: {'geometry': [{'solid': p} for p in pads]}}


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def tool(qapp):
    app = make_tool_app()
    app.abort_flag = False
    app.dec_format = functools.partial(App.dec_format, app)
    # run the jobs in place of the worker thread and of the process pool
    app.worker_task.emit.side_effect = lambda task: task['fcn'](*task['params'])
    app.pool.apply_async.side_effect = lambda fcn, args: MagicMock(get=lambda: fcn(*args))
    t = ToolIsolation(app)
    t.decimals = DEC
    app.collection = MagicMock()
    return t


def find_optimal(t, gap):
    t.app.collection.get_by_name.return_value = MagicMock(tools=gerber_tools(gap))
    found = []
    t.optimal_found_sig.connect(found.append)
    t.on_find_optimal_tooldia()
    t.optimal_found_sig.disconnect(found.append)
    return found[0] if found else None


def messages(t):
    return [c.args[0] for c in t.app.inform.emit.call_args_list]


@pytest.mark.parametrize('gap', [0.15996, 0.1, 0.2, 0.20004, 0.25, 0.123449, 0.30005])
def test_optimal_tool_fits_in_the_smallest_gap(tool, gap):
    dia = find_optimal(tool, gap)
    assert dia is not None
    assert dia < gap
    assert dia >= gap - 1.5 * UNIT - 1e-12
    assert dia == round(dia, DEC)
    # the Optimal button puts the diameter in the New Tool entry
    assert tool.ui.new_tooldia_entry.get_value() == dia


def test_gap_rounded_up_gives_a_tool_below_the_gap(tool):
    # 0.15996 is rounded to 0.1600; the Optimal button proposed a 0.16 tool, larger than the gap
    assert find_optimal(tool, 0.15996) == 0.1599
    assert any('0.1599' in m for m in messages(tool) if m.startswith('[success]'))


@pytest.mark.parametrize('gap', [0.15996, 0.2, 0.123449])
def test_optimal_tool_passes_the_check_validity(tool, gap):
    dia = find_optimal(tool, gap)
    data = {k: deepcopy(v) for k, v in AppDefaults().defaults.items() if k.startswith('tools_')}
    tool.iso_tools = {1: {'tooldia': dia, 'data': data, 'solid_geometry': []}}
    tool.build_ui()
    tool.app.inform.emit.reset_mock()
    tool.validation_status = True

    tool.find_safe_tooldia_multiprocessing()

    assert tool.validation_status is True
    assert 'Tool validation passed.' in messages(tool)
    assert not any(m.startswith('[WARNING]') for m in messages(tool))


def test_gap_below_the_resolution_gives_no_tool(tool):
    assert find_optimal(tool, 0.00004) is None
    assert tool.safe_tooldia is None
    assert any(m.startswith('[ERROR_NOTCL]') for m in messages(tool))
