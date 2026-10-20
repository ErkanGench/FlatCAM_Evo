# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""
Pure parsers for the replies of a GRBL 1.1 controller.

No Qt imports, no app imports - standard library only, so these functions
can be unit tested without the GUI stack.
"""

import math
import re


_PRB_RE = re.compile(r'\[PRB:\s*([^\]:]+):\s*([01])\s*\]')


def parse_grbl_probe_output(text):
    """
    Parse GRBL 1.1 probe results out of the raw serial answer stream.

    Every ``G38.2`` probe move is answered by GRBL with a line such as
    ``[PRB:10.000,5.000,-1.234:1]``. Other lines (``ok``, status reports
    ``<Idle|...>``, ``[MSG:...]``, blank lines, ...) are ignored. A PRB
    line can carry more than 3 axis values; only the first 3 (X, Y, Z)
    are kept.

    :param text: raw text captured from the controller.
    :return: list of (x, y, z) tuples, in the order the probes occurred.
    :raises ValueError: if a probe line reports flag ``:0`` (the probe
        did not touch the surface).
    """
    results = []
    for line in text.splitlines():
        m = _PRB_RE.search(line)
        if not m:
            continue

        coords_str, flag = m.group(1), m.group(2)
        parts = [p.strip() for p in coords_str.split(',') if p.strip() != '']
        if len(parts) < 3:
            continue

        x = float(parts[0])
        y = float(parts[1])
        z = float(parts[2])

        if not all(math.isfinite(value) for value in (x, y, z)):
            raise ValueError("Probe result contains non-finite coordinates")

        if flag == '0':
            raise ValueError(
                "Probe did not touch the surface at X={0} Y={1}".format(x, y)
            )

        results.append((x, y, z))

    return results


_ACTIVE_WCS_RE = re.compile(r'(?<![A-Z0-9.])G(5[4-9])(?![A-Z0-9.])')
_OFFSET_RE = re.compile(r'\[(G5[4-9]|G92|TLO)(?=[:\]\s]|$)(.*)')


def parse_grbl_active_wcs(text):
    """Parse the active G54-G59 work coordinate system from ``$G`` output."""
    match = _ACTIVE_WCS_RE.search(text)
    if not match:
        raise ValueError("Active G54-G59 work offset not found in $G output")
    return 'G' + match.group(1)


def parse_grbl_work_offset(text, active_wcs='G54'):
    """
    Parse the work-coordinate offset to SUBTRACT from a GRBL machine
    position, out of the raw ``$#`` command answer.

    GRBL reports probe/machine positions in MACHINE coordinates, but
    FlatCAM's probed height-map points are in WORK coordinates (the
    coordinate system the G-code itself is written in). The ``$#``
    command answer holds lines like::

        [G54:-100.000,-50.000,-20.000]
        [G55:0.000,0.000,0.000]
        [G92:0.000,0.000,0.000]
        [TLO:0.000]
        [PRB:0.000,0.000,0.000:0]

    The selected G54-G59 work coordinate system is read; the
    ``[PRB:...]`` line in this output is not a probe result and is
    ignored.

    :param text: raw text captured from the controller after ``$#``.
    :param active_wcs: selected work coordinate system, defaulting to G54.
    :return: (x, y, z) offset, computed as selected WCS + G92 per axis,
        with TLO added to Z. Missing G92 or TLO count as 0.
    :raises ValueError: if the selected WCS line is missing, an offset record
        is malformed, duplicated or nonfinite, or the combined offset overflows.
    """
    work_offset = None
    g92 = (0.0, 0.0, 0.0)
    tlo = 0.0
    seen = set()

    for line in text.splitlines():
        # Recognize the record key even if its payload or closing bracket is
        # truncated. A malformed optional G92/TLO is not an absent zero offset.
        m = _OFFSET_RE.fullmatch(line.strip())
        if not m:
            continue

        key, val = m.group(1), m.group(2)
        if key in seen or not val.startswith(':') or not val.endswith(']'):
            raise ValueError("Malformed or duplicate %s offset in $# output" % key)
        seen.add(key)
        parts = [p.strip() for p in val[1:-1].split(',')]
        if len(parts) != (1 if key == 'TLO' else 3):
            raise ValueError("Invalid %s offset field count in $# output" % key)
        try:
            values = tuple(float(p) for p in parts)
        except ValueError as err:
            raise ValueError("Invalid %s offset number in $# output" % key) from err
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite %s offset in $# output" % key)

        if key == active_wcs:
            work_offset = values
        elif key == 'G92':
            g92 = values
        elif key == 'TLO':
            tlo = values[0]

    if work_offset is None:
        raise ValueError("%s work offset not found in $# output" % active_wcs)

    x = work_offset[0] + g92[0]
    y = work_offset[1] + g92[1]
    z = work_offset[2] + g92[2] + tlo
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise ValueError("Nonfinite combined work offset in $# output")
    return x, y, z


_GRBL_ERROR_RE = re.compile(r'^\s*((?:error|ALARM)\s*:\s*\d+)', re.IGNORECASE | re.MULTILINE)
_SETTING_RE = re.compile(r'^\s*\$(\d+)\s*=\s*([+\-]?\d*\.?\d+)', re.MULTILINE)
_STATUS_RE = re.compile(r'^\s*<\s*([A-Za-z]+)')
_GC_RE = re.compile(r'\[GC:([^\]]*)\]')


def grbl_reply_error(text):
    """
    Find the first GRBL error or alarm line in a controller reply.

    :param text: decoded reply text; it can hold more than 1 line.
    :return: the text of the first 'error:N' or 'ALARM:N' line, or None.
    """
    if not text:
        return None
    m = _GRBL_ERROR_RE.search(text)
    return m.group(1) if m else None


def probe_timeout_s(travel_z, depth, feedrate, margin_s=5.0):
    """
    Time limit for 1 G38.2 probe move: the time to move from travel_z to
    depth at the probe feedrate (units per minute, G94), times 1.5, plus a margin.

    :return: seconds (float), never less than 10.0.
    """
    try:
        distance = abs(float(travel_z) - float(depth))
        feed = float(feedrate)
    except (TypeError, ValueError):
        return 10.0
    if not math.isfinite(distance) or not math.isfinite(feed) or feed <= 0:
        return 10.0
    return max(10.0, distance / feed * 60.0 * 1.5 + margin_s)


def grbl_report_scale(app_units, report_inches):
    """
    Factor that changes GRBL reported positions ([PRB:], $# offsets) into
    the application units.

    :param app_units: 'MM' or 'IN'.
    :param report_inches: True if the GRBL setting $13 is 1 (reports in inches).
    :return: 1.0, 25.4 or 1 / 25.4.
    """
    app_in = str(app_units).upper() == 'IN'
    if app_in == bool(report_inches):
        return 1.0
    return 1.0 / 25.4 if app_in else 25.4


def parse_grbl_setting(text, number):
    """
    :param text: the reply of the GRBL '$$' command.
    :param number: the setting number (int), for example 13.
    :return: the setting value as float, or None if it is not in the text.
    """
    if not text:
        return None
    for m in _SETTING_RE.finditer(text):
        if int(m.group(1)) == int(number):
            return float(m.group(2))
    return None


def parse_grbl_status_state(line):
    """
    :param line: a GRBL status report, for example '<Idle|MPos:0.000,0.000,0.000|FS:0,0>'.
    :return: the machine state word ('Idle', 'Run', 'Hold', 'Jog', 'Alarm',
        'Door', 'Check', 'Home', 'Sleep'), or None.
    """
    if not line:
        return None
    m = _STATUS_RE.match(line)
    return m.group(1) if m else None


def grbl_modes_confirmed(gc_text, units_cmd):
    """
    :param gc_text: the reply of the GRBL '$G' command.
    :param units_cmd: 'G20' or 'G21'.
    :return: True if the active modes include units_cmd, G90 and G94.
    """
    if not gc_text:
        return False
    m = _GC_RE.search(gc_text)
    if not m:
        return False
    words = m.group(1).split()
    return units_cmd in words and 'G90' in words and 'G94' in words


def parse_grbl_status_report(line):
    """
    Parse a GRBL 1.1 status report, for example
    '<Run|MPos:1.000,2.000,-0.500|FS:500,10000|Ov:100,100,100|WCO:0.000,0.000,0.000>'.

    :param line: 1 line of text.
    :return: dict with 'state' (str), and if they are in the report: 'mpos' and
        'wpos' (tuples of 3 floats), 'wco' (tuple of 3 floats), 'feed' and
        'spindle' (floats), 'ov' (tuple of 3 ints: feed, rapid, spindle),
        'buffer' (tuple of 2 ints: planner blocks, RX bytes available),
        'line' (int), 'accessory' (str, for example 'SF': S = spindle CW, C = spindle CCW,
        F = flood, M = mist; GRBL sends it with 'Ov', and only when an accessory is on);
        None if `line` is not a status report.
    """
    text = (line or '').strip()
    if not (text.startswith('<') and text.endswith('>')):
        return None
    fields = text[1:-1].split('|')
    if not fields or not fields[0]:
        return None
    report = {'state': fields[0].split(':')[0]}

    def floats(value, count):
        parts = value.split(',')
        if len(parts) != count:
            raise ValueError(value)
        result = tuple(float(p) for p in parts)
        if not all(math.isfinite(v) for v in result):
            raise ValueError(value)
        return result

    try:
        for field in fields[1:]:
            key, _sep, value = field.partition(':')
            if key == 'MPos':
                report['mpos'] = floats(value, 3)
            elif key == 'WPos':
                report['wpos'] = floats(value, 3)
            elif key == 'WCO':
                report['wco'] = floats(value, 3)
            elif key == 'FS':
                report['feed'], report['spindle'] = floats(value, 2)
            elif key == 'F':
                report['feed'] = floats(value, 1)[0]
            elif key == 'Ov':
                report['ov'] = tuple(int(v) for v in floats(value, 3))
            elif key == 'Bf':
                report['buffer'] = tuple(int(v) for v in floats(value, 2))
            elif key == 'Ln':
                report['line'] = int(value)
            elif key == 'A':
                report['accessory'] = value
    except ValueError:
        return None
    return report


def work_position(report, last_wco=None):
    """
    :param report:   a dict from parse_grbl_status_report().
    :param last_wco: the last WCO seen (GRBL sends WCO only in some reports).
    :return: (x, y, z) work position, or None if it can not be computed.
    """
    if report is None:
        return None
    if 'wpos' in report:
        return report['wpos']
    wco = report.get('wco', last_wco)
    if 'mpos' in report and wco is not None:
        return tuple(m - o for m, o in zip(report['mpos'], wco))
    return None
