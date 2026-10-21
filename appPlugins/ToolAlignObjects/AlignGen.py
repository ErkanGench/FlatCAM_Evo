# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 10/21/2026                                         #
# MIT Licence                                              #
# ##########################################################

"""
Model of the Align Objects plugin: the snap index and the solvers. No Qt here.

A matrix is the shapely 6-tuple (a, b, d, e, xoff, yoff):
    x' = a * x + b * y + xoff
    y' = d * x + e * y + yoff
"""

import math

import numpy as np
import shapely
from shapely import Point, STRtree
from shapely.geometry.base import BaseGeometry

from appParsers.feature_access import iter_features


class AlignError(Exception):
    """A user message: the points can not give a valid alignment."""


class SnapIndex:
    """
    Snap targets of one object.

    tree:       STRtree of the feature solids (None if there are none)
    centers:    (N, 2) array, the snap point of each solid, in the order of the tree
    areas:      (N,) array, the area of each solid
    vertices:   (M, 2) array, the fallback snap points
    """

    def __init__(self, solids, centers, vertices):
        self.tree = STRtree(solids) if solids else None
        self.centers = np.asarray(centers, dtype=float).reshape(-1, 2)
        self.areas = shapely.area(np.asarray(solids, dtype=object)) if solids else np.empty(0)
        self.vertices = np.asarray(vertices, dtype=float).reshape(-1, 2)


def _flatten(geo, out):
    """Collect every shapely geometry of a nested list / dict-free structure into out."""
    if geo is None:
        return out
    if isinstance(geo, BaseGeometry):
        if not geo.is_empty:
            out.append(geo)
        return out
    try:
        for g in geo:
            _flatten(g, out)
    except TypeError:
        pass
    return out


def _coordinates(geoms):
    if not geoms:
        return np.empty((0, 2))
    return shapely.get_coordinates(np.asarray(geoms, dtype=object))


def build_snap_index(obj):
    """
    Build the snap index of a Gerber, Excellon or Geometry object.

    Gerber:     the dark flashes snap to the flash point; the vertices of all dark solids are the fallback
    Excellon:   a drill snaps to the drill point, a slot to the middle of the slot; vertices are the fallback
    Geometry:   only vertices
    """
    kind = str(getattr(obj, 'kind', '')).lower()
    solids, centers, outlines = [], [], []

    if kind in ('gerber', 'excellon'):
        for rec in iter_features(obj):
            if rec.polarity != 'dark' or rec.solid is None or rec.solid.is_empty:
                continue
            outlines.append(rec.solid)
            if kind == 'gerber':
                if not isinstance(rec.follow, Point):
                    continue
                center = rec.follow
            else:
                center = rec.follow if isinstance(rec.follow, Point) else rec.follow.centroid
            solids.append(rec.solid)
            centers.append((center.x, center.y))
    else:
        tools = getattr(obj, 'tools', None)
        if getattr(obj, 'multigeo', False) and isinstance(tools, dict):
            for tool in tools.values():
                _flatten(tool.get('solid_geometry'), outlines)
        else:
            _flatten(getattr(obj, 'solid_geometry', None), outlines)

    return SnapIndex(solids, centers, _coordinates(outlines))


def snap(index, x, y, tol):
    """
    The snap point for a click at (x, y), or None.

    1. the click is in one or more solids: the center of the smallest one
    2. else the nearest vertex, if it is not farther than tol
    """
    if index.tree is not None:
        hits = index.tree.query(Point(x, y), predicate='intersects')
        if len(hits):
            best = hits[int(np.argmin(index.areas[hits]))]
            cx, cy = index.centers[best]
            return float(cx), float(cy)

    if len(index.vertices):
        d2 = (index.vertices[:, 0] - x) ** 2 + (index.vertices[:, 1] - y) ** 2
        i = int(np.argmin(d2))
        if d2[i] <= tol * tol:
            vx, vy = index.vertices[i]
            return float(vx), float(vy)
    return None


def _points(P, Q, min_pairs):
    P = np.asarray(P, dtype=float).reshape(-1, 2)
    Q = np.asarray(Q, dtype=float).reshape(-1, 2)
    if len(P) != len(Q):
        raise AlignError("The number of START points and DESTINATION points is not the same.")
    if len(P) < min_pairs:
        raise AlignError("At least %d point pairs are needed." % min_pairs)
    if not (np.isfinite(P).all() and np.isfinite(Q).all()):
        raise AlignError("A point is not a finite number.")
    return P, Q


def _eps(P, Q):
    return 1e-9 * max(1.0, float(np.abs(P).max()), float(np.abs(Q).max()))


def solve_translate(P, Q):
    """Move the first START point to the first DESTINATION point."""
    P, Q = _points(P, Q, 1)
    dx, dy = Q[0] - P[0]
    return 1.0, 0.0, 0.0, 1.0, float(dx), float(dy)


def _rotation_fit(P, Q, with_scale):
    """Least-squares rotation (+ uniform scale) and translation, by Umeyama with atan2. No reflection."""
    P, Q = _points(P, Q, 2)
    mp, mq = P.mean(axis=0), Q.mean(axis=0)
    pc, qc = P - mp, Q - mq
    var_p = float((pc ** 2).sum())
    if math.sqrt(var_p) <= _eps(P, Q):
        raise AlignError("The START points are all at the same position.")

    num = float((pc[:, 0] * qc[:, 1] - pc[:, 1] * qc[:, 0]).sum())
    den = float((pc[:, 0] * qc[:, 0] + pc[:, 1] * qc[:, 1]).sum())
    theta = math.atan2(num, den)

    if with_scale:
        s = math.hypot(num, den) / var_p
        if not math.isfinite(s) or s <= _eps(P, Q):
            raise AlignError("The scale factor is not valid.")
    else:
        s = 1.0

    c, sn = s * math.cos(theta), s * math.sin(theta)
    a, b, d, e = c, -sn, sn, c
    xoff = mq[0] - (a * mp[0] + b * mp[1])
    yoff = mq[1] - (d * mp[0] + e * mp[1])
    return a, b, d, e, float(xoff), float(yoff)


def solve_rigid(P, Q):
    """Move + rotate, least squares, 2 or more pairs."""
    return _rotation_fit(P, Q, with_scale=False)


def solve_similarity(P, Q):
    """Move + rotate + uniform scale, least squares, 2 or more pairs."""
    return _rotation_fit(P, Q, with_scale=True)


def solve_affine(P, Q):
    """Full affine (move, rotate, X/Y scale, skew), least squares, 3 or more pairs not on one line."""
    P, Q = _points(P, Q, 3)
    pc = P - P.mean(axis=0)
    sv = np.linalg.svd(pc, compute_uv=False)
    if sv[0] <= _eps(P, Q) or sv[1] <= 1e-9 * sv[0]:
        raise AlignError("The START points are on one line.")

    A = np.column_stack([P, np.ones(len(P))])
    sol_x = np.linalg.lstsq(A, Q[:, 0], rcond=None)[0]
    sol_y = np.linalg.lstsq(A, Q[:, 1], rcond=None)[0]
    a, b, xoff = (float(v) for v in sol_x)
    d, e, yoff = (float(v) for v in sol_y)
    if abs(a * e - b * d) <= 1e-12:
        raise AlignError("The transformation is singular.")
    return a, b, d, e, xoff, yoff


def apply_matrix(matrix, P):
    """The points P after the matrix, as an (N, 2) array."""
    a, b, d, e, xoff, yoff = matrix
    P = np.asarray(P, dtype=float).reshape(-1, 2)
    return np.column_stack([a * P[:, 0] + b * P[:, 1] + xoff, d * P[:, 0] + e * P[:, 1] + yoff])


def residuals(matrix, P, Q):
    """(errors, rms): the distance from each transformed START point to its DESTINATION point."""
    Q = np.asarray(Q, dtype=float).reshape(-1, 2)
    if len(Q) == 0:
        return [], 0.0
    err = np.hypot(*(apply_matrix(matrix, P) - Q).T)
    return [float(v) for v in err], float(math.sqrt((err ** 2).mean()))


def invert(matrix):
    """The inverse matrix."""
    a, b, d, e, xoff, yoff = matrix
    det = a * e - b * d
    if abs(det) <= 1e-12:
        raise AlignError("The transformation is singular.")
    ia, ib, id_, ie = e / det, -b / det, -d / det, a / det
    return ia, ib, id_, ie, -(ia * xoff + ib * yoff), -(id_ * xoff + ie * yoff)


# ##################################################################################################################
# Automatic alignment
# ##################################################################################################################

class AutoResult:
    """One candidate of auto_align: the matrix, the overlap score and the matched pairs."""

    def __init__(self, matrix, matched, total, P, Q, errors, rms, mirrored):
        self.matrix = matrix
        self.matched = matched
        self.total = total
        self.P = P
        self.Q = Q
        self.errors = errors
        self.rms = rms
        self.mirrored = mirrored


_FLIP = np.array([-1.0, 1.0])


def _after_mirror(matrix):
    """The matrix applied after a mirror about the Y axis (x -> -x)."""
    a, b, d, e, xoff, yoff = matrix
    return -a, b, -d, e, xoff, yoff


def _nn_vectors(pts, sample):
    """The vector from each sampled point to its nearest other point: (angle mod pi, length)."""
    tree = STRtree(shapely.points(pts))
    idx_in, idx_tree = tree.query_nearest(shapely.points(pts[sample]), exclusive=True, all_matches=False)
    v = pts[idx_tree] - pts[sample[idx_in]]
    return np.mod(np.arctan2(v[:, 1], v[:, 0]), math.pi), np.hypot(v[:, 0], v[:, 1])


def _angle_candidates(src, dst, rng, peaks=4):
    """Rotation angles (radians) from a histogram of the angle differences of the nearest neighbor vectors."""
    s_idx = rng.choice(len(src), min(len(src), 300), replace=False)
    d_idx = rng.choice(len(dst), min(len(dst), 1500), replace=False)
    a_s, l_s = _nn_vectors(src, s_idx)
    a_d, l_d = _nn_vectors(dst, d_idx)

    same_len = np.abs(l_s[:, None] - l_d[None, :]) <= 0.05 * l_s[:, None] + 1e-12
    theta = np.mod(a_d[None, :] - a_s[:, None], math.pi)[same_len]
    if len(theta) == 0:
        return [0.0, math.pi]

    bins = 360
    hist = np.bincount(np.minimum((theta / math.pi * bins).astype(int), bins - 1), minlength=bins).astype(float)
    smooth = hist + 0.5 * (np.roll(hist, 1) + np.roll(hist, -1))
    is_peak = (smooth >= np.roll(smooth, 1)) & (smooth > np.roll(smooth, -1)) & (smooth > 0)
    found = [int(i) for i in np.argsort(-smooth) if is_peak[i]][:peaks]

    width = math.pi / bins
    angles = []
    for i in found:
        # the mean of the differences in the peak bin and its 2 neighbors (circular, mod pi)
        center = (i + 0.5) * width
        delta = np.mod(theta - center + math.pi / 2, math.pi) - math.pi / 2
        near = delta[np.abs(delta) <= 1.5 * width]
        angles.append(center + (float(near.mean()) if len(near) else 0.0))
    # the nearest neighbor vectors have no direction: every angle is also tested + 180 degrees
    return angles + [a + math.pi for a in angles]


def _translation_candidates(moved, dst, cell, peaks=3):
    """Translations from a vote of the offsets dst - moved (moved: the rotated START sample)."""
    off = (dst[None, :, :] - moved[:, None, :]).reshape(-1, 2)
    keys = np.floor(off / cell).astype(np.int64)
    # 1 integer key for each cell (with 2 cells of margin for the neighbors): a 1D sort is much faster than a row sort
    kmin = keys.min(axis=0) - 2
    width = int(keys[:, 1].max() - kmin[1]) + 3
    flat = np.sort((keys[:, 0] - kmin[0]) * width + (keys[:, 1] - kmin[1]))
    starts = np.flatnonzero(np.r_[True, flat[1:] != flat[:-1]])
    uniq = flat[starts]
    counts = np.diff(np.r_[starts, len(flat)])

    # the count of each cell plus its 8 neighbors: a peak on a cell border is not split
    top = uniq[np.argsort(-counts)[:30]]
    near = (top[:, None] + np.array([i * width + j for i in (-1, 0, 1) for j in (-1, 0, 1)])[None, :]).ravel()
    pos = np.minimum(np.searchsorted(uniq, near), len(uniq) - 1)
    sums = np.where(uniq[pos] == near, counts[pos], 0).reshape(len(top), 9).sum(axis=1)
    scored = sorted(((int(c), int(k // width + kmin[0]), int(k % width + kmin[1])) for c, k in zip(sums, top)),
                    reverse=True)

    out, used = [], []
    for _total, x, y in scored:
        if any(abs(x - ux) <= 2 and abs(y - uy) <= 2 for ux, uy in used):
            continue
        used.append((x, y))
        mask = (np.abs(keys[:, 0] - x) <= 1) & (np.abs(keys[:, 1] - y) <= 1)
        out.append(np.median(off[mask], axis=0))
        if len(out) == peaks:
            break
    return out


def _nearest_pairs(matrix, src, dst_tree, dst, max_dist):
    """(P, Q): each START point and the nearest aligner center within max_dist after the matrix."""
    moved = apply_matrix(matrix, src)
    idx_in, idx_tree = dst_tree.query_nearest(shapely.points(moved), max_distance=max_dist, all_matches=False)
    return src[idx_in], dst[idx_tree]


def _refine(matrix, src_fit, dst_tree, dst, radius, model):
    """
    ICP: pair with the nearest center, solve, repeat. src_fit are the START points, already mirrored for a
    mirrored candidate; the matrix maps src_fit.
    """
    solver = {'rigid': solve_rigid, 'similarity': solve_similarity, 'affine': solve_affine}[model]
    for step in range(5):
        P, Q = _nearest_pairs(matrix, src_fit, dst_tree, dst, 2.0 * radius)
        try:
            # the first steps are rigid: a scale or a skew from a bad start would grow
            matrix = (solver if step >= 2 else solve_rigid)(P, Q)
        except AlignError:
            return None
    return matrix


def _score(matrix, src, dst_index, dst, dst_tree, radius):
    """The START centers that fall inside an aligner solid after the matrix, and their nearest aligner centers."""
    moved = apply_matrix(matrix, src)
    hits = dst_index.tree.query(shapely.points(moved), predicate='intersects')
    inside = np.unique(hits[0]) if hits.size else np.empty(0, dtype=int)
    if len(inside) == 0:
        return 0, src[:0], dst[:0]
    idx_in, idx_tree = dst_tree.query_nearest(shapely.points(moved[inside]), max_distance=2.0 * radius,
                                              all_matches=False)
    return len(inside), src[inside][idx_in], dst[idx_tree]


def _same(m1, m2, corners, tol):
    return bool(np.all(np.hypot(*(apply_matrix(m1, corners) - apply_matrix(m2, corners)).T) <= tol))


def auto_align(src_index, dst_index, model='rigid', allow_mirror=False, max_results=5, progress=None):
    """
    Find the matrices that put the most START centers (pads / holes of the aligned object) inside the features of
    the aligner object. No scipy: STRtree and numpy only.

    1. rotation candidates: a histogram of the angle differences of the nearest neighbor vectors
    2. translation candidates: for each rotation, a vote of the offsets from a START sample to all aligner centers
    3. ICP refine with the selected model, then the overlap score on all START centers

    :param src_index:       SnapIndex of the aligned object
    :param dst_index:       SnapIndex of the aligner object
    :param model:           'rigid', 'similarity' or 'affine', the model of the refine
    :param allow_mirror:    also test the START centers mirrored (a bottom layer)
    :param max_results:     the number of distinct candidates to return
    :param progress:        callable(int percent) or None
    :return:                list of AutoResult, best first
    """
    src = src_index.centers
    dst = dst_index.centers
    if len(src) < 2:
        raise AlignError("The aligned object needs at least 2 pads or holes.")
    if len(dst) < 2 or dst_index.tree is None:
        raise AlignError("The aligner object needs at least 2 pads or holes.")
    if model not in ('rigid', 'similarity', 'affine'):
        model = 'rigid'

    def report(value):
        if progress is not None:
            progress(int(value))

    rng = np.random.default_rng(0)
    radius = float(np.median(np.sqrt(dst_index.areas / math.pi)))
    if not radius > 0:
        raise AlignError("The aligner object needs at least 2 pads or holes.")

    dst_tree = STRtree(shapely.points(dst))
    sample = src[rng.choice(len(src), min(len(src), 50), replace=False)]
    src_fit = src[rng.choice(len(src), min(len(src), 2000), replace=False)]

    mirrors = (False, True) if allow_mirror else (False,)
    # the current position is always a candidate: the objects are often almost aligned
    candidates = []
    matrix = _refine((1.0, 0.0, 0.0, 1.0, 0.0, 0.0), src_fit, dst_tree, dst, radius, model)
    if matrix is not None:
        candidates.append((matrix, False))
    for m_i, mirrored in enumerate(mirrors):
        flip = _FLIP if mirrored else 1.0
        angles = _angle_candidates(src * flip, dst, rng)
        for a_i, theta in enumerate(angles):
            c, s = math.cos(theta), math.sin(theta)
            moved = (sample * flip) @ np.array([[c, s], [-s, c]])
            for t in _translation_candidates(moved, dst, radius):
                matrix = _refine((c, -s, s, c, float(t[0]), float(t[1])), src_fit * flip, dst_tree, dst, radius,
                                 model)
                if matrix is not None:
                    candidates.append((_after_mirror(matrix) if mirrored else matrix, mirrored))
            report(90.0 * (m_i * len(angles) + a_i + 1) / (len(mirrors) * len(angles)))

    xmin, ymin = src.min(axis=0)
    xmax, ymax = src.max(axis=0)
    corners = np.array([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]])

    results, moves = [], []
    for matrix, mirrored in candidates:
        matched, P, Q = _score(matrix, src, dst_index, dst, dst_tree, radius)
        if matched < 2:
            continue
        errors, rms = residuals(matrix, P, Q)
        results.append(AutoResult(matrix, matched, len(src), P, Q, errors, rms, mirrored))
        moves.append(float(np.hypot(*(apply_matrix(matrix, corners) - corners).T).max()))
    # equal scores: the smaller error wins, then the smaller move (the objects are often almost aligned)
    order = sorted(range(len(results)),
                   key=lambda i: (-results[i].matched, round(results[i].rms / radius, 3), moves[i]))
    results = [results[i] for i in order]

    distinct = []
    for r in results:
        if not any(_same(r.matrix, k.matrix, corners, radius) for k in distinct):
            distinct.append(r)
        if len(distinct) == max_results:
            break
    report(100)

    if not distinct:
        raise AlignError("No alignment was found.")
    return distinct


def is_ambiguous(results):
    """True if a different candidate has almost the same score as the best one."""
    return len(results) >= 2 and results[0].matched > 0 and results[1].matched >= 0.95 * results[0].matched
