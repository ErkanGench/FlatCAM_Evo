# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""Job preparation of the GRBL Sender: the lines that are streamed."""

import re
from types import SimpleNamespace

from appPlugins.Common.levelling_interp import new_levelling_state, level_gcode_line

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


def needs_segmentation(target_obj):
    """:return: True if the G-code of the CNCJob was not made with segmented lines."""
    return getattr(target_obj, 'is_segmented_gcode', False) is not True


def split_arcs(lines, units, arc_segment, decimals=4):
    """
    Split the G2/G3 arcs into G1 lines without a height change: level_gcode_line()
    with a 0 offset splits the arcs and keeps every Z. The modal state of
    level_gcode_line() finds also a bare modal arc line (X20 Y0 I5 J0 after G2).

    :param lines: list of str (clean lines).
    :param units: 'MM' or 'IN'.
    :param arc_segment: the longest chord of 1 piece of a split arc, in `units`.
    :param decimals: decimals of the new words.
    :return: (new_lines, count of split arcs, source_index, unsplit).
        source_index[i] is the index in `lines` of the source line of new_lines[i].
        unsplit is the list of the indexes of the arc lines that could not be
        split (plane, frame or position not known); they stay in new_lines as they are.
    """
    state = new_levelling_state(arc_segment=arc_segment, units=units)
    out = []
    source_index = []
    unsplit = []
    for index, line in enumerate(lines):
        split_before = state['arcs_split']
        arcs_before = state['arcs']
        text = level_gcode_line(line, state, lambda x, y: 0.0, decimals)
        if state['arcs_split'] > split_before:
            pieces = text.split('\n')
            out.extend(pieces)
            source_index.extend([index] * len(pieces))
            continue
        if state['arcs'] > arcs_before:
            unsplit.append(index)
        out.append(line)
        source_index.append(index)
    return out, state['arcs_split'], source_index, unsplit


def job_proxy(target_obj, lines):
    """
    A stand-in for the CNCJob that LevellingCoreMixin.autolevell_gcode() can level:
    1 tool with the stream text.
    """
    return SimpleNamespace(
        tools={'job': {'gcode': '\n'.join(lines) + '\n'}},
        units=target_obj.units,
        coords_decimals=target_obj.coords_decimals,
        seg_x=getattr(target_obj, 'seg_x', 0) or 0,
        seg_y=getattr(target_obj, 'seg_y', 0) or 0,
        obj_options=target_obj.obj_options,
    )
