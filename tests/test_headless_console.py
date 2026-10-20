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


def test_selected_and_input_echo_are_not_written():
    assert _write('selected', 'x\n') == ('', '')
    assert _write('in', '> help\n') == ('', '')


def test_the_log_copy_in_the_shell_is_not_written():
    # AppLogging copies each log message into the shell as '[log]...'; the log itself already reaches stderr
    assert _write('out', '[log]DEBUG 20261020_033744 ***\tAppObject.new_object()\n') == ('', '')


def test_quiet_logs_lets_only_warnings_and_errors_pass():
    import logging
    from appCommon.Headless import quiet_logs
    stream = io.StringIO()
    logger = logging.getLogger('test_headless_quiet')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler(stream))
    quiet_logs(('test_headless_quiet',))
    # a handler added after quiet_logs() (AppLogging does this) is filtered too
    logger.addHandler(logging.StreamHandler(stream))
    logger.debug('no')
    logger.info('no')
    logger.warning('yes')
    assert stream.getvalue() == 'yes\nyes\n'


def test_only_critical_qt_messages_reach_stderr(capsys):
    from PyQt6 import QtCore
    from appCommon.Headless import headless_qt_message_handler
    headless_qt_message_handler(QtCore.QtMsgType.QtWarningMsg, None, 'QWidget::setMaximumSize: Negative sizes')
    headless_qt_message_handler(QtCore.QtMsgType.QtCriticalMsg, None, 'broken')
    assert capsys.readouterr().err == 'Qt: broken\n'


def test_raw_html_is_plain_text():
    assert console_text('<b>a</b><br>b &amp; c<br/>') == 'a\nb & c\n'
    assert _write('raw', '<span>x</span>\n') == ('x\n', '')


def test_headless_exit_is_not_an_exception():
    # the Tcl command wrappers catch Exception; HeadlessExit must pass through them
    assert not issubclass(HeadlessExit, Exception)
    assert HeadlessExit(3).code == 3


def test_the_shell_widget_writes_to_the_console_in_headless_mode(capsys):
    from appPlugins.ToolShell import TermWidget
    fake = SimpleNamespace(app=SimpleNamespace(headless_console=True))
    TermWidget._append_to_browser(fake, 'out', 'from the shell\n')
    assert capsys.readouterr().out == 'from the shell\n'
