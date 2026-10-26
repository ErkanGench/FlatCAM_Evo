"""Basic shapes and paths converted into user-space polylines."""
import math
import re

import numpy as np

from .document import parse_length
from .flatten import quad_segs
from .pathdata import path_polylines

_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_UNIT_CIRCLES = {}


class Geo:
    """Reads geometry properties from CSS first (SVG 2) and from attributes second."""
    __slots__ = ('el', 'own', 'vw', 'vh', 'fs')

    def __init__(self, el, own, vp, font_size):
        self.el, self.own, self.vw, self.vh, self.fs = el, own, vp[0], vp[1], font_size

    def raw(self, name):
        v = self.own.get(name)
        return v if v is not None else self.el.get(name)

    def length(self, name, axis, default=0.0):
        """
        :param name: property name
        :param axis: 'x', 'y' or 'r' picks the percentage reference
        :param default: value when missing or invalid
        :return: length in user units
        """
        raw = self.raw(name)
        if raw is None:
            return default
        ref = self.vw if axis == 'x' else (self.vh if axis == 'y' else math.sqrt((self.vw ** 2 + self.vh ** 2) / 2.0))
        try:
            v = float(raw)
            if v - v == 0.0 and '_' not in raw:
                return v
        except ValueError:
            pass
        v = parse_length(raw.strip(), ref, self.fs)
        return default if v is None else v


def _unit_circle(n):
    hit = _UNIT_CIRCLES.get(n)
    if hit is None:
        a = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        hit = (np.cos(a), np.sin(a))
        _UNIT_CIRCLES[n] = hit
    return hit


def ellipse_points(cx, cy, rx, ry, steps):
    """
    :param steps: segments per quarter circle (int)
    :return: (4 * steps, 2) points on the ellipse
    """
    c, s = _unit_circle(4 * max(int(steps), 2))
    return np.column_stack((cx + rx * c, cy + ry * s))


def _rect(g, res):
    w, h = g.length('width', 'x'), g.length('height', 'y')
    if w <= 0 or h <= 0:
        return []
    x, y = g.length('x', 'x'), g.length('y', 'y')
    rx_raw, ry_raw = g.raw('rx'), g.raw('ry')
    rx = g.length('rx', 'x', -1.0) if rx_raw not in (None, 'auto') else -1.0
    ry = g.length('ry', 'y', -1.0) if ry_raw not in (None, 'auto') else -1.0
    if rx < 0 and ry < 0:
        rx = ry = 0.0
    elif rx < 0:
        rx = ry
    elif ry < 0:
        ry = rx
    rx, ry = min(rx, w / 2.0), min(ry, h / 2.0)
    if rx <= 0 or ry <= 0:
        return [(np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h)]), True)]
    q = max(1, int(quad_segs(res, max(rx, ry))))
    parts = []
    for ccx, ccy, a0 in ((x + w - rx, y + ry, -math.pi / 2), (x + w - rx, y + h - ry, 0.0),
                         (x + rx, y + h - ry, math.pi / 2), (x + rx, y + ry, math.pi)):
        a = a0 + np.linspace(0.0, math.pi / 2, q + 1)
        parts.append(np.column_stack((ccx + rx * np.cos(a), ccy + ry * np.sin(a))))
    return [(np.concatenate(parts), True)]


def _circle(g, res):
    r = g.length('r', 'r')
    if r <= 0:
        return []
    return [(ellipse_points(g.length('cx', 'x'), g.length('cy', 'y'), r, r, quad_segs(res, r)), True)]


def _ellipse(g, res):
    rx_raw, ry_raw = g.raw('rx'), g.raw('ry')
    rx = g.length('rx', 'x', -1.0) if rx_raw not in (None, 'auto') else -1.0
    ry = g.length('ry', 'y', -1.0) if ry_raw not in (None, 'auto') else -1.0
    if rx < 0:
        rx = ry
    if ry < 0:
        ry = rx
    if rx <= 0 or ry <= 0:
        return []
    return [(ellipse_points(g.length('cx', 'x'), g.length('cy', 'y'), rx, ry, quad_segs(res, max(rx, ry))), True)]


def _line(g, res):
    pts = np.array([(g.length('x1', 'x'), g.length('y1', 'y')), (g.length('x2', 'x'), g.length('y2', 'y'))])
    return [(pts, False)]


def _poly(g, closed):
    vals = [float(v) for v in _NUM.findall(g.el.get('points', ''))]
    n = len(vals) // 2
    if n < 2:
        return []
    return [(np.array(vals[:2 * n]).reshape(-1, 2), closed)]


def shape_polylines(local, g, resolution, tol):
    """
    :param local: local tag name
    :param g: Geo reader
    :param resolution: segments per quarter circle
    :param tol: curve tolerance in user units
    :return: list of (points (N,2), closed) in user space
    """
    if local == 'path':
        d = g.el.get('d')
        return path_polylines(d, tol, resolution) if d else []
    if local == 'rect':
        return _rect(g, resolution)
    if local == 'circle':
        return _circle(g, resolution)
    if local == 'ellipse':
        return _ellipse(g, resolution)
    if local == 'line':
        return _line(g, resolution)
    if local == 'polygon':
        return _poly(g, True)
    if local == 'polyline':
        return _poly(g, False)
    return []
