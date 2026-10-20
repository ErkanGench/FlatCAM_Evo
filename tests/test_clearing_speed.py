"""Run: python tests/test_clearing_speed.py

The seed clearing makes its rings in bands and cuts them from the margin without the holes and polygons that the
rings of a band cannot touch. It must give the paths of the ring-by-ring cut, bit for bit.
"""
import math
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_saved_argv = sys.argv
sys.argv = [sys.argv[0]]
try:
    import camlib
    import numpy as np
    import shapely
    from shapely import MultiPolygon, Point, Polygon, box
finally:
    sys.argv = _saved_argv

from test_clearing_paths import make_geometry

PAD_CENTERS = [(x, y) for x in range(3, 29, 3) for y in range(3, 20, 3)]
# (getattr and create=True: on the code before the bands the seed tests run too, and show its ring-by-ring cut)
SEED_BAND_MIN_COORDS = getattr(camlib.Geometry, 'SEED_BAND_MIN_COORDS', 2000)
SEED_BAND_RINGS = getattr(camlib.Geometry, 'SEED_BAND_RINGS', 16)


def band_limit(min_coords):
    """Sets Geometry.SEED_BAND_MIN_COORDS, the number of margin coordinates from which the margin is cut in bands."""
    return patch.object(camlib.Geometry, 'SEED_BAND_MIN_COORDS', min_coords, create=True)


def board(islands=False):
    """
    A board area of 30 x 21 mm with 54 round holes (the copper pads). With islands: the pads are rings and the area
    inside each ring is a separate polygon.
    """
    area = Polygon(box(0, 0, 30, 21).exterior.coords, [Point(c).buffer(0.7, quad_segs=16).exterior.coords
                                                       for c in PAD_CENTERS])
    if islands:
        area = MultiPolygon([area] + [Point(c).buffer(0.35, quad_segs=16) for c in PAD_CENTERS])
    return area


def margin_of(polygon, tooldia, steps=64, simplify_tol=0.0):
    margin = polygon.buffer(-tooldia / 2, quad_segs=camlib.circle_quad_segs(steps))
    return MultiPolygon(camlib.flatten_shapely_geometry(margin, simplify_tolerance=simplify_tol))


def seed_rings_one_by_one(polygon, tooldia, steps, overlap=0.15, simplify_tol=0.0):
    """
    The rings of clear_polygon_seed() cut from the whole margin one at a time (the code before the bands).

    :return:    the paths and the number of rings cut
    """
    quad_segs = camlib.circle_quad_segs(steps)
    radius = tooldia / 2 * (1 - overlap)
    margin = margin_of(polygon, tooldia, steps, simplify_tol)
    seedpoint = margin.representative_point()
    paths = []
    rings = 0
    while True:
        rings += 1
        path = Point(seedpoint).buffer(radius, quad_segs=quad_segs).exterior
        path = path.simplify(simplify_tol)
        path = path.intersection(margin)
        if path.is_empty:
            break
        paths += camlib.flatten_shapely_geometry(path, simplify_tolerance=simplify_tol)
        radius += tooldia * (1 - overlap)
    return paths, rings


class TestSeedBands(unittest.TestCase):
    def setUp(self):
        self.geometry = make_geometry()

    def seed_paths(self, polygon, tooldia, steps, simplify_tol=0.0):
        return list(self.geometry.clear_polygon_seed(
            polygon, tooldia, steps, connect=False, contour=False, simplify_tol=simplify_tol).get_objects())

    def test_banded_rings_are_the_rings_cut_one_by_one(self):
        for islands in (False, True):
            polygon = board(islands)
            for steps in (8, 16, 64):
                for simplify_tol in (0.0, 0.01):
                    expected, __ = seed_rings_one_by_one(polygon, 0.4, steps, simplify_tol=simplify_tol)
                    # the margin cut whole (fewer coordinates than SEED_BAND_MIN_COORDS) and cut in bands
                    for min_coords in (SEED_BAND_MIN_COORDS, 0):
                        with self.subTest(islands=islands, steps=steps, simplify_tol=simplify_tol,
                                          min_coords=min_coords), band_limit(min_coords):
                            paths = self.seed_paths(polygon, 0.4, steps, simplify_tol)
                            self.assertEqual([p.wkb for p in paths], [p.wkb for p in expected])

    def test_rings_stop_at_the_first_ring_that_misses_the_margin(self):
        # 2 areas 3 mm apart: the rings grown in the area of the seed stop in the gap, the other area gets no ring
        # (the later rings of the same band reach it)
        polygon = MultiPolygon([box(0, 0, 4, 4), box(7, 0, 11, 4)]).buffer(0)
        expected, __ = seed_rings_one_by_one(polygon, 0.5, 64)
        self.assertTrue(all(p.bounds[2] < 5 for p in expected) or all(p.bounds[0] > 6 for p in expected))
        for min_coords in (SEED_BAND_MIN_COORDS, 0):
            with self.subTest(min_coords=min_coords), band_limit(min_coords):
                self.assertEqual([p.wkb for p in self.seed_paths(polygon, 0.5, 64)], [p.wkb for p in expected])

    def test_a_small_area_gets_its_rings_in_1_call(self):
        # 3 rings touch the margin of a 2 mm square: no band of SEED_BAND_RINGS rings is made for it
        polygon = box(0, 0, 2, 2)
        expected, rings = seed_rings_one_by_one(polygon, 0.4, 64)
        original = shapely.buffer
        ring_calls = []

        def recorded(geometry, distance, *args, **kwargs):
            if isinstance(geometry, Point):
                ring_calls.append(np.size(distance))
            return original(geometry, distance, *args, **kwargs)

        with patch.object(shapely, 'buffer', recorded):
            paths = self.seed_paths(polygon, 0.4, 64)
        self.assertEqual([p.wkb for p in paths], [p.wkb for p in expected])
        self.assertEqual(len(ring_calls), 1)
        self.assertLessEqual(ring_calls[0], rings + 2)

    def test_a_large_margin_is_cut_without_the_holes_out_of_the_band(self):
        polygon = board()
        tooldia = 0.4
        margin_coords = shapely.get_num_coordinates(margin_of(polygon, tooldia))
        original = shapely.intersection
        cuts = []

        def recorded(a, b, *args, **kwargs):
            cuts.append(shapely.get_num_coordinates(b))
            return original(a, b, *args, **kwargs)

        with band_limit(0), patch.object(shapely, 'intersection', recorded):
            paths = self.seed_paths(polygon, tooldia, 64)
        __, rings = seed_rings_one_by_one(polygon, tooldia, 64)
        self.assertGreater(rings, 3 * SEED_BAND_RINGS)
        self.assertGreater(len(paths), 0)
        # one cut for each band of SEED_BAND_RINGS rings, not one for each ring
        self.assertLessEqual(len(cuts), math.ceil(rings / SEED_BAND_RINGS) + 1)
        # each band holds a part of the margin
        self.assertLess(sum(cuts), len(cuts) * margin_coords / 2)

    def test_band_margin_keeps_the_parts_in_the_band(self):
        margin = margin_of(board(islands=True), 0.4)
        center = Point(14, 10)
        near, far = 4.0, 7.5
        band = camlib.seed_band_margin(margin, center)(near, far)
        # the same envelope; the kept polygons and holes keep their coordinates
        self.assertEqual(band.bounds, margin.bounds)
        margin_rings = {ring.wkb for p in margin.geoms for ring in [p.exterior, *p.interiors]}
        band_rings = [ring for p in band.geoms for ring in [p.exterior, *p.interiors]]
        self.assertTrue(all(ring.wkb in margin_rings for ring in band_rings))
        # a hole or an island is kept when its area reaches the annulus between near and far
        annulus = center.buffer(far, quad_segs=256).difference(center.buffer(near, quad_segs=256))
        # (the board area holds the holes; the islands are the other polygons)
        holes = [Polygon(ring) for p in margin.geoms for ring in p.interiors]
        kept_holes = [Polygon(ring) for p in band.geoms for ring in p.interiors]
        islands = [p for p in margin.geoms if not p.interiors]
        kept_islands = [p for p in band.geoms if not p.interiors]
        self.assertEqual([h.wkb for h in kept_holes], [h.wkb for h in holes if h.intersects(annulus)])
        self.assertEqual([i.wkb for i in kept_islands], [i.wkb for i in islands if i.intersects(annulus)])
        self.assertTrue(0 < len(kept_holes) < len(holes) and 0 < len(kept_islands) < len(islands))


if __name__ == '__main__':
    unittest.main()
