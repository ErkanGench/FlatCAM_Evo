# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################
"""
The headless mode (flatcam.py --headless): the application runs a FlatScript, the --command text or a Tcl prompt on
stdin with no window and no OpenGL, writes the shell output to stdout / stderr and ends with an exit code.
"""

import html
import re
import sys


class HeadlessExit(BaseException):
    """
    Ends a headless run: quit_app and the Tcl exit. A BaseException because the Tcl command wrappers catch Exception.
    """

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


_TAG_RE = re.compile(r'<[^>]+>')


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
    if style == 'raw':
        text = console_text(text)
    is_error = style == 'err' or text.lstrip().upper().startswith('[ERROR')
    stream = (err or sys.stderr) if is_error else (out or sys.stdout)
    stream.write(text)
    stream.flush()
