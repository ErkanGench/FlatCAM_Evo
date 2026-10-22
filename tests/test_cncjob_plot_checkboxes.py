"""CNCJobObject: the object 'Plot' checkbox and the plot checkboxes of the tool table follow each other."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from appObjects.CNCJobObject import CNCJobObject
from tests.helpers_objects import _headless_qt, make_app_0b as make_app  # noqa: F401,E402


class FakeCheckBox:
    def __init__(self, checked):
        self.checked = checked
        self.clicked = Mock()
        self.stateChanged = Mock()

    def isChecked(self):
        return self.checked

    def setChecked(self, val):
        self.checked = bool(val)


class FakeTable:
    def __init__(self, rows):
        # rows: list of (diameter text, tool id text, checkbox or None)
        self.rows = rows

    def rowCount(self):
        return len(self.rows)

    def item(self, row, col):
        dia, tid, _cb = self.rows[row]
        return Mock(text=Mock(return_value=dia if col == 1 else tid))

    def cellWidget(self, row, col):
        return self.rows[row][2] if col == 6 else None


def make_job(kind, rows, plot=True):
    with patch('appObjects.AppObjectTemplate.ShapeCollection', Mock()):
        job = CNCJobObject('job', make_app())
    job.obj_options['type'] = kind
    job.obj_options['plot'] = plot
    job.muted_ui = False
    job.read_form_item = Mock()
    job.show_plotted_shapes = Mock(return_value=True)
    job.plot = Mock()
    job.plot2 = Mock()
    job.shapes = Mock()
    table = FakeTable(rows)
    empty = FakeTable([])
    job.ui = SimpleNamespace(
        plot_cb=FakeCheckBox(plot), cncplot_method_combo=Mock(get_value=Mock(return_value='all')),
        exc_cnc_tools_table=table if kind == 'excellon' else empty,
        cnc_tools_table=empty if kind == 'excellon' else table)
    job.tools = {int(tid): {'tooldia': float(dia), 'gcode_parsed': ['x']} for dia, tid, _cb in rows}
    return job, table


@pytest.mark.parametrize('kind', ['excellon', 'geometry'])
@pytest.mark.parametrize('plot', [True])
def test_object_plot_checkbox_sets_every_tool_checkbox(kind, plot):
    rows = [('0.8000', '1', FakeCheckBox(not plot)), ('1.0000', '2', FakeCheckBox(plot)),
            ('1.2000', '3', FakeCheckBox(not plot))]
    job, _ = make_job(kind, rows, plot=plot)
    job.on_plot_cb_click()
    assert [cb.isChecked() for _d, _t, cb in rows] == [plot, plot, plot]


@pytest.mark.parametrize('kind', ['excellon', 'geometry'])
def test_tool_checkboxes_set_the_object_plot_checkbox(kind):
    rows = [('0.8000', '1', FakeCheckBox(True)), ('1.0000', '2', FakeCheckBox(False))]
    job, _ = make_job(kind, rows, plot=True)
    job.on_plot_cb_click_table()
    assert job.ui.plot_cb.isChecked() is False
    # only the checked tool is plotted
    assert job.plot2.call_count == 1

    rows[1][2].setChecked(True)
    job.on_plot_cb_click_table()
    assert job.ui.plot_cb.isChecked() is True


@pytest.mark.parametrize('kind', ['all', 'cut', 'travel'])
def test_plot_kind_signal_keeps_a_reusable_full_plot(kind):
    from appObjects.AppObjectTemplate import FlatCAMObj

    job, _ = make_job('geometry', [('0.8000', '1', FakeCheckBox(True))])
    job.ui.cncplot_method_combo.get_value.return_value = kind
    job.multitool = True
    job.used_tools = [1]
    job.app.dec_format = round
    job.mark_full_plot = Mock()
    job.plot = CNCJobObject.plot.__get__(job)
    job.on_plot_kind_change(kind)
    task = job.app.worker_task.emit.call_args[0][0]
    with patch.object(FlatCAMObj, 'plot', return_value=True):
        task['fcn'](*task['params'])
    assert job.plot2.call_args.kwargs['kind'] == kind
    job.mark_full_plot.assert_called_once()
    assert job._full_plot_kind == kind


@pytest.mark.parametrize('kind', ['geometry', 'excellon'])
@pytest.mark.parametrize('multitool', [False])
def test_first_disable_reuses_a_plot_with_an_explicit_diameter(kind, multitool):
    from appObjects.AppObjectTemplate import FlatCAMObj

    job, _ = make_job(kind, [('0.8000', '1', FakeCheckBox(True))])
    job.multitool = multitool
    job.used_tools = [1]
    job.app.dec_format = round
    job.shapes._indexes = [1]
    job.shapes._collection.data = {1: {}}
    with patch.object(FlatCAMObj, 'plot', return_value=True):
        CNCJobObject.plot(job, dia=0.6)
    job.show_plotted_shapes = CNCJobObject.show_plotted_shapes.__get__(job)
    job.obj_options['plot'] = False
    job.ui.plot_cb.setChecked(False)
    job.on_plot_cb_click()
    job.plot.assert_not_called()
    assert job.shapes.visible is False


@pytest.mark.parametrize('visible', [False, True])
@pytest.mark.parametrize('kind', ['cut'])
def test_project_plot_toggle_reuses_the_objects_selected_filter(kind, visible):
    from appHandlers.appPlotManager import AppPlotManager

    job, _ = make_job('geometry', [], plot=not visible)
    job.ui.plot_cb = Mock()
    job.set_form_item = Mock()
    job.ui.cncplot_method_combo.get_value.return_value = kind
    job.shapes._indexes = [1]
    job.shapes._collection.data = {1: {}}
    job.mark_full_plot()
    job._full_plot_kind = kind
    job.show_plotted_shapes = CNCJobObject.show_plotted_shapes.__get__(job)
    manager = SimpleNamespace(app=job.app, log=job.app.log, options={'cncjob_plot_kind': 'all'},
                              defaults=job.app.defaults, collection=Mock(), worker_task=job.app.worker_task,
                              proc_container=job.app.proc_container)
    toggle = AppPlotManager.enable_plots if visible else AppPlotManager.disable_plots
    toggle(manager, [job])
    task = manager.worker_task.emit.call_args[0][0]
    task['fcn'](*task['params'])
    job.plot.assert_not_called()
    assert job.shapes.visible is visible
