"""Numpy flattening of cubic Beziers and elliptical arcs into polylines."""
import math

import numpy as np

MAX_STEPS = 1000


def quad_segs(resolution, radius):
    """
    :param resolution: segments per quarter circle (int), or a function radius -> segments per quarter circle
    :param radius:     the radius of the circle or arc, in the units that function expects
    :return:           segments per quarter circle
    """
    return resolution(radius) if callable(resolution) else resolution


def cubic_counts(b, tol):
    """
    :param b: (K, 4, 2) control points
    :param tol: allowed deviation in the units of b (a number or a (K,) array)
    :return: (K,) integer segment counts
    """
    d = b[:, :2] - 2.0 * b[:, 1:3] + b[:, 2:4]
    dd = np.hypot(d[:, :, 0], d[:, :, 1]).max(axis=1)
    n = np.ceil(np.sqrt(0.75 * dd / np.maximum(tol, 1e-12)))
    return np.minimum(np.maximum(n, 1), MAX_STEPS).astype(np.int64)


def eval_cubics(b, n):
    """
    :param b: (K, 4, 2) control points
    :param n: (K,) segment counts
    :return: (sum(n), 2) points, t from 1/n to 1 for every curve (start points excluded)
    """
    total = int(n.sum())
    ends = np.cumsum(n)
    t = ((np.arange(1, total + 1) - np.repeat(ends - n, n)) / np.repeat(n, n))[:, None]
    p0, p1, p2, p3 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    coef = np.stack((p3 - p0 + 3.0 * (p1 - p2), 3.0 * (p0 - 2.0 * p1 + p2), 3.0 * (p1 - p0), p0), axis=1)
    c = np.repeat(coef, n, axis=0)
    out = ((c[:, 0] * t + c[:, 1]) * t + c[:, 2]) * t + c[:, 3]
    out[ends - 1] = p3
    return out


def eval_arc(arc, resolution):
    """
    :param arc: (cx, cy, rx, ry, phi, theta1, dtheta, x_end, y_end)
    :param resolution: segments per quarter circle (int) or a function radius -> segments per quarter circle;
                       the radius of an ellipse arc is its larger semi-axis
    :return: (n, 2) points after the arc start
    """
    cx, cy, rx, ry, phi, th1, dth, ex, ey = arc
    q = quad_segs(resolution, max(abs(rx), abs(ry)))
    n = int(max(1, min(MAX_STEPS, math.ceil(abs(dth) / (0.5 * math.pi / max(q, 1))))))
    th = th1 + dth * (np.arange(1, n + 1) / n)
    ct, st = np.cos(th), np.sin(th)
    cp, sp = math.cos(phi), math.sin(phi)
    pts = np.empty((n, 2))
    pts[:, 0] = cx + rx * ct * cp - ry * st * sp
    pts[:, 1] = cy + rx * ct * sp + ry * st * cp
    pts[-1] = (ex, ey)
    return pts


def flatten_subpath(start, segs, tol, resolution):
    """
    :param start: (x, y) start point
    :param segs: list of ('L', (k,2)) / ('C', (4,2)) / ('A', tuple)
    :param tol: curve tolerance in path units
    :param resolution: segments per quarter circle
    :return: (N, 2) polyline
    """
    curves = [s[1] for s in segs if s[0] == 'C']
    cub_chunks = []
    if curves:
        b = np.stack(curves)
        n = cubic_counts(b, tol)
        cub = eval_cubics(b, n)
        stops = np.cumsum(n).tolist()
        cub_chunks = [cub[e - c:e] for e, c in zip(stops, n.tolist())]
    chunks = [np.asarray(start, dtype=float)[None, :]]
    ci = 0
    for kind, data in segs:
        if kind == 'L':
            chunks.append(data)
        elif kind == 'C':
            chunks.append(cub_chunks[ci])
            ci += 1
        else:
            chunks.append(eval_arc(data, resolution))
    return np.concatenate(chunks) if len(chunks) > 1 else chunks[0]


def flatten_many(items):
    """
    Flatten many line/cubic-only subpaths with one vectorised Bezier evaluation.

    :param items: list of (start, segs, tol) where segs holds only ('L', (k,2)) and ('C', (4,2)) entries
    :return: list of (N, 2) polylines, same order
    """
    curves, tols = [], []
    for _, segs, tol in items:
        for kind, data in segs:
            if kind == 'C':
                curves.append(data)
                tols.append(tol)
    cub, stops, ci = None, [], 0
    if curves:
        b = np.stack(curves)
        n = cubic_counts(b, np.array(tols))
        cub = eval_cubics(b, n)
        stops = np.cumsum(n).tolist()
    out = []
    for start, segs, _ in items:
        chunks = [np.asarray(start, dtype=float)[None, :]]
        for kind, data in segs:
            if kind == 'L':
                chunks.append(data)
            else:
                chunks.append(cub[(stops[ci - 1] if ci else 0):stops[ci]])
                ci += 1
        out.append(np.concatenate(chunks) if len(chunks) > 1 else chunks[0])
    return out
