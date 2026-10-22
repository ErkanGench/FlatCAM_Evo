"""Custom Origin must keep dialogs/widgets/camera on the GUI thread."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets
from shapely import affinity
from shapely.geometry import box

from appCommon.Common import LoudDict
from appHandlers.appEdit import appEditor
from appHandlers.appSignalConnector import AppSignalConnector
from test_move2origin_responsiveness import make_app, wait_for


@pytest.fixture(scope='module')
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Layer:
    def __init__(self, x, y, events, threads, block=None):
        self.geometry = box(x, y, x + 2.0, y + 3.0)
        self.events = events
        self.threads = threads
        self.block = block
        self.gui_thread = QtCore.QThread.currentThread()
        self.offset_entry = QtWidgets.QLineEdit()
        self.obj_options = LoudDict()
        self.obj_options['name'] = 'layer'
        self.obj_options.set_change_callback(lambda key: self.record('metadata'))
        self.source_file = 'original'

    def record(self, phase):
        self.events.append(phase)
        self.threads.append((phase, QtCore.QThread.currentThread()))

    def bounds(self):
        self.record('bounds')
        return self.geometry.bounds

    def offset(self, vector):
        self.record('offset')
        self.geometry = affinity.translate(self.geometry, xoff=vector[0], yoff=vector[1])

    def plot(self):
        self.record('plot')
        self.plotted_geometry = self.geometry

    def regenerate_source(self):
        self.record('export_start')
        if self.block is not None:
            entered, release = self.block
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test did not release exporter')
        self.source_file = self.geometry.wkt
        self.record('export_done')

    def set_offset_values(self, bounds=None):
        self.record('ui')
        # Record the old unsafe call without making a native cross-thread Qt
        # widget write in the failing regression run.
        if QtCore.QThread.currentThread() is self.gui_thread:
            self.offset_entry.setText(str(bounds if bounds is not None else self.bounds()))


class Worker(QtCore.QThread):
    def __init__(self, task):
        super().__init__()
        self.task = task
        self.errors = []

    def run(self):
        try:
            self.task['fcn'](*self.task['params'])
        except Exception as error:
            self.errors.append(error)


def setup_operation():
    app = make_app()
    app.resource_location = 'assets/resources'
    app.should_we_save = False
    events, threads, tasks = [], [], []
    app.inform.emit.side_effect = events.append
    app.worker_task.emit.side_effect = tasks.append
    controller = appEditor(app)
    app.edit_class = controller
    return app, controller, events, threads, tasks


def test_real_center_action_uses_qthread_and_gui_completion_after_export(qt_app):
    app, controller, events, threads, tasks = setup_operation()
    entered, release, fit_ready = threading.Event(), threading.Event(), threading.Event()
    first = Layer(10.0, 30.0, events, threads, (entered, release))
    second = Layer(25.0, 5.0, events, threads)
    outsider = Layer(100.0, 100.0, events, threads)
    app.collection.get_selected.return_value = [first, second]

    def get_selected():
        threads.append(('selection', QtCore.QThread.currentThread()))
        return app.collection.get_selected.return_value

    app.collection.get_selected.side_effect = get_selected
    action = QtGui.QAction('Center in Origin')
    app.ui.menuedit_center_in_origin = action
    checked = []
    action.triggered.connect(checked.append)
    connector = AppSignalConnector(app)
    connector.connect_editmenu_signals()
    gui_thread = QtCore.QThread.currentThread()
    dialog_threads = []

    def dialog(**kwargs):
        dialog_threads.append(QtCore.QThread.currentThread())
        assert kwargs['default_choice'] == 'c'
        return SimpleNamespace(ok=True, location_point='c')

    def fit(**kwargs):
        threads.append(('fit', QtCore.QThread.currentThread()))
        return fit_ready.is_set()

    app.plotcanvas.fit_view.side_effect = fit
    with patch('appHandlers.appEdit.DialogBoxChoice', side_effect=dialog):
        action.trigger()
    assert checked == [False]
    assert len(tasks) == 1
    assert dialog_threads == [gui_thread]
    app.collection.get_selected.return_value = [outsider]
    worker = Worker(tasks[0])
    ticks = []
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    worker.start()
    try:
        wait_for(entered.is_set)
        wait_for(lambda: len(ticks) >= 3)
        assert not any(phase in ('ui', 'metadata', 'fit') for phase, thread in threads)
        assert not any('Origin set' in event for event in events)
    finally:
        release.set()
        assert worker.wait(3000)
        heartbeat.stop()
    assert not worker.errors
    previous_ticks = len(ticks)
    heartbeat.start()
    try:
        wait_for(lambda: app.plotcanvas.fit_view.call_count >= 2 and len(ticks) >= previous_ticks + 3)
        assert not any('Origin set' in event for event in events)
        app.delete_selection_shape.assert_called_once_with()
    finally:
        heartbeat.stop()
        fit_ready.set()
    wait_for(lambda: any('Origin set' in event for event in events))
    assert sum('Origin set' in event for event in events) == 1
    app.delete_selection_shape.assert_called_once_with()
    assert all(thread is worker for phase, thread in threads if phase in ('bounds', 'offset', 'plot',
                                                                         'export_start', 'export_done'))
    assert all(thread is gui_thread for phase, thread in threads if phase in ('selection', 'ui', 'metadata', 'fit'))
    app.collection.get_selected.assert_called_once_with()
    assert all(call.kwargs == {'blocking': False} for call in app.plotcanvas.fit_view.call_args_list)
    assert first.geometry.bounds == pytest.approx((-8.5, 11.0, -6.5, 14.0))
    assert second.geometry.bounds == pytest.approx((6.5, -14.0, 8.5, -11.0))
    assert outsider.geometry.bounds == (100.0, 100.0, 102.0, 103.0)
    assert first.source_file == first.plotted_geometry.wkt == first.geometry.wkt
    assert second.source_file == second.plotted_geometry.wkt == second.geometry.wkt
    assert events.count('ui') == 2
    assert events.index('ui') > max(index for index, event in enumerate(events) if event == 'export_done')
    app.app_obj.object_changed.emit.assert_not_called()


@pytest.mark.parametrize('mode, origin', [
    ('bl', (10.0, 5.0)), ('tl', (10.0, 33.0)),
    ('br', (27.0, 5.0)), ('tr', (27.0, 33.0)), ('c', (18.5, 19.0)),
])
def test_corner_and_center_modes_keep_group_offsets_and_explicit_inline_execution(qt_app, mode, origin):
    app, controller, events, threads, tasks = setup_operation()
    objects = [Layer(10.0, 30.0, events, threads), Layer(25.0, 5.0, events, threads)]
    before = [obj.geometry for obj in objects]
    app.collection.get_selected.return_value = objects
    with patch('appHandlers.appEdit.DialogBoxChoice', return_value=SimpleNamespace(ok=True, location_point=mode)):
        controller.on_custom_origin(use_thread=False)
    assert tasks == []
    for obj, original in zip(objects, before):
        expected = affinity.translate(original, xoff=-origin[0], yoff=-origin[1])
        assert obj.geometry.equals_exact(expected, 1e-9)
        assert obj.plotted_geometry.equals_exact(expected, 1e-9)
        assert obj.source_file == expected.wkt
        assert tuple(obj.obj_options[key] for key in ('xmin', 'ymin', 'xmax', 'ymax')) == expected.bounds
        assert obj.offset_entry.text() == str(expected.bounds)
    assert all(thread is QtCore.QThread.currentThread() for phase, thread in threads)
    app.plotcanvas.fit_view.assert_called_once_with()
    app.delete_selection_shape.assert_called_once_with()
    app.app_obj.object_changed.emit.assert_not_called()
    assert app.should_we_save is True


def test_regeneration_failure_refreshes_bounds_but_does_not_report_success(qt_app):
    app, controller, events, threads, tasks = setup_operation()
    obj = Layer(10.0, 30.0, events, threads)
    obj.regenerate_source = Mock(side_effect=ValueError('export failed'))
    app.collection.get_selected.return_value = [obj]
    with patch('appHandlers.appEdit.DialogBoxChoice', return_value=SimpleNamespace(ok=True, location_point='bl')):
        controller.on_custom_origin(use_thread=False)
    assert 'export failed' in app.inform.emit.call_args.args[0]
    assert not any('Origin set' in event for event in events)
    assert obj.obj_options['xmin'] == 0.0
    app.plotcanvas.fit_view.assert_not_called()
