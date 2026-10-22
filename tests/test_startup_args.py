"""
A file given to FlatCAM on the command line (a double-click on a file associated with FlatCAM, or the command line
that a second launch sends to the open window) gets its type from its last extension only. Windows also picks the
program by the last extension: 'top_copper.tcl.gtl' is a Gerber and must not run as a Tcl script.

A Tcl script given this way runs only after a Yes; the default answer is No. The --shellfile option and the headless
runs do not go through App.on_startup_args().
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

import appMain
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
    return SimpleNamespace(
        ui=ui,
        f_handlers=f_handlers if f_handlers is not None else Mock(),
        log=Mock(),
        inform=Mock(),
        app_quit=Mock(),
        defaults=Mock(),
        options={'units': 'MM'},
        preferencesUiManager=Mock(),
        ask_run_script_arg=Mock(return_value=answer))


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
        assert app.f_handlers.method_calls == [call.open_project(filename=path, run_from_arg=True)]
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

    @pytest.mark.parametrize('path', ['C:/boards/a.FlatPrj.bak', 'C:/board.tcl/readme'])
    def test_unknown_extension_opens_nothing(self, path):
        app = make_app()
        run_args(app, [path])
        assert app.f_handlers.method_calls == []
        app.ask_run_script_arg.assert_not_called()
        assert_no_command(app)

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
