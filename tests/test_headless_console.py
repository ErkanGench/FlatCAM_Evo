"""In headless mode the shell output goes to stdout, the errors go to stderr, without HTML."""

import io
from types import SimpleNamespace

from appCommon.Headless import HeadlessExit, console_text, console_write


def _write(style, text):
    out, err = io.StringIO(), io.StringIO()
    console_write(style, text, out=out, err=err)
    return out.getvalue(), err.getvalue()


def test_output_goes_to_stdout():
    assert _write('out', 'hello\n') == ('hello\n', '')
    assert _write('success', '[success] Saved\n') == ('[success] Saved\n', '')
    assert _write('warning', '[WARNING] careful\n') == ('[WARNING] careful\n', '')


def test_errors_go_to_stderr():
    assert _write('err', 'ERROR Report: boom\n') == ('', 'ERROR Report: boom\n')
    assert _write('out', '[ERROR_NOTCL] Failed\n') == ('', '[ERROR_NOTCL] Failed\n')


def test_only_critical_qt_messages_reach_stderr(capsys):
    from PyQt6 import QtCore
    from appCommon.Headless import headless_qt_message_handler
    headless_qt_message_handler(QtCore.QtMsgType.QtWarningMsg, None, 'QWidget::setMaximumSize: Negative sizes')
    headless_qt_message_handler(QtCore.QtMsgType.QtCriticalMsg, None, 'broken')
    assert capsys.readouterr().err == 'Qt: broken\n'


def test_the_shell_widget_writes_to_the_console_in_headless_mode(capsys):
    from appPlugins.ToolShell import TermWidget
    fake = SimpleNamespace(app=SimpleNamespace(headless_console=True))
    TermWidget._append_to_browser(fake, 'out', 'from the shell\n')
    assert capsys.readouterr().out == 'from the shell\n'
