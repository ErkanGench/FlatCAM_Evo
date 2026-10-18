"""Parser of the SVG path ``d`` attribute into subpaths of absolute segments."""
import math
import re

import numpy as np

from .flatten import flatten_subpath

_NUM_RE = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
_TOKEN = re.compile(r'([MmLlHhVvCcSsQqTtAaZz])|(' + _NUM_RE + ')')
_SEP = re.compile(r'[\s,]*')
_NUM = re.compile(_NUM_RE)
_ARGS = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}
_CMDS = frozenset('MmLlHhVvCcSsQqTtAaZz')


def tokenize(d):
    """
    :param d: path data
    :return: list of command letters (str) and numbers (float)
    """
    if 'a' in d or 'A' in d:
        return _tokenize_arcs(d)
    return [c or float(n) for c, n in _TOKEN.findall(d)]


def _tokenize_arcs(d):
    """Slow tokenizer that understands arc flags written without separators."""
    out = []
    pos, size, cmd, argi = 0, len(d), None, 0
    while True:
        pos = _SEP.match(d, pos).end()
        if pos >= size:
            break
        ch = d[pos]
        if ch.isalpha():
            if ch not in _CMDS:
                break
            out.append(ch)
            cmd, argi, pos = ch, 0, pos + 1
            continue
        if cmd in ('a', 'A') and argi % 7 in (3, 4):
            if ch not in '01':
                break
            out.append(float(ch))
            pos, argi = pos + 1, argi + 1
            continue
        m = _NUM.match(d, pos)
        if not m:
            break
        out.append(float(m.group()))
        pos, argi = m.end(), argi + 1
    return out


def arc_to_center(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2):
    """
    SVG endpoint to center parameterisation (SVG implementation notes F.6.5).

    :return: (cx, cy, rx, ry, phi, theta1, dtheta, x2, y2) or None for a degenerate arc
    """
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return None
    phi = math.radians(phi_deg % 360.0)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    if den == 0:
        return None
    num = rx * rx * ry * ry - den
    coef = math.sqrt(max(0.0, num / den)) * (-1.0 if fa == fs else 1.0)
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0
    th1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    th2 = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx)
    dth = th2 - th1
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    return cx, cy, rx, ry, phi, th1, dth, x2, y2


class _PathParser:
    """Stateful converter of tokens into absolute segments."""

    def __init__(self, tokens):
        self.t = tokens
        self.subs = []
        self.cur = None
        self.start = None
        self.segs = None
        self.pc = None
        self.pk = None

    def flush(self, closed=False):
        if self.segs:
            self.subs.append((self.start, self.segs, closed))
        self.segs = None

    def begin(self):
        if self.segs is None:
            self.segs = []
            self.start = self.cur

    def move(self, x, y, rel):
        self.flush()
        if rel and self.cur is not None:
            x, y = x + self.cur[0], y + self.cur[1]
        self.cur = (x, y)
        self.start = self.cur
        self.segs = []
        self.pk = None

    def close(self):
        if self.segs is not None and self.segs:
            self.flush(True)
        self.segs = None
        if self.start is not None:
            self.cur = self.start
        self.pk = None

    def lines(self, up, vals, rel):
        cx, cy = self.cur
        a = np.array(vals, dtype=float)
        if up == 'L':
            a = a.reshape(-1, 2)
            if rel:
                a = a.cumsum(axis=0) + (cx, cy)
        elif up == 'H':
            xs = a.cumsum() + cx if rel else a
            a = np.column_stack((xs, np.full(len(xs), cy)))
        else:
            ys = a.cumsum() + cy if rel else a
            a = np.column_stack((np.full(len(ys), cx), ys))
        self.begin()
        self.segs.append(('L', a))
        self.cur = (a[-1, 0], a[-1, 1])
        self.pk = None

    def curve(self, up, a, rel):
        self.begin()
        x0, y0 = self.cur
        ox, oy = (x0, y0) if rel else (0.0, 0.0)
        if up == 'C':
            p1, p2, p3 = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy), (a[4] + ox, a[5] + oy)
            self.pk, self.pc = 'c', p2
        elif up == 'S':
            p1 = (2 * x0 - self.pc[0], 2 * y0 - self.pc[1]) if self.pk == 'c' else (x0, y0)
            p2, p3 = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy)
            self.pk, self.pc = 'c', p2
        else:
            if up == 'Q':
                q, e = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy)
            else:
                q = (2 * x0 - self.pc[0], 2 * y0 - self.pc[1]) if self.pk == 'q' else (x0, y0)
                e = (a[0] + ox, a[1] + oy)
            p1 = (x0 + 2.0 / 3.0 * (q[0] - x0), y0 + 2.0 / 3.0 * (q[1] - y0))
            p2 = (e[0] + 2.0 / 3.0 * (q[0] - e[0]), e[1] + 2.0 / 3.0 * (q[1] - e[1]))
            p3 = e
            self.pk, self.pc = 'q', q
        self.segs.append(('C', np.array([(x0, y0), p1, p2, p3], dtype=float)))
        self.cur = p3

    def arc(self, a, rel):
        self.begin()
        x0, y0 = self.cur
        x2, y2 = (a[5] + x0, a[6] + y0) if rel else (a[5], a[6])
        self.pk = None
        if (x2, y2) == (x0, y0):
            return
        center = arc_to_center(x0, y0, a[0], a[1], a[2], a[3] != 0, a[4] != 0, x2, y2)
        if center is None:
            self.segs.append(('L', np.array([[x2, y2]])))
        else:
            self.segs.append(('A', center))
        self.cur = (x2, y2)

    def run(self):
        t, n, i, cmd = self.t, len(self.t), 0, None
        while i < n:
            tok = t[i]
            if isinstance(tok, str):
                cmd = tok
                i += 1
                if cmd in 'Zz':
                    if self.cur is None:
                        break
                    self.close()
                continue
            if cmd is None or cmd in 'Zz':
                break
            up, rel = cmd.upper(), cmd.islower()
            if self.cur is None and up != 'M':
                break
            need = _ARGS[up]
            j = i
            while j < n and not isinstance(t[j], str):
                j += 1
            k = (j - i) // need
            if k == 0:
                break
            vals = t[i:i + k * need]
            self._dispatch(up, vals, k, need, rel)
            if up == 'M':
                cmd = 'l' if rel else 'L'
            i += k * need
            if i != j:
                break
        self.flush()
        return self.subs

    def _dispatch(self, up, vals, k, need, rel):
        if up in 'LHV':
            self.lines(up, vals, rel)
        elif up == 'M':
            self.move(vals[0], vals[1], rel)
            if k > 1:
                self.lines('L', vals[2:], rel)
        elif up == 'A':
            for g in range(k):
                self.arc(vals[g * 7:g * 7 + 7], rel)
        else:
            for g in range(k):
                self.curve(up, vals[g * need:(g + 1) * need], rel)


def parse_path(d):
    """
    :param d: path data
    :return: list of (start, segments, closed) with absolute coordinates
    """
    return _PathParser(tokenize(d)).run()


def is_batchable(subs):
    """
    :param subs: result of parse_path
    :return: True for one subpath of lines and cubics only, with enough points for a ring (flatten_many can take it)
    """
    if len(subs) != 1:
        return False
    points = 1
    for kind, data in subs[0][1]:
        if kind == 'A':
            return False
        points += len(data) if kind == 'L' else 1
    return points >= 3


def polylines_of(subs, tol, resolution):
    """
    :param subs: result of parse_path
    :param tol: Bezier tolerance in user units
    :param resolution: segments per quarter circle (a full circle has 4 * resolution)
    :return: list of (points (N,2), closed)
    """
    out = []
    for start, segs, closed in subs:
        pts = flatten_subpath(start, segs, tol, resolution)
        if len(pts) >= 2:
            out.append((pts, closed))
    return out


def path_polylines(d, tol, resolution):
    """
    :param d: path data
    :param tol: Bezier tolerance in user units
    :param resolution: segments per quarter circle (a full circle has 4 * resolution)
    :return: list of (points (N,2), closed)
    """
    return polylines_of(parse_path(d), tol, resolution)
