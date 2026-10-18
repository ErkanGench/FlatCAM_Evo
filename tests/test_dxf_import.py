"""Tests for the appParsers.DXF importer; run directly: python tests/test_dxf_import.py"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ezdxf
from shapely.ops import unary_union

from appParsers.DXF import dxf_to_shapes, text_entity_to_shapes
from appParsers.DXF import text as dxf_text


def new_doc():
    doc = ezdxf.new()
    return doc, doc.modelspace()


class DxfImportTest(unittest.TestCase):

    def test_point_line(self):
        doc, msp = new_doc()
        msp.add_point((3, 4))
        msp.add_line((0, 0), (10, 0))
        msp.add_line((1, 1), (1, 1))  # zero length: skipped
        shapes = dxf_to_shapes(doc)
        self.assertEqual(sorted(s.geom_type for s in shapes), ['LineString', 'Polygon'])
        poly = [s for s in shapes if s.geom_type == 'Polygon'][0]
        self.assertAlmostEqual(poly.centroid.x, 3, places=3)
        self.assertAlmostEqual(poly.area, math.pi * 0.01 ** 2, places=4)

    def test_circle(self):
        doc, msp = new_doc()
        msp.add_circle((1, 2), 5)
        (poly,) = dxf_to_shapes(doc)
        self.assertEqual(poly.geom_type, 'Polygon')
        self.assertAlmostEqual(poly.area, 78.54, delta=0.3)
        self.assertGreaterEqual(len(poly.exterior.coords) - 1, 100)
        self.assertAlmostEqual(poly.centroid.x, 1, places=3)

    def test_arc(self):
        doc, msp = new_doc()
        msp.add_arc((0, 0), 10, 0, 90)
        (line,) = dxf_to_shapes(doc)
        self.assertEqual(line.geom_type, 'LineString')
        self.assertAlmostEqual(line.length, 15.708, delta=0.02)
        b = line.bounds
        self.assertAlmostEqual(b[2], 10, places=3)
        self.assertAlmostEqual(b[3], 10, places=3)

    def test_lwpolyline_bulge_and_closed(self):
        doc, msp = new_doc()
        # half circle of diameter 10 (bulge 1): length = pi * 5
        msp.add_lwpolyline([(0, 0, 0, 0, 1), (10, 0)])
        msp.add_lwpolyline([(0, 0), (4, 0), (4, 3)], close=True)
        half, tri = dxf_to_shapes(doc)
        self.assertEqual(half.geom_type, 'LineString')
        self.assertAlmostEqual(half.length, math.pi * 5, delta=0.03)
        self.assertEqual(tri.geom_type, 'LineString')
        self.assertTrue(tri.is_ring)
        self.assertAlmostEqual(tri.length, 12, places=6)

    def test_polyline_2d_3d(self):
        doc, msp = new_doc()
        msp.add_polyline2d([(0, 0), (5, 0), (5, 5)])
        msp.add_polyline3d([(0, 0, 0), (3, 4, 9)])
        a, b = dxf_to_shapes(doc)
        self.assertAlmostEqual(a.length, 10, places=6)
        self.assertAlmostEqual(b.length, 5, places=6)  # Z dropped
        self.assertFalse(b.has_z)

    def test_solid_trace_3dface(self):
        doc, msp = new_doc()
        msp.add_solid([(0, 0), (4, 0), (0, 3), (4, 3)])  # stored order 0,1,3,2: a rectangle
        msp.add_trace([(0, 0), (2, 0), (0, 2), (2, 2)])
        msp.add_3dface([(0, 0, 1), (3, 0, 2), (3, 3, 3), (0, 3, 4)])
        solid, trace, face = dxf_to_shapes(doc)
        self.assertEqual(solid.geom_type, 'Polygon')
        self.assertAlmostEqual(solid.area, 12)
        self.assertAlmostEqual(trace.area, 4)
        self.assertAlmostEqual(face.area, 9)

    def test_ellipse(self):
        doc, msp = new_doc()
        msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5)
        msp.add_ellipse((0, 0), major_axis=(10, 0), ratio=0.5, start_param=0, end_param=math.pi)
        full, half = dxf_to_shapes(doc)
        self.assertEqual(full.geom_type, 'LineString')
        self.assertTrue(full.is_ring)
        # Ramanujan perimeter for a=10, b=5
        a, b = 10, 5
        h = ((a - b) / (a + b)) ** 2
        perimeter = math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
        self.assertAlmostEqual(full.length, perimeter, delta=0.05)
        self.assertAlmostEqual(half.length, perimeter / 2, delta=0.05)
        self.assertFalse(half.is_ring)
        self.assertAlmostEqual(half.bounds[1], 0, places=3)

    def test_spline(self):
        doc, msp = new_doc()
        msp.add_spline(fit_points=[(0, 0), (5, 5), (10, 0), (15, 5)])
        (line,) = dxf_to_shapes(doc)
        self.assertEqual(line.geom_type, 'LineString')
        self.assertAlmostEqual(line.coords[0][0], 0, places=6)
        self.assertAlmostEqual(line.coords[0][1], 0, places=6)
        self.assertAlmostEqual(line.coords[-1][0], 15, places=6)
        self.assertAlmostEqual(line.coords[-1][1], 5, places=6)

    def test_extrusion_mirrors_arc(self):
        doc, msp = new_doc()
        msp.add_arc((10, 0), 5, 0, 90, dxfattribs={'extrusion': (0, 0, -1)})
        msp.add_circle((10, 0), 1, dxfattribs={'extrusion': (0, 0, -1)})
        arc, circle = dxf_to_shapes(doc)
        b = arc.bounds
        self.assertAlmostEqual(b[0], -15, places=3)
        self.assertAlmostEqual(b[2], -10, places=3)
        self.assertAlmostEqual(b[1], 0, places=3)
        self.assertAlmostEqual(b[3], 5, places=3)
        self.assertAlmostEqual(circle.centroid.x, -10, places=3)

    def test_insert_transform(self):
        doc, msp = new_doc()
        blk = doc.blocks.new('B')
        blk.add_line((0, 0), (1, 0))
        msp.add_blockref('B', (10, 5), dxfattribs={'xscale': -2, 'yscale': 2, 'rotation': 90})
        (line,) = dxf_to_shapes(doc)
        (x0, y0), (x1, y1) = line.coords
        self.assertAlmostEqual(x0, 10, places=6)
        self.assertAlmostEqual(y0, 5, places=6)
        self.assertAlmostEqual(x1, 10, places=6)
        self.assertAlmostEqual(y1, 3, places=6)

    def test_insert_nested(self):
        doc, msp = new_doc()
        doc.blocks.new('A').add_line((0, 0), (1, 0))
        doc.blocks.new('B').add_blockref('A', (5, 0))
        msp.add_blockref('B', (0, 10))
        (line,) = dxf_to_shapes(doc)
        self.assertEqual(tuple(line.bounds), (5, 10, 6, 10))

    def test_minsert(self):
        doc, msp = new_doc()
        doc.blocks.new('A').add_line((0, 0), (1, 0))
        msp.add_blockref('A', (0, 0)).grid(size=(2, 2), spacing=(5, 10))
        shapes = dxf_to_shapes(doc)
        self.assertEqual(len(shapes), 4)
        starts = sorted(s.coords[0] for s in shapes)
        # grid(spacing=(row, column)): rows 5 apart in Y, columns 10 apart in X
        self.assertEqual(starts, [(0, 0), (0, 5), (10, 0), (10, 5)])

    def test_bad_entity_does_not_stop(self):
        doc, msp = new_doc()
        msp.add_line((0, 0), (1, 0))
        bad = msp.add_circle((0, 0), 1)
        bad.dxf.radius = 0  # degenerate
        msp.add_polyline2d([(0, 0)])  # single vertex
        msp.add_blockref('MISSING', (0, 0))
        msp.add_line((0, 5), (1, 5))
        shapes = dxf_to_shapes(doc)
        self.assertEqual(len([s for s in shapes if s.geom_type == 'LineString']), 2)

    def test_huge_radius_is_finite(self):
        doc, msp = new_doc()
        msp.add_arc((0, 0), 1e7, 0, 90)
        (line,) = dxf_to_shapes(doc)
        self.assertLess(len(line.coords), 20000)

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_text_modes(self):
        doc, msp = new_doc()
        msp.add_text('ABC', dxfattribs={'height': 2.5})
        stroke = dxf_to_shapes(doc, 'stroke')
        outline = dxf_to_shapes(doc, 'outline')
        self.assertTrue(stroke and all(s.geom_type == 'LineString' for s in stroke))
        self.assertTrue(outline and all(s.geom_type == 'Polygon' for s in outline))
        self.assertEqual(dxf_to_shapes(doc, 'none'), [])
        self.assertEqual(text_entity_to_shapes(list(msp)[0], 'none'), [])
        self.assertTrue(all(math.isfinite(v) for g in outline for v in g.bounds))

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_text_hole_in_outline(self):
        doc, msp = new_doc()
        msp.add_text('O', dxfattribs={'height': 5})
        outline = dxf_to_shapes(doc, 'outline')
        self.assertTrue(any(len(p.interiors) == 1 for p in outline))

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_text_in_block(self):
        doc, msp = new_doc()
        doc.blocks.new('T').add_text('AB', dxfattribs={'height': 2})
        msp.add_blockref('T', (100, 100))
        shapes = dxf_to_shapes(doc, 'stroke')
        self.assertTrue(shapes)
        self.assertGreaterEqual(unary_union(shapes).bounds[0], 99)
        self.assertEqual(dxf_to_shapes(doc, 'none'), [])

    @staticmethod
    def _square(x, y, size):
        return [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]

    def _hatch(self, msp, *paths):
        hatch = msp.add_hatch()
        for pts in paths:
            hatch.paths.add_polyline_path(pts, is_closed=True)
        return hatch

    def test_hatch_hole(self):
        doc, msp = new_doc()
        self._hatch(msp, self._square(0, 0, 10), self._square(2, 2, 4))
        shapes = dxf_to_shapes(doc)
        self.assertEqual(len(shapes), 1)
        self.assertEqual(len(shapes[0].interiors), 1)
        self.assertAlmostEqual(shapes[0].area, 100 - 16, places=6)

    def test_hatch_island_in_hole(self):
        doc, msp = new_doc()
        self._hatch(msp, self._square(0, 0, 20), self._square(2, 2, 12), self._square(5, 5, 4))
        shapes = dxf_to_shapes(doc)
        self.assertEqual(len(shapes), 2)
        self.assertAlmostEqual(sum(s.area for s in shapes), 400 - 144 + 16, places=6)

    def test_invisible_entity_skipped(self):
        doc, msp = new_doc()
        msp.add_line((0, 0), (1, 0), dxfattribs={'invisible': 1})
        msp.add_line((0, 1), (1, 1))
        shapes = dxf_to_shapes(doc)
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0].bounds[1], 1)

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_invisible_attrib_skipped(self):
        doc, msp = new_doc()
        doc.blocks.new('A').add_line((0, 0), (1, 0))
        shown = msp.add_blockref('A', (0, 0))
        shown.add_attrib('T1', 'ABC', (0, 10), dxfattribs={'height': 2})
        hidden = msp.add_blockref('A', (0, 100))
        hidden.add_attrib('T2', 'ABC', (0, 110), dxfattribs={'height': 2})
        hidden.attribs[0].is_invisible = True
        shapes = dxf_to_shapes(doc, 'stroke')
        self.assertTrue(any(9 <= s.bounds[1] and s.bounds[3] < 20 for s in shapes))
        self.assertFalse(any(s.bounds[1] >= 105 for s in shapes))
        self.assertTrue(any(s.bounds[1] == 100 for s in shapes))  # the block line itself

    def test_off_and_frozen_layers_skipped(self):
        doc, msp = new_doc()
        doc.layers.add('OFF').off()
        doc.layers.add('FROZEN').freeze()
        doc.layers.add('ON')
        for name in ('OFF', 'FROZEN', 'ON'):
            msp.add_line((0, 0), (1, 0), dxfattribs={'layer': name})
        doc.blocks.new('B').add_line((0, 5), (1, 5))  # layer '0': takes the layer of the INSERT
        msp.add_blockref('B', (0, 0), dxfattribs={'layer': 'FROZEN'})
        msp.add_blockref('B', (0, 10), dxfattribs={'layer': 'ON'})
        shapes = dxf_to_shapes(doc)
        self.assertEqual(sorted(s.bounds[1] for s in shapes), [0, 15])

    def test_scaled_circle_in_block_stays_filled(self):
        doc, msp = new_doc()
        doc.blocks.new('C').add_circle((0, 0), 5)
        msp.add_blockref('C', (10, 10), dxfattribs={'xscale': 2, 'yscale': 3})
        msp.add_blockref('C', (50, 10), dxfattribs={'xscale': 2, 'yscale': 2})
        scaled, uniform = dxf_to_shapes(doc)
        self.assertEqual(scaled.geom_type, 'Polygon')
        self.assertAlmostEqual(scaled.area, math.pi * 25 * 6, delta=0.01 * math.pi * 25 * 6)
        self.assertEqual(uniform.geom_type, 'Polygon')
        self.assertAlmostEqual(uniform.area, math.pi * 100, delta=1)

    def test_real_ellipse_in_block_stays_line(self):
        doc, msp = new_doc()
        doc.blocks.new('E').add_ellipse((0, 0), major_axis=(5, 0), ratio=0.5)
        msp.add_blockref('E', (0, 0), dxfattribs={'xscale': 2, 'yscale': 3})
        (shape,) = dxf_to_shapes(doc)
        self.assertEqual(shape.geom_type, 'LineString')

    def test_inch_drawing_flattens_finer(self):
        counts = {}
        for units in (0, 4, 1):
            doc, msp = new_doc()
            doc.header['$INSUNITS'] = units
            msp.add_arc((0, 0), 10, 0, 90)
            (line,) = dxf_to_shapes(doc)
            counts[units] = len(line.coords)
        self.assertGreater(counts[1], counts[4])
        self.assertEqual(counts[0], counts[4])  # unitless = mm

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_invalid_text_mode_is_stroke(self):
        doc, msp = new_doc()
        msp.add_text('ABC', dxfattribs={'height': 2.5})
        shapes = dxf_to_shapes(doc, 'bogus')
        self.assertTrue(shapes and all(s.geom_type == 'LineString' for s in shapes))

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_mtext_modes_and_lines(self):
        doc, msp = new_doc()
        one = msp.add_mtext('Hello', dxfattribs={'insert': (10, 20), 'char_height': 2.5})
        two = msp.add_mtext('Hello\\PWorld', dxfattribs={'insert': (10, 20), 'char_height': 2.5})
        for mode, kind in (('stroke', 'LineString'), ('outline', 'Polygon')):
            boxes = []
            for entity in (one, two):
                shapes = text_entity_to_shapes(entity, mode)
                self.assertTrue(shapes)
                self.assertTrue(all(s.geom_type == kind for s in shapes))
                boxes.append(unary_union(shapes).bounds)
            self.assertGreaterEqual(boxes[0][0], 9.9)
            self.assertGreater(boxes[1][3] - boxes[1][1], 1.5 * (boxes[0][3] - boxes[0][1]))
            self.assertLess(boxes[1][3] - boxes[1][1], 12)
            self.assertTrue(dxf_to_shapes(doc, mode))
        self.assertEqual(dxf_to_shapes(doc, 'none'), [])

    @unittest.skipUnless(dxf_text.TEXT_RENDERING_AVAILABLE, 'text rendering unavailable')
    def test_mtext_in_block_and_attdef_skipped(self):
        doc, msp = new_doc()
        blk = doc.blocks.new('M')
        blk.add_mtext('AB\\PCD', dxfattribs={'insert': (0, 0), 'char_height': 2})
        blk.add_attdef('TAG', (0, -10), 'XYZ', dxfattribs={'height': 2})
        names = set(b.name for b in doc.blocks)
        msp.add_blockref('M', (100, 100))
        shapes = dxf_to_shapes(doc, 'stroke')
        self.assertTrue(shapes)
        bounds = unary_union(shapes).bounds
        self.assertGreaterEqual(bounds[0], 99)
        self.assertGreater(bounds[1], 90)  # nothing from the ATTDEF at y = 90
        self.assertEqual(set(b.name for b in doc.blocks), names)  # scratch block removed


if __name__ == '__main__':
    unittest.main()
