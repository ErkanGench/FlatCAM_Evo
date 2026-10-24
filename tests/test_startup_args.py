"""
A file given to FlatCAM on the command line (a double-click on a file associated with FlatCAM, or the command line
that a second launch sends to the open window) gets its type from its last extension only. Windows also picks the
program by the last extension: 'top_copper.tcl.gtl' is a Gerber and must not run as a Tcl script.

A Tcl script given this way runs only after a Yes; the default answer is No. The --shellfile option and the headless
runs do not go through App.on_startup_args().
"""

import os
import threading
import types
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PyQt6 import QtCore, QtGui, QtNetwork, QtTest, QtWidgets

import appMain
from appCommon import SingleInstance, StartDir
from appHandlers.appIO import appIO
from defaults import AppDefaults

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='module')
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _list_text(key):
    """the read-only text box of a file association list in Preferences -> Utilities, with the default list"""
    return SimpleNamespace(get_value=lambda: AppDefaults.factory_defaults[key])


def make_app(answer=False, f_handlers=None):
    """
    The parts of App that on_startup_args() uses.

    :param answer:  what the user answers to the 'Run this script?' question
    """
    ui = SimpleNamespace(
        util_pref_form=SimpleNamespace(
            fa_excellon_group=SimpleNamespace(exc_list_text=_list_text('fa_excellon')),
            fa_gcode_group=SimpleNamespace(gco_list_text=_list_text('fa_gcode')),
            fa_gerber_group=SimpleNamespace(grb_list_text=_list_text('fa_gerber'))),
        plot_tab_area=Mock(),
        plot_tab=Mock())
    app = SimpleNamespace(
        ui=ui,
        f_handlers=f_handlers if f_handlers is not None else Mock(),
        log=Mock(),
        inform=Mock(),
        app_quit=Mock(),
        defaults=Mock(),
        options={'units': 'MM'},
        preferencesUiManager=Mock(),
        regFK=None,
        ask_run_script_arg=Mock(return_value=answer))
    for name in ('_open_startup_items', '_open_startup_item', '_open_import_item', '_report_open_failure'):
        setattr(app, name, types.MethodType(getattr(appMain.App, name), app))
    return app


def run_args(app, args):
    appMain.App.on_startup_args(app, args)


def assert_no_command(app):
    app.app_quit.emit.assert_not_called()
    app.defaults.update.assert_not_called()
    app.preferencesUiManager.save_defaults.assert_not_called()


class TestFileType:
    @pytest.mark.parametrize('path', ['C:/boards/a.gtl', 'C:/boards/top_copper.FlatScript.gbr'])
    def test_gerber(self, path):
        app = make_app()
        run_args(app, [path])
        assert app.f_handlers.method_calls == [call.on_file_open_gerber(name=path)]
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

    @pytest.mark.parametrize('path', ['C:/boards/a.drl'])
    def test_excellon(self, path):
        app = make_app()
        run_args(app, [path])
        assert app.f_handlers.method_calls == [call.on_file_open_excellon(name=path)]
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

    @pytest.mark.parametrize('path', ['C:/boards/a.gcode'])
    def test_gcode(self, path):
        app = make_app()
        run_args(app, [path])
        assert app.f_handlers.method_calls == [call.on_file_open_gcode(name=path)]
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

    @pytest.mark.parametrize('path', ['C:/boards/a.FlatPrj'])
    def test_project(self, path):
        app = make_app()
        run_args(app, [path])
        app.f_handlers.open_project.assert_called_once_with(filename=path, run_from_arg=True)
        app.f_handlers.on_file_open_gerber.assert_not_called()
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

    def test_every_file_is_opened(self):
        app = make_app()
        run_args(app, ['C:/b/a.gtl', 'C:/b/a.drl', 'C:/b/b.gbr', 'C:/b/a.gcode'])
        assert app.f_handlers.method_calls == [call.on_file_open_gerber(name='C:/b/a.gtl'),
                                               call.on_file_open_excellon(name='C:/b/a.drl'),
                                               call.on_file_open_gerber(name='C:/b/b.gbr'),
                                               call.on_file_open_gcode(name='C:/b/a.gcode')]

    @pytest.mark.parametrize('path', ['C:/boards/a.FlatPrj.bak', 'C:/board.tcl/readme'])
    def test_unknown_extension_opens_nothing(self, path):
        app = make_app()
        run_args(app, [path])
        assert app.f_handlers.method_calls == []
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

class TestOrderAndErrors:
    @staticmethod
    def _handlers():
        # a project load that ends when the test emits project_load_done
        class Handlers(QtCore.QObject):
            project_load_done = QtCore.pyqtSignal(bool, str, list)

        handlers = Handlers()
        handlers.open_project = Mock()
        handlers.on_file_open_gerber = Mock()
        return handlers

    def test_objects_wait_for_the_project_before_them(self, qapp):
        handlers = self._handlers()
        app = make_app(f_handlers=handlers)
        run_args(app, ['C:/b/one.flatprj', 'C:/b/a.gtl', 'C:/b/two.flatprj', 'C:/b/b.gtl'])
        handlers.open_project.assert_called_once_with(filename='C:/b/one.flatprj', run_from_arg=True)
        handlers.on_file_open_gerber.assert_not_called()

        handlers.project_load_done.emit(True, 'C:/b/one.flatprj', [])
        handlers.on_file_open_gerber.assert_called_once_with(name='C:/b/a.gtl')
        assert handlers.open_project.call_count == 2

        handlers.project_load_done.emit(True, 'C:/b/two.flatprj', [])
        assert handlers.on_file_open_gerber.call_count == 2

    def test_load_that_never_ends_does_not_block_the_next_file(self, qapp):
        from PyQt6 import QtTest
        handlers = self._handlers()
        app = make_app(f_handlers=handlers)
        app.options['global_background_timeout'] = 50
        run_args(app, ['C:/b/one.flatprj', 'C:/b/a.gtl'])
        handlers.on_file_open_gerber.assert_not_called()
        # the end of another request is not the awaited one
        handlers.project_load_done.emit(False, 'C:/b/other.flatprj', [])
        handlers.on_file_open_gerber.assert_not_called()
        QtTest.QTest.qWait(300)
        handlers.on_file_open_gerber.assert_called_once_with(name='C:/b/a.gtl')
        assert 'WARNING' in app.inform.emit.call_args[0][0]

    def test_same_file_opens_once(self):
        app = make_app()
        run_args(app, ['C:/b/a.gtl', 'C:/b/a.gtl', 'file:///C:/b/a.gtl'])
        assert app.f_handlers.on_file_open_gerber.call_count == 1

    def test_failure_is_shown_to_the_user(self, monkeypatch):
        shown = []
        monkeypatch.setattr(QtWidgets.QMessageBox, 'critical', lambda *a: shown.append(a[2]))
        f_handlers = Mock()
        f_handlers.open_project.side_effect = RuntimeError('corrupt')
        app = make_app(f_handlers=f_handlers)
        run_args(app, ['C:/b/a.flatprj'])
        assert len(shown) == 1 and 'a.flatprj' in shown[0] and 'corrupt' in shown[0]
        assert 'ERROR' in app.inform.emit.call_args[0][0]


class TestOpenRequests:
    def _app(self, modal=None):
        app = SimpleNamespace(
            _open_requests=deque(), _open_busy=False, _open_retry_pending=False, _version_check_due=False,
            qapp=SimpleNamespace(activeModalWidget=lambda: modal[0] if modal else None),
            on_startup_args=Mock(), log=Mock(), version=1.0, _queue_version_check=Mock())
        for name in ('open_files_request', '_drain_open_requests', '_retry_open_requests', '_open_request_done',
                     '_start_deferred_version_check'):
            setattr(app, name, types.MethodType(getattr(appMain.App, name), app))
        return app

    def test_files_wait_while_a_dialog_is_open(self, qapp):
        modal = [object()]
        app = self._app(modal)
        app.open_files_request(['C:/a.gtl'])
        app.on_startup_args.assert_not_called()
        modal.clear()
        app._retry_open_requests()
        app.on_startup_args.assert_called_once()

    def test_requests_run_one_at_a_time(self, qapp):
        app = self._app()
        app.open_files_request(['C:/a.gtl'])
        app.open_files_request(['C:/b.gtl'])
        assert app.on_startup_args.call_count == 1
        app.on_startup_args.call_args.kwargs['on_done']()
        assert app.on_startup_args.call_count == 2

    def test_update_check_waits_for_the_files(self, qapp):
        app = self._app()
        app._version_check_due = True
        app.open_files_request(['C:/a.gtl'])
        app._queue_version_check.assert_not_called()
        app.on_startup_args.call_args.kwargs['on_done']()
        app._queue_version_check.assert_called_once_with()


class TestRecent:
    def test_reopened_file_moves_to_the_top(self):
        app = SimpleNamespace(
            log=Mock(), recent=[{'kind': 'Gerber', 'filename': 'b'}, {'kind': 'Gerber', 'filename': 'a'}],
            recent_projects=[], options={'global_recent_limit': 10}, defaults={},
            app_obj=SimpleNamespace(load_batches=True))
        appMain.App.register_recent(app, 'Gerber', 'a')
        assert [r['filename'] for r in app.recent] == ['a', 'b']


class TestPaths:
    def test_file_url_and_relative_names(self, tmp_path):
        target = tmp_path / 'a b.gtl'
        target.write_text('x')
        assert StartDir.absolute_paths([target.as_uri(), 'new.gtl', 'quit'], start_dir=str(tmp_path)) == [
            os.path.normpath(str(target)), os.path.normpath(str(tmp_path / 'new.gtl')), 'quit']

    def test_filter_takes_a_path_once(self, qapp):
        flt = SingleInstance.FileOpenFilter()
        got = []
        flt.files_received.connect(got.append)
        for path in ('C:/a.gbr', 'C:/a.gbr', 'C:/b.gbr'):
            flt.eventFilter(None, SimpleNamespace(type=lambda: QtCore.QEvent.Type.FileOpen, file=lambda p=path: p))
        flt.set_ready(skip=['C:/b.gbr'])
        assert got == [['C:/a.gbr']]


class TestCommandWords:
    @pytest.mark.parametrize('word', ['quit'])
    def test_quit(self, word):
        app = make_app()
        run_args(app, [word])
        app.app_quit.emit.assert_called_once_with()
        assert app.f_handlers.method_calls == []
        app.defaults.update.assert_not_called()

    def test_save_then_quit(self):
        app = make_app()
        run_args(app, ['save', 'quit'])
        app.preferencesUiManager.save_defaults.assert_called_once_with()
        app.app_quit.emit.assert_called_once_with()

class TestScriptArgument:
    @pytest.mark.parametrize('path', ['C:/scripts/a.tcl', 'C:/scripts/a.flatscript'])
    def test_no_does_not_run_the_script(self, path):
        app = make_app(answer=False)
        run_args(app, [path])
        app.ask_run_script_arg.assert_called_once_with(path)
        # it is opened in the Code Editor, where the user can read it, and not run
        assert app.f_handlers.method_calls == [call.on_file_open_script(name=path)]
        app.f_handlers.on_file_run_script.assert_not_called()

    @pytest.mark.parametrize('path', ['C:/scripts/a.tcl'])
    def test_yes_runs_the_script(self, path):
        app = make_app(answer=True)
        run_args(app, [path])
        app.ask_run_script_arg.assert_called_once_with(path)
        assert app.f_handlers.method_calls == [call.on_file_open_script(name=path),
                                               call.on_file_run_script(name=path)]

    @pytest.mark.parametrize('answer', [False, True])
    def test_the_script_reaches_the_tcl_shell_only_after_a_yes(self, tmp_path, answer):
        # the real File -> Run Script handler: it gives the text of the script to the Tcl shell
        script = tmp_path / 'job.tcl'
        script.write_text('puts marker\n', encoding='utf-8')
        io = Mock()
        io.app.used_time = 0.0
        io.app.ui.shell_dock.isHidden.return_value = False
        f_handlers = SimpleNamespace(
            on_file_open_script=Mock(),
            on_file_run_script=lambda name=None, silent=False: appIO.on_file_run_script(io, name=name, silent=silent))

        app = make_app(answer=answer, f_handlers=f_handlers)
        run_args(app, [str(script)])

        if answer:
            io.app.shell.exec_command.assert_called_once_with('puts marker\n')
        else:
            io.app.shell.exec_command.assert_not_called()


class TestSingleInstance:
    """The files of a second launch reach the open instance, whatever else is sent to its socket."""

    @pytest.fixture
    def name(self, qapp, monkeypatch):
        unique = 'FlatCAM_EVO-test-%d' % os.getpid()
        monkeypatch.setattr(SingleInstance, 'server_name', lambda: unique)
        return unique

    @staticmethod
    def _run_client(fn, received, count):
        """
        The second launch is another process: run its side in a thread, so that the event loop of the server serves it.
        """
        result = []
        thread = threading.Thread(target=lambda: result.append(fn()))
        thread.start()
        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: loop.quit() if len(received) >= count and not thread.is_alive() else None)
        QtCore.QTimer.singleShot(3000, loop.quit)
        timer.start()
        loop.exec()
        timer.stop()
        thread.join(3)
        return result[0] if result else None

    def test_files_arrive(self, name):
        server = SingleInstance.InstanceServer()
        received = []
        server.files_received.connect(received.append)
        assert server.start()
        server.set_ready()
        try:
            sent = self._run_client(
                lambda: SingleInstance.send_to_running(['C:/a.gbr', 'C:/b.drl'], 3000), received, 1)
            assert sent is True
            assert received == [['C:/a.gbr', 'C:/b.drl']]
        finally:
            server.close()

    def test_second_server_does_not_take_the_name(self, name):
        first = SingleInstance.InstanceServer()
        received = []
        first.files_received.connect(received.append)
        assert first.start()
        first.set_ready()
        second = SingleInstance.InstanceServer()
        try:
            assert second.start() is False
            sent = self._run_client(lambda: SingleInstance.send_to_running(['C:/a.gbr'], 3000), received, 1)
            assert sent is True
            assert received == [['C:/a.gbr']]
        finally:
            second.close()
            first.close()

    def test_files_wait_until_the_app_is_ready(self, name):
        server = SingleInstance.InstanceServer()
        received = []
        server.files_received.connect(received.append)
        assert server.start()
        try:
            assert self._run_client(lambda: SingleInstance.send_to_running(['C:/a.gbr'], 3000), received, 0) is True
            QtTest.QTest.qWait(300)
            assert received == []
            server.set_ready()
            assert received == [['C:/a.gbr']]
        finally:
            server.close()

    def test_no_answer_means_not_delivered(self, name):
        # a process that holds the socket but does not answer: the launch must not exit on it
        silent = QtNetwork.QLocalServer()
        assert silent.listen(name)
        try:
            assert self._run_client(
                lambda: SingleInstance.send_to_running(['C:/a.gbr'], 1000, ack_timeout_ms=300), [], 0) is False
        finally:
            silent.close()

    def test_no_instance_running(self, name):
        assert SingleInstance.send_to_running(['C:/a.gbr']) is False

    def test_bad_client_does_not_stop_the_server(self, name):
        server = SingleInstance.InstanceServer()
        received = []
        server.files_received.connect(received.append)
        assert server.start()
        server.set_ready()

        def client():
            for junk in (b'\xff\xfe not json\n', b'[1, 2]\n', b'{"files": "a.gbr"}\n', b'{"files": [1]}\n'):
                sock = QtNetwork.QLocalSocket()
                sock.connectToServer(name)
                assert sock.waitForConnected(1000)
                sock.write(junk)
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
            return SingleInstance.send_to_running(['C:/a.gbr'], 3000)

        try:
            assert self._run_client(client, received, 1) is True
            assert received == [['C:/a.gbr']]
        finally:
            server.close()

    def test_sender_that_gave_up_is_not_served(self, name):
        # the sender opens the files itself after its deadline, or when it goes before the answer: no second copy
        server = SingleInstance.InstanceServer()
        received = []
        server.files_received.connect(received.append)
        assert server.start()
        server.set_ready()

        def client():
            for message in (b'{"files": ["C:/late.gbr"], "deadline": 1.0}\n', b'{"files": ["C:/cut.gbr"]}'):
                sock = QtNetwork.QLocalSocket()
                sock.connectToServer(name)
                assert sock.waitForConnected(1000)
                sock.write(message)
                sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
            return True

        try:
            self._run_client(client, received, 0)
            QtTest.QTest.qWait(SingleInstance.RELEASE_DELAY_MS + 300)
            assert received == []
        finally:
            server.close()


class TestRunScriptQuestion:
    @pytest.fixture
    def app(self, qapp):
        return SimpleNamespace(ui=None, resource_location=os.path.join(REPO, 'assets', 'resources'))

    def _ask(self, app, monkeypatch, action, path='C:/scripts/job.tcl'):
        seen = {}

        def fake_exec(msgbox):
            seen['default'] = msgbox.buttonRole(msgbox.defaultButton())
            seen['text'] = msgbox.text() + '\n' + msgbox.informativeText()
            seen['informative'] = msgbox.informativeText()
            action(msgbox)
            return 0

        monkeypatch.setattr(appMain.FCMessageBox, 'exec', fake_exec)
        result = appMain.App.ask_run_script_arg(app, path)
        return result, seen

    def test_default_answer_is_no(self, app, monkeypatch):
        # Enter clicks the default button
        result, seen = self._ask(app, monkeypatch, lambda box: box.defaultButton().click())
        assert seen['default'] == QtWidgets.QMessageBox.ButtonRole.NoRole
        assert result is False
        assert 'C:/scripts/job.tcl' in seen['text']

    def test_yes(self, app, monkeypatch):
        def click_yes(box):
            yes = [b for b in box.buttons() if box.buttonRole(b) == QtWidgets.QMessageBox.ButtonRole.YesRole]
            assert len(yes) == 1
            yes[0].click()

        result, _seen = self._ask(app, monkeypatch, click_yes)
        assert result is True
