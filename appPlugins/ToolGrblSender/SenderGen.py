# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""Job preparation of the GRBL Sender: the lines that are streamed."""

import re

_COMMENT_PAREN_RE = re.compile(r'\([^)]*\)')


def clean_lines_numbered(text):
    """
    Make the stream lines out of G-code text: remove the comments ('(...)' and
    ';...'), the '%' lines and the empty lines; strip the spaces.

    :param text: G-code text.
    :return: list of (source line number, str). The source line number is 1-based.
    """
    result = []
    for number, raw in enumerate((text or '').splitlines(), start=1):
        line = _COMMENT_PAREN_RE.sub('', raw)
        line = line.split(';', 1)[0].strip()
        if not line or line == '%':
            continue
        result.append((number, line))
    return result


def clean_lines(text):
    """
    Make the stream lines out of G-code text: remove the comments ('(...)' and
    ';...'), the '%' lines and the empty lines; strip the spaces.

    :param text: G-code text.
    :return: list of str.
    """
    return [line for _number, line in clean_lines_numbered(text)]
