"""Document-wide batching of the simplest fills: one closed ring per element, built with vectorised Shapely calls."""
import logging

import numpy as np
import shapely

from . import paint
from .flatten import flatten_many

log = logging.getLogger('base')

_SHARED_EDGE = '****1****'  # the boundaries of two polygons meet along a line
_CHUNK = 4_000_000


class FillSlot:
    """Placeholder in the output list for the polygons of one single-ring element."""
    __slots__ = ('pts', 'coef', 'rule', 'geoms', 'recipe')

    def __init__(self, pts, coef, rule):
        self.pts, self.coef, self.rule, self.geoms = pts, coef, rule, []
        self.recipe = None


class FillBatch:
    """Collects single-ring fills in document order and builds all their polygons at once."""

    def __init__(self, polygons_only):
        """
        :param polygons_only: gerber mode (only affects the slow fallback)
        """
        self.polygons_only = polygons_only
        self.slots = []
        self._coefs = {}

    def _coef(self, m):
        """Affine coefficients (a, b, c, d, e, f) of a matrix, cached per matrix object (most elements share one)."""
        hit = self._coefs.get(id(m))
        if hit is None:
            hit = (m, (m[0, 0], m[0, 1], m[0, 2], m[1, 0], m[1, 1], m[1, 2]))
            self._coefs[id(m)] = hit
        return hit[1]

    def add(self, pts, m, rule):
        """
        :param pts: (N, 2) ring in user space, N >= 3
        :param m: 3x3 user -> output matrix
        :param rule: 'nonzero' or 'evenodd'
        :return: the slot that receives the geometries on resolve()
        """
        slot = FillSlot(pts, self._coef(m), rule)
        self.slots.append(slot)
        return slot

    def add_path(self, sub, tol, m, rule):
        """
        Like add() for a line/cubic subpath whose Beziers are flattened later, all together.

        :param sub: (start, segs, closed) from parse_path
        :param tol: Bezier tolerance in user units
        :param m: 3x3 user -> output matrix
        :param rule: 'nonzero' or 'evenodd'
        :return: the slot that receives the geometries on resolve()
        """
        slot = self.add(None, m, rule)
        slot.recipe = (sub[0], sub[1], tol)
        return slot

    def _flatten_paths(self):
        pending = [s for s in self.slots if s.pts is None]
        for slot, pts in zip(pending, flatten_many([s.recipe for s in pending])):
            slot.pts, slot.recipe = pts, None

    def resolve(self):
        """Fill the geoms of every slot."""
        slots = self.slots
        if not slots:
            return
        self._flatten_paths()
        slots = [s for s in slots if not _degenerate(s.pts)]
        if not slots:
            return
        lens = np.fromiter((len(s.pts) for s in slots), np.int64, len(slots))
        owner = np.repeat(np.arange(len(slots)), lens)
        xy = self._transformed(slots, lens)
        offsets = np.concatenate(([0], np.cumsum(lens)))
        try:
            polys = shapely.polygons(shapely.linearrings(xy, indices=owner))
        except (ValueError, shapely.errors.ShapelyError) as exc:
            log.debug('SVG import: batch build failed (%s), using the slow path', exc)
            for i in range(len(slots)):
                self._slow(slots[i], xy[offsets[i]:offsets[i + 1]])
            return
        valid = shapely.is_valid(polys)
        area = shapely.area(polys)
        for i in np.flatnonzero(valid & (area > 0)).tolist():
            slots[i].geoms = [polys[i]]
        bad = np.flatnonzero(~valid)
        if len(bad):
            self._repair(slots, polys, bad, xy, offsets)

    @staticmethod
    def _transformed(slots, lens):
        """Apply every element matrix to its points with one set of vector operations."""
        coords = np.concatenate([s.pts for s in slots])
        a, b, c, d, e, f = (np.repeat(col, lens) for col in np.array([s.coef for s in slots]).T)
        x, y = coords[:, 0], coords[:, 1]
        out = np.empty_like(coords)
        out[:, 0] = a * x + b * y + c
        out[:, 1] = d * x + e * y + f
        return out

    def _slow(self, slot, ring):
        """Exact per-element fill, used whenever the quick repair cannot guarantee the fill rule."""
        slot.geoms = paint.finish(paint.fill_polygons([ring], slot.rule), self.polygons_only)

    def _repair(self, slots, polys, bad, xy, offsets):
        """
        Exact fill of the invalid rings (self-touching or self-crossing) for all of them at once: node, polygonize,
        winding number of every face, union of the kept faces that share an edge.
        """
        rings = shapely.get_exterior_ring(polys[bad])
        faces, owner = shapely.get_parts(shapely.polygonize(shapely.node(rings)[:, None]), return_index=True)
        if len(faces) == 0:
            return
        wn = _winding_batch(shapely.get_coordinates(shapely.point_on_surface(faces)), bad[owner], xy, offsets)
        rule = np.array([slots[i].rule == 'nonzero' for i in bad])[owner]
        keep = np.where(rule, wn != 0, wn % 2 != 0)
        faces, owner = faces[keep], bad[owner[keep]]
        self._assign(slots, faces, owner)

    @staticmethod
    def _assign(slots, faces, owner):
        """Give every slot its kept faces, merging the faces that share an edge."""
        if len(faces) == 0:
            return
        starts = np.flatnonzero(np.concatenate(([True], owner[1:] != owner[:-1])))
        counts = np.diff(np.concatenate((starts, [len(faces)])))
        merge = counts > 2
        pairs = np.flatnonzero(counts == 2)
        if len(pairs):
            first = starts[pairs]
            shared = shapely.relate_pattern(faces[first], faces[first + 1], _SHARED_EDGE)
            merge[pairs[shared]] = True
        for g, (s0, c) in enumerate(zip(starts.tolist(), counts.tolist())):
            parts = faces[s0:s0 + c]
            if merge[g]:
                parts = shapely.get_parts(shapely.union_all(parts))
            slots[owner[s0]].geoms = list(parts)


def _winding_batch(points, element, xy, offsets):
    """
    :param points: (F, 2) one point per face
    :param element: (F,) slot index of every point, ascending
    :param xy: (N, 2) transformed ring points of all slots
    :param offsets: (S + 1,) start of every ring in xy
    :return: (F,) winding numbers of every point with respect to the ring of its own slot
    """
    nxt = np.arange(1, len(xy) + 1)
    nxt[offsets[1:] - 1] = offsets[:-1]
    cnt = (offsets[1:] - offsets[:-1])[element]
    out = np.zeros(len(points), dtype=np.int64)
    ends = np.cumsum(cnt)
    lo = 0
    while lo < len(points):
        hi = int(np.searchsorted(ends, ends[lo] - cnt[lo] + _CHUNK, side='right'))
        hi = max(hi, lo + 1)
        out[lo:hi] = _winding_chunk(points[lo:hi], element[lo:hi], cnt[lo:hi], xy, offsets, nxt)
        lo = hi
    return out


def _winding_chunk(points, element, cnt, xy, offsets, nxt):
    pt = np.repeat(np.arange(len(points)), cnt)
    first = np.cumsum(cnt) - cnt
    edge = offsets[element][pt] + (np.arange(len(pt)) - first[pt])
    x0, y0 = xy[edge, 0], xy[edge, 1]
    x1, y1 = xy[nxt[edge], 0], xy[nxt[edge], 1]
    px, py = points[pt, 0], points[pt, 1]
    left = (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)
    up = (y0 <= py) & (y1 > py) & (left > 0)
    down = (y1 <= py) & (y0 > py) & (left < 0)
    return np.bincount(pt, weights=up.astype(np.int8) - down.astype(np.int8), minlength=len(points)).astype(np.int64)


def _degenerate(pts):
    """A three point ring that returns to its start has no area (Polygon() refuses it)."""
    return len(pts) == 3 and pts[0, 0] == pts[2, 0] and pts[0, 1] == pts[2, 1]
