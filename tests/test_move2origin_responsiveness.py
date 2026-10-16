"""Real Qt action dispatch and worker/GUI completion boundaries for group moves."""

import threading
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets, QtTest

from appHandlers.appObjectOps import AppObjectOps
from appHandlers.appSignalConnector import AppSignalConnector


@pytest.fixture(scope='module')
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_app():
    app = Mock()
    app.options = {}
    app.defaults = {}
    app.ui = Mock()
    app.collection.get_selected.return_value = []
    app.proc_container.new.side_effect = lambda text: nullcontext()
    app.use_3d_engine = False
    app.ui.pop_menucolor.actions.return_value = []
    return app


@pytest.mark.parametrize('context_menu', [False, True])
def test_real_move_action_does_not_pass_checked_as_use_thread(qt_app, context_menu):
    app = make_app()
    app.ui.menuedit_move2origin = QtGui.QAction('Move2Origin')
    app.ui.popmenu_move2origin = QtGui.QAction('Move2Origin')
    app.collection.get_selected.return_value = [Layer(10.0, [], []), Layer(20.0, [], [])]
    ops = AppObjectOps(app)
    app.on_move2origin = ops.on_move2origin
    connector = AppSignalConnector(app)
    if context_menu:
        connector.connect_canvas_context_signals()
        action = app.ui.popmenu_move2origin
    else:
        connector.connect_editmenu_signals()
        action = app.ui.menuedit_move2origin
    action.trigger()
    app.worker_task.emit.assert_called_once()


class Layer:
    def __init__(self, x, events, threads, entered=None, release=None):
        self.x = x
        self.obj_options = {}
        self.events = events
        self.threads = threads
        self.entered = entered
        self.release = release
        self.offset_entry = QtWidgets.QLineEdit()

    def bounds(self):
        return self.x, 5.0, self.x + 1.0, 6.0

    def offset(self, vector):
        self.threads.append(('offset', QtCore.QThread.currentThread()))
        self.x += vector[0]

    def plot(self):
        self.threads.append(('plot', QtCore.QThread.currentThread()))
        self.events.append('plot')

    def regenerate_source(self):
        self.threads.append(('export', QtCore.QThread.currentThread()))
        if self.entered is not None:
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError('test did not release exporter')
        self.events.append('export')

    def set_offset_values(self, bounds=None):
        self.threads.append(('ui', QtCore.QThread.currentThread()))
        self.offset_entry.setText(str(bounds if bounds is not None else self.bounds()))
        self.events.append('ui')


def wait_for(predicate):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while not predicate() and timer.elapsed() < 2000:
        QtTest.QTest.qWait(1)
    assert predicate(), 'Qt completion timed out'


def test_group_move_keeps_gui_alive_and_finalizes_after_export(qt_app):
    app = make_app()
    events, threads, tasks, ticks = [], [], [], []
    entered, release = threading.Event(), threading.Event()
    first = Layer(10.0, events, threads, entered, release)
    second = Layer(20.0, events, threads)
    outsider = Layer(100.0, events, threads)
    app.collection.get_selected.return_value = [first, second]
    app.worker_task.emit.side_effect = tasks.append
    app.plotcanvas.fit_view.side_effect = lambda **kwargs: threads.append(('fit', QtCore.QThread.currentThread()))
    app.inform.emit.side_effect = lambda text: events.append(text)
    ops = AppObjectOps(app)
    ops.on_move2origin()
    app.collection.get_selected.return_value = [outsider]
    gui_thread = QtCore.QThread.currentThread()
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    worker = threading.Thread(target=lambda: tasks[0]['fcn'](*tasks[0]['params']), daemon=True)
    worker.start()
    try:
        wait_for(entered.is_set)
        wait_for(lambda: len(ticks) >= 3)
        assert not any(name == 'ui' or name == 'fit' for name, thread in threads)
        assert not any('Origin set' in event for event in events)
    finally:
        release.set()
        worker.join(3)
        heartbeat.stop()
    assert not worker.is_alive()
    wait_for(lambda: any('Origin set' in event for event in events))
    assert first.x == 0.0 and second.x == 10.0 and outsider.x == 100.0
    assert events.index('ui') > max(index for index, event in enumerate(events) if event == 'export')
    assert all(thread is not gui_thread for name, thread in threads if name in ('offset', 'plot', 'export'))
    assert all(thread is gui_thread for name, thread in threads if name in ('ui', 'fit'))
    assert first.obj_options['xmin'] == 0.0
    assert first.offset_entry.text() == str((0.0, 5.0, 1.0, 6.0))
    app.delete_selection_shape.assert_called_once_with()


def test_busy_plot_lock_retries_fit_without_blocking_gui_or_repeating_refresh(qt_app):
    from appGUI.PlotCanvas import PlotCanvas

    app = make_app()
    app.use_3d_engine = True
    events, threads, ticks, tasks = [], [], [], []
    layer = Layer(10.0, events, threads)
    app.collection.get_selected.return_value = [layer]
    app.worker_task.emit.side_effect = tasks.append
    app.inform.emit.side_effect = events.append
    lock = threading.Lock()
    collection = SimpleNamespace(
        update_lock=lock, bounds=lambda axis: (0.0, 10.0),
        lock_updates=Mock(side_effect=AssertionError('GUI must not wait for a plot lock')),
        unlock_updates=lock.release)
    canvas = SimpleNamespace(shape_collection=collection, view=SimpleNamespace(camera=SimpleNamespace(rect=None)))
    app.plotcanvas = canvas
    canvas.fit_view = lambda **kwargs: PlotCanvas.fit_view(canvas, **kwargs)
    ops = AppObjectOps(app)
    heartbeat = QtCore.QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    lock.acquire()
    heartbeat.start()
    try:
        ops.on_move2origin()
        worker = threading.Thread(target=lambda: tasks[0]['fcn'](*tasks[0]['params']))
        worker.start()
        worker.join(2)
        assert not worker.is_alive()
        wait_for(lambda: len(ticks) >= 3 and app.delete_selection_shape.called)
        assert canvas.view.camera.rect is None
        assert not any('Origin set' in event for event in events)
    finally:
        lock.release()
        heartbeat.stop()
    wait_for(lambda: any('Origin set' in event for event in events))
    assert canvas.view.camera.rect is not None
    assert events.count('ui') == 1
    app.delete_selection_shape.assert_called_once_with()


@pytest.mark.parametrize('clear', [False, True])
def test_worker_progress_is_coalesced_on_gui_thread_and_preserves_clear(qt_app, clear):
    from appGUI.GUIElements import FlatCAMActivityView
    from appProcess import FCVisibleProcessContainer

    class View(FlatCAMActivityView):
        def __init__(self):
            QtWidgets.QWidget.__init__(self)
            self.label = QtWidgets.QLabel(self)
            self.messages = []

        def set_busy(self, msg, no_movie=None):
            self.messages.append((msg, QtCore.QThread.currentThread()))
            self.label.setText(msg)

        def set_idle(self):
            self.label.setText('Idle')

    view = View()
    container = FCVisibleProcessContainer(view, make_app())
    gui_thread = QtCore.QThread.currentThread()
    try:
        with container.new('Moving'):
            worker = threading.Thread(target=lambda: [container.update_view_text('%d%%' % index, clear=clear)
                                                      for index in range(200)])
            worker.start()
            worker.join(2)
            assert not worker.is_alive()
            assert not view.messages
            wait_for(lambda: bool(view.messages))
            expected = '199%' if clear else container.text_to_display_in_activity + '199%'
            assert view.messages == [(expected, gui_thread)]
            assert view.label.text() == expected
    finally:
        container._update_timer.stop()
        view.close()


def test_move_error_reports_after_worker_and_does_not_fit(qt_app):
    app = make_app()
    layer = Layer(10.0, [], [])
    layer.regenerate_source = Mock(side_effect=ValueError('export failed'))
    app.collection.get_selected.return_value = [layer]
    ops = AppObjectOps(app)
    ops.on_move2origin(use_thread=False)
    app.plotcanvas.fit_view.assert_not_called()
    assert 'export failed' in app.inform.emit.call_args.args[0]
