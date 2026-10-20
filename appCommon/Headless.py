# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################
"""
The headless mode (flatcam.py --headless): the application runs a FlatScript, the --command text or a Tcl prompt on
stdin with no window and no OpenGL, writes the shell output to stdout / stderr and ends with an exit code.
"""

import html
import logging
import re
import sys
import tkinter as tk

from PyQt6 import QtCore


class HeadlessExit(BaseException):
    """
    Ends a headless run: quit_app and the Tcl exit. A BaseException because the Tcl command wrappers catch Exception.
    """

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


_TAG_RE = re.compile(r'<[^>]+>')


def quiet_logs(names=('base', 'base2')):
    """
    Lets only the warnings and errors of the application logs reach the console. A filter on the logger, not a level
    on a handler: AppLogging and camlib add their own handlers at DEBUG level.

    :param names: the names of the loggers
    :return: None
    """
    for name in names:
        logging.getLogger(name).addFilter(lambda record: record.levelno >= logging.WARNING)


def headless_qt_message_handler(message_type, context, message):
    """
    The Qt message handler of the headless mode: the widgets are never shown, so only the critical and fatal Qt
    messages are written to stderr.
    """
    if message_type in (QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
        sys.stderr.write('Qt: %s\n' % message)
        sys.stderr.flush()


def console_text(text):
    """
    :param text: a shell message that can hold HTML (the raw messages of help, get_path ...)
    :return: the plain text
    """
    text = text.replace('<br/>', '\n').replace('<br>', '\n')
    return html.unescape(_TAG_RE.sub('', text))


def console_write(style, text, out=None, err=None):
    """
    Writes a shell message to the console.

    :param style: the style of TermWidget._append_to_browser(): in, out, err, warning, success, selected or raw
    :param text: the message
    :param out: the stream for the output, default sys.stdout
    :param err: the stream for the errors, default sys.stderr
    :return: None
    """

    # 'in' is the echo of a typed command and the banner of the shell, 'selected' a canvas selection
    if style in ('in', 'selected') or not text:
        return
    # AppLogging copies each log message into the shell; the log itself reaches the console through quiet_logs()
    if text.startswith('[log]'):
        return
    if style == 'raw':
        text = console_text(text)
    is_error = style == 'err' or text.lstrip().upper().startswith('[ERROR')
    stream = (err or sys.stderr) if is_error else (out or sys.stdout)
    stream.write(text)
    stream.flush()


class HeadlessRunner:
    """
    Runs the job of a headless start in this order: --shellvar, --shellfile, --command. Without --shellfile and
    --command it reads Tcl commands from stdin (a prompt when stdin is a terminal).
    """

    def __init__(self, app, stdin=None, out=None, err=None):
        """
        :param app: the App, started with headless=True
        :param stdin: the stream of the prompt, default sys.stdin
        :param out: the stream for the output, default sys.stdout
        :param err: the stream for the errors, default sys.stderr
        """
        self.app = app
        self.tcl = app.shell.tcl
        self.stdin = stdin
        self.out = out
        self.err = err

    def run(self):
        """
        :return: the exit code: 0 done, 1 a Tcl command failed, N for 'exit N'
        """
        self.app.headless_console = True
        self._install_exit()
        try:
            try:
                for command in self.app.shellvar_commands():
                    self._eval(command, echo=False)
                if self.app.cmd_line_shellfile:
                    with open(self.app.cmd_line_shellfile, 'r') as f:
                        self._eval(f.read())
                if self.app.cmd_line_command:
                    self._eval(self.app.cmd_line_command)
                code = 0
                if not (self.app.cmd_line_shellfile or self.app.cmd_line_command):
                    code = self._prompt()
            except HeadlessExit as stop:
                code = stop.code
            except tk.TclError:
                code = 1
            self._wait_for_workers()
        finally:
            self._shutdown()
        return code

    def _install_exit(self):
        def tcl_exit(code='0'):
            self.app.headless_exit_code = int(code)
            raise HeadlessExit(int(code))

        # the Tcl exit would end the process at once, without stopping the process pool
        if self.tcl.eval('info commands flatcam_tcl_exit') == '' and self.tcl.eval('info commands exit') != '':
            self.tcl.eval('rename exit flatcam_tcl_exit')
        self.tcl.createcommand('exit', tcl_exit)

    def _eval(self, text, echo=True):
        """
        Runs Tcl code. A Tcl error is written to stderr and raised again; quit_app and exit raise HeadlessExit.
        """
        try:
            result = self.tcl.eval(text)
        except tk.TclError:
            if self.app.headless_exit_code is not None:
                raise HeadlessExit(self.app.headless_exit_code)
            console_write('err', 'ERROR Report: %s\n' % self.tcl.eval('set errorInfo'), out=self.out, err=self.err)
            raise
        if echo and result not in ('', 'None'):
            console_write('out', '%s\n' % result, out=self.out, err=self.err)
        return result

    def _prompt(self):
        """
        :return: 0, or 1 when a command failed; the prompt goes on after a failed command
        """
        stdin = self.stdin or sys.stdin
        out = self.out or sys.stdout
        interactive = stdin.isatty()
        failed = False
        buffer = ''
        while True:
            if interactive:
                out.write('> ' if buffer else '% ')
                out.flush()
            line = stdin.readline()
            if not line:
                break
            buffer += line
            if not self.tcl.getboolean(self.tcl.call('info', 'complete', buffer)):
                continue
            command, buffer = buffer, ''
            if not command.strip():
                continue
            try:
                self._eval(command)
            except tk.TclError:
                failed = True
        return 1 if failed else 0

    def _wait_for_workers(self):
        qapp = QtCore.QCoreApplication.instance()
        while True:
            if qapp is not None:
                qapp.processEvents()
            if self.app.workers.pending_count() == 0:
                break
            QtCore.QThread.msleep(20)
        if qapp is not None:
            qapp.processEvents()

    def _shutdown(self):
        try:
            self.app.pool.terminate()
            self.app.pool.join()
        except (ValueError, AttributeError):
            pass
        self.app.workers.quit()
        for stream in (self.out or sys.stdout, self.err or sys.stderr):
            stream.flush()
