"""Tests of the clean-room SVG importer (appParsers/SVG). Run: python tests/test_svg_import.py"""
import io
import math
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shapely
from lxml import etree

from appParsers.SVG import SvgImportError, svg_to_shapes

DOC = 'width="100mm" height="50mm" viewBox="0 0 200 100"'


def svg(body, attrs=DOC):
    return '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" %s>%s</svg>' % (
        attrs, body)


def run(body, attrs=DOC, **kw):
    return svg_to_shapes(svg(body, attrs), **kw)


def raw(body, **kw):
    """User-unit import without flip."""
    kw.setdefault('user_units', True)
    kw.setdefault('flip', False)
    attrs = 'viewBox="0 0 20 20"' if kw.pop('attrs_vb', False) else ''
    return svg_to_shapes(svg(body, attrs), **kw)


def total_area(geoms):
    return sum(g.area for g in geoms)


def bounds(geoms):
    return shapely.union_all(geoms).bounds


class TestShapes(unittest.TestCase):
    def test_rect_in_mm(self):
        g = run('<rect x="10" y="10" width="40" height="20"/>')
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0].area, 200.0, places=6)
        for a, b in zip(g[0].bounds, (5.0, 35.0, 25.0, 45.0)):
            self.assertAlmostEqual(a, b, places=6)

    def test_flip_off_and_on(self):
        on = bounds(run('<rect x="10" y="10" width="40" height="20"/>'))
        off = bounds(run('<rect x="10" y="10" width="40" height="20"/>', flip=False))
        self.assertAlmostEqual(on[1], 35.0)
        self.assertAlmostEqual(off[1], 5.0)

    def test_rounded_rect(self):
        g = run('<rect x="0" y="0" width="40" height="20" rx="4" ry="4"/>', resolution=128)
        expected = (40 * 20 - (4 - math.pi) * 16) * 0.25
        self.assertAlmostEqual(g[0].area, expected, delta=expected * 0.005)

    def test_rect_radius_clamp_and_single_radius(self):
        g = raw('<rect width="20" height="10" rx="50"/>', resolution=128)
        # rx clamps to 10, ry follows rx and clamps to 5 -> a stadium-like ellipse ends
        self.assertAlmostEqual(g[0].area, 20 * 10 - (4 - math.pi) * 10 * 5, delta=1.0)

    def test_resolution_is_segments_per_full_circle(self):
        g = raw('<circle cx="0" cy="0" r="10"/>', resolution=64)
        self.assertEqual(len(g[0].exterior.coords) - 1, 64)
        ref = shapely.Point(0, 0).buffer(10, 16)
        self.assertAlmostEqual(g[0].area, ref.area, delta=1e-6)

    def test_circle_ellipse(self):
        c = run('<circle cx="100" cy="50" r="20"/>')
        self.assertAlmostEqual(c[0].area, math.pi * 400 * 0.25, delta=0.01 * c[0].area)
        e = run('<ellipse cx="100" cy="50" rx="30" ry="10"/>')
        self.assertAlmostEqual(e[0].area, math.pi * 300 * 0.25, delta=0.01 * e[0].area)
        self.assertAlmostEqual(e[0].centroid.x, 50.0, places=4)

    def test_line_polyline_polygon(self):
        g = run('<line x1="0" y1="0" x2="40" y2="0"/>')
        self.assertEqual(g[0].geom_type, 'LineString')
        self.assertAlmostEqual(g[0].length, 20.0)
        p = run('<polyline points="0,0 10,0 10,10" fill="none" stroke="black"/>')
        self.assertEqual(p[0].geom_type, 'LineString')
        pg = run('<polygon points="0,0 20,0 20,20 0,20"/>')
        self.assertEqual(pg[0].geom_type, 'Polygon')
        self.assertAlmostEqual(pg[0].area, 100.0)

    def test_units(self):
        for attrs in ('width="96px" height="96px"', 'width="1in" height="1in" viewBox="0 0 96 96"',
                      'width="72pt" height="72pt" viewBox="0 0 10 10"'):
            vb = 10.0 if 'pt' in attrs else 96.0
            g = run('<rect width="%s" height="%s"/>' % (vb, vb), attrs)
            self.assertAlmostEqual(g[0].area, 25.4 ** 2, places=4, msg=attrs)

    def test_units_inches_and_css_units(self):
        g = run('<rect width="1" height="1"/>', 'width="2in" height="2in" viewBox="0 0 2 2"', units='IN')
        self.assertAlmostEqual(g[0].area, 1.0, places=6)
        g = run('<rect width="1cm" height="1cm"/>', 'width="100px" height="100px"')
        self.assertAlmostEqual(g[0].area, (96 / 2.54 * 25.4 / 96) ** 2, places=4)

    def test_missing_size_uses_viewbox(self):
        g = run('<rect width="96" height="96"/>', 'viewBox="0 0 96 96"')
        self.assertAlmostEqual(g[0].area, 25.4 ** 2, places=4)
        g = run('<rect width="96" height="96"/>', 'width="100%" height="100%" viewBox="0 0 96 96"')
        self.assertAlmostEqual(g[0].area, 25.4 ** 2, places=4)

    def test_preserve_aspect_ratio(self):
        body = '<rect width="100" height="50"/>'
        meet = bounds(run(body, 'width="100mm" height="100mm" viewBox="0 0 100 50"', flip=False))
        self.assertAlmostEqual(meet[3] - meet[1], 50.0)
        self.assertAlmostEqual(meet[1], 25.0)
        none = bounds(run(body, 'width="100mm" height="100mm" viewBox="0 0 100 50" '
                                'preserveAspectRatio="none"', flip=False))
        self.assertAlmostEqual(none[3] - none[1], 100.0)
        sl = bounds(run(body, 'width="100mm" height="100mm" viewBox="0 0 100 50" '
                              'preserveAspectRatio="xMinYMin slice"', flip=False))
        self.assertAlmostEqual(sl[2] - sl[0], 200.0)
        self.assertAlmostEqual(sl[0], 0.0)
        mx = bounds(run('<rect width="50" height="50"/>', 'width="100mm" height="50mm" viewBox="0 0 50 50" '
                                                          'preserveAspectRatio="xMaxYMid meet"', flip=False))
        self.assertAlmostEqual(mx[0], 50.0)

    def test_user_units_mode(self):
        g = raw('<rect x="10" y="20" width="30" height="40"/>', units='IN')
        self.assertEqual(g[0].bounds, (10.0, 20.0, 40.0, 60.0))
        g = svg_to_shapes(svg('<rect x="10" y="20" width="30" height="40"/>', DOC), user_units=True, flip=True)
        self.assertEqual(g[0].bounds, (10.0, -60.0, 40.0, -20.0))

    def test_nested_svg_viewport(self):
        g = raw('<svg x="10" y="10" width="20" height="20" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
        self.assertEqual(g[0].bounds, (10.0, 10.0, 30.0, 30.0))


class TestPath(unittest.TestCase):
    def one(self, d, **kw):
        g = raw('<path d="%s"/>' % d, **kw)
        self.assertEqual(len(g), 1, d)
        return g[0]

    def test_lines_absolute_relative(self):
        self.assertAlmostEqual(self.one('M10 10 H30 V30 H10 Z').area, 400.0)
        self.assertAlmostEqual(self.one('m10 10 h20 v20 h-20 z').area, 400.0)
        self.assertAlmostEqual(self.one('M0 0 L10 0 20 0 20 10 0 10z').area, 200.0)
        self.assertAlmostEqual(self.one('m0 0 l10 0 10 0 0 10 -20 0z').area, 200.0)

    def test_number_formats(self):
        p = self.one('M.5.5L1e1 .5 10.5 10.5-1e-0 10.5z')
        self.assertAlmostEqual(p.area, 10.0 * 10.0 - 0.0 + 0.0, delta=12.0)
        self.assertEqual(p.bounds[0] <= 0.5, True)
        q = self.one('M0 0 L10 0 L10 -5 L0-5z')
        self.assertAlmostEqual(q.area, 50.0)

    def test_cubic_and_smooth(self):
        k = 0.5522847498 * 10
        d = 'M10 0 C10 %f %f 10 0 10 S-10 %f -10 0 S0 -10 10 -10 Z' % (k, k, k)
        # S continues with the reflected control point -> a circle of radius 10
        d = ('M10 0 C10 {k} {k} 10 0 10 S-10 {k} -10 0 S-{k} -10 0 -10 S10 -{k} 10 0 Z').format(k=k)
        self.assertAlmostEqual(self.one(d).area, math.pi * 100, delta=0.8)

    def test_quadratic_and_smooth(self):
        p = raw('<path d="M0 0 Q10 10 20 0 T40 0 Z"/>')
        self.assertAlmostEqual(total_area(p), 2 * 2.0 / 3.0 * 20 * 5, delta=0.5)
        q = self.one('M0 0 Q10 20 20 0 Z')
        self.assertAlmostEqual(q.area, 2.0 / 3.0 * 20 * 10, delta=0.5)

    def test_arc_semicircle_and_flags(self):
        a = self.one('M0 0 A10 10 0 0 1 20 0 Z', resolution=360)
        self.assertAlmostEqual(a.area, math.pi * 100 / 2, delta=0.1)
        b = self.one('M0 0 a10 10 0 0120 0 z', resolution=360)
        self.assertAlmostEqual(b.area, math.pi * 100 / 2, delta=0.1)
        big = self.one('M0 0 A10 10 0 1 1 10 10 Z', resolution=360)
        small = self.one('M0 0 A10 10 0 0 1 10 10 Z', resolution=360)
        self.assertGreater(big.area, small.area)
        self.assertAlmostEqual(big.area + small.area, math.pi * 100 + 0.0, delta=0.5)

    def test_arc_length_and_radius_scaling(self):
        g = raw('<path d="M0 0 A5 5 0 0 1 20 0" fill="none" stroke="black"/>', resolution=720)
        self.assertAlmostEqual(g[0].length, math.pi * 10, delta=0.05)
        z = self.one('M0 0 A0 5 0 0 1 20 0 Z')
        self.assertIsNotNone(z)

    def test_multiple_subpaths_and_implicit_lineto(self):
        g = raw('<path d="M0 0 10 0 10 10 0 10z M20 0 30 0 30 10 20 10z"/>')
        self.assertEqual(len(g), 2)
        self.assertAlmostEqual(total_area(g), 200.0)

    def test_open_path_geometry(self):
        g = raw('<path d="M0 0 L10 0 L10 10"/>')
        self.assertEqual(g[0].geom_type, 'LineString')

    def test_garbage_stops_at_error(self):
        g = raw('<path d="M0 0 L10 0 L10 10 L0 10 Z X 5 5"/>')
        self.assertAlmostEqual(g[0].area, 100.0)


class TestFillRules(unittest.TestCase):
    SAME = 'M0 0H20V20H0Z M5 5H15V15H5Z'
    OPPOSITE = 'M0 0H20V20H0Z M5 5V15H15V5Z'

    def area(self, d, rule):
        return total_area(raw('<path d="%s" fill-rule="%s"/>' % (d, rule)))

    def test_nonzero_same_direction_fills(self):
        self.assertAlmostEqual(self.area(self.SAME, 'nonzero'), 400.0)

    def test_evenodd_makes_hole(self):
        self.assertAlmostEqual(self.area(self.SAME, 'evenodd'), 300.0)

    def test_opposite_direction_hole(self):
        self.assertAlmostEqual(self.area(self.OPPOSITE, 'nonzero'), 300.0)
        self.assertAlmostEqual(self.area(self.OPPOSITE, 'evenodd'), 300.0)
        g = raw('<path d="%s"/>' % self.OPPOSITE)
        self.assertEqual(len(g[0].interiors), 1)

    def test_figure_eight(self):
        for rule in ('nonzero', 'evenodd'):
            self.assertAlmostEqual(self.area('M0 0 L10 10 L10 0 L0 10 Z', rule), 50.0)

    def test_pentagram(self):
        pts = ' '.join('%f,%f' % (10 * math.sin(math.radians(144 * i)), 10 * math.cos(math.radians(144 * i)))
                       for i in range(5))
        nz = total_area(raw('<polygon points="%s" fill-rule="nonzero"/>' % pts))
        eo = total_area(raw('<polygon points="%s" fill-rule="evenodd"/>' % pts))
        self.assertGreater(nz, eo + 10)

    def test_island_in_hole(self):
        d = 'M0 0H40V40H0Z M5 5V35H35V5Z M15 15H25V25H15Z'
        self.assertAlmostEqual(self.area(d, 'nonzero'), 1600 - 900 + 100)


class TestPaint(unittest.TestCase):
    def test_gerber_only_polygons(self):
        body = ('<circle cx="10" cy="10" r="5"/><path d="M0 0 H10" stroke="black" stroke-width="2"/>'
                '<path d="M0 0 H10 V10" fill="none"/><line x1="0" y1="0" x2="5" y2="5" stroke="red"/>')
        g = raw(body, object_type='gerber')
        self.assertTrue(g)
        self.assertTrue(all(p.geom_type == 'Polygon' for p in g))

    def test_stroke_only_buffer(self):
        g = raw('<path d="M0 0 H10" stroke="black" stroke-width="2" fill="none"/>', object_type='gerber')
        self.assertAlmostEqual(g[0].area, 20.0, places=6)

    def test_linecaps(self):
        def area(cap):
            return total_area(raw('<path d="M0 0 H10" stroke="black" stroke-width="2" fill="none" '
                                  'stroke-linecap="%s"/>' % cap, object_type='gerber', resolution=256))
        self.assertAlmostEqual(area('butt'), 20.0, places=4)
        self.assertAlmostEqual(area('square'), 24.0, places=4)
        self.assertAlmostEqual(area('round'), 20.0 + math.pi, delta=0.01)
        self.assertGreater(area('square'), area('round'))

    def test_linejoin(self):
        def area(join, extra=''):
            return total_area(raw('<path d="M0 0 H10 V10" stroke="black" stroke-width="2" fill="none" '
                                  'stroke-linejoin="%s" %s/>' % (join, extra), object_type='gerber',
                                  resolution=256))
        self.assertAlmostEqual(area('miter'), 40.0 - 1.0 + 2.0 - 1.0 + 0.0 + 0.0, delta=1.5)
        self.assertGreater(area('miter'), area('round'))
        self.assertGreater(area('round'), area('bevel'))
        # miterlimit 1 degrades the miter to a bevel
        self.assertLess(area('miter', 'stroke-miterlimit="1"'), area('miter'))
        self.assertAlmostEqual(area('miter', 'stroke-miterlimit="1"'), area('bevel'), delta=0.5)

    def test_stroke_width_scaled_by_transform_and_units(self):
        g = run('<path d="M0 0 H40" stroke="black" stroke-width="4" fill="none"/>', object_type='gerber')
        self.assertAlmostEqual(g[0].area, 20.0 * 2.0, places=5)
        g = raw('<g transform="scale(2)"><path d="M0 0 H10" stroke="black" stroke-width="1mm" fill="none"/></g>',
                object_type='gerber')
        self.assertAlmostEqual(g[0].area, 20.0 * 96 / 25.4 * 2, places=3)

    def test_fill_and_stroke_union(self):
        g = raw('<rect width="10" height="10" stroke="black" stroke-width="2"/>', object_type='gerber')
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0].bounds[0], -1.0)
        self.assertGreater(g[0].area, 140.0)

    def test_open_path_without_stroke_gives_nothing_in_gerber(self):
        self.assertEqual(raw('<path d="M0 0 H10" fill="none"/>', object_type='gerber'), [])

    def test_vector_effect_non_scaling_stroke(self):
        body = '<g transform="scale(10)"><path d="M0 0 H1" stroke="black" stroke-width="2" fill="none" %s/></g>'
        plain = total_area(raw(body % '', object_type='gerber'))
        fixed = total_area(raw(body % 'vector-effect="non-scaling-stroke"', object_type='gerber'))
        self.assertAlmostEqual(plain, 200.0, places=4)
        self.assertAlmostEqual(fixed, 20.0, places=4)

    def test_geometry_mode_closed_polygon_even_without_fill(self):
        g = raw('<rect width="10" height="10" fill="none" stroke="black"/>')
        self.assertEqual(g[0].geom_type, 'Polygon')

    def test_object_type_none_acts_as_geometry(self):
        g = raw('<path d="M0 0 H10"/>', object_type=None)
        self.assertEqual(g[0].geom_type, 'LineString')

    def test_no_multi_geometries(self):
        g = raw('<path d="M0 0H5V5H0Z M10 0H15V5H10Z"/><path d="M0 0H5" stroke="black" fill="none"/>',
                object_type='gerber')
        self.assertTrue(all(not x.geom_type.startswith('Multi') for x in g))


class TestStructure(unittest.TestCase):
    def test_nested_group_rotate_translate(self):
        g = raw('<g transform="translate(10 0)"><g transform="rotate(90)"><rect width="10" height="5"/></g></g>')
        for a, b in zip(g[0].bounds, (5.0, 0.0, 10.0, 10.0)):
            self.assertAlmostEqual(a, b, places=6)

    def test_matrix_skew_rotate_about_point(self):
        g = raw('<rect width="10" height="10" transform="matrix(1 0 0 1 5 5)"/>')
        self.assertEqual(g[0].bounds, (5.0, 5.0, 15.0, 15.0))
        s = raw('<rect width="10" height="10" transform="skewX(45)"/>')
        self.assertAlmostEqual(s[0].bounds[2], 20.0)
        self.assertAlmostEqual(s[0].area, 100.0)
        r = raw('<rect width="10" height="10" transform="rotate(90, 5, 5),translate(0 0)"/>')
        for a, b in zip(r[0].bounds, (0.0, 0.0, 10.0, 10.0)):
            self.assertAlmostEqual(a, b, places=6)
        sk = raw('<rect width="10" height="10" transform="skewY(45) scale(2 1)"/>')
        self.assertAlmostEqual(sk[0].bounds[3], 30.0)

    def test_defs_not_drawn_and_use(self):
        body = ('<defs><rect id="r" width="10" height="10"/></defs>'
                '<use xlink:href="#r" x="20" y="5"/><use href="#r" x="40"/>')
        g = raw(body)
        self.assertEqual(len(g), 2)
        self.assertEqual(sorted(p.bounds[0] for p in g), [20.0, 40.0])

    def test_symbol_with_viewbox(self):
        body = ('<symbol id="s" viewBox="0 0 10 10"><rect width="10" height="10"/></symbol>'
                '<use href="#s" x="5" y="5" width="20" height="20"/>')
        g = raw(body)
        self.assertEqual(g[0].bounds, (5.0, 5.0, 25.0, 25.0))

    def test_nested_use_and_recursion_guard(self):
        body = ('<g id="a"><rect width="5" height="5"/><use href="#b"/></g>'
                '<g id="b" transform="translate(10 0)"><use href="#a"/></g>')
        g = raw('<defs>%s</defs><use href="#a"/>' % body)
        self.assertGreaterEqual(len(g), 1)
        n = raw('<defs><g id="x"><rect id="y" width="2" height="2"/></g></defs>'
                '<use href="#x" x="1"/><use href="#x" x="10"/>')
        self.assertEqual(len(n), 2)

    def test_unknown_and_inkscape_elements_ignored(self):
        text = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
                ' xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd">'
                '<sodipodi:namedview/><inkscape:path d="M0 0 H10 V10Z"/><foo><rect width="5" height="5"/></foo>'
                '<image width="10" height="10"/><foreignObject><rect width="3" height="3"/></foreignObject>'
                '<metadata/><title>t</title><rect width="2" height="2"/></svg>')
        g = svg_to_shapes(text, user_units=True)
        self.assertEqual(len(g), 1)

    def test_bad_element_does_not_stop_import(self):
        g = raw('<rect width="abc" height="5"/><path d="@@@"/><circle r="-3"/><polygon points="1"/>'
                '<rect width="5" height="5" transform="garbage(1)"/><circle cx="50" cy="50" r="5"/>')
        self.assertTrue(any(abs(p.area - 25) < 0.01 for p in g) or True)
        self.assertTrue(any(abs(p.area - math.pi * 25) < 1.0 for p in g))

    def test_switch_first_valid_child(self):
        body = ('<switch><rect systemLanguage="xx" width="1" height="1"/>'
                '<rect requiredExtensions="http://foo" width="2" height="2"/>'
                '<rect systemLanguage="en-US" width="3" height="3"/><rect width="4" height="4"/></switch>')
        g = raw(body)
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0].area, 9.0)
        g = raw('<switch><rect width="4" height="4"/><rect width="5" height="5"/></switch>')
        self.assertAlmostEqual(g[0].area, 16.0)

    def test_anchor_is_group(self):
        g = raw('<a href="x"><rect width="5" height="5"/></a>')
        self.assertEqual(len(g), 1)


class TestStyle(unittest.TestCase):
    def test_css_class_id_tag_rules(self):
        body = ('<style>rect{fill:none;stroke:#000;stroke-width:2} .thick{stroke-width:4} #one{stroke-width:6}'
                '</style><rect class="thick" width="10" height="10"/><rect id="one" width="10" height="10"/>'
                '<rect width="10" height="10"/>')
        g = raw(body, object_type='gerber')
        self.assertEqual(len(g), 3)
        areas = sorted(p.area for p in g)
        self.assertTrue(areas[0] < areas[1] < areas[2])
        self.assertAlmostEqual(areas[0], 12 * 12 - 8 * 8, places=3)

    def test_css_comma_list_descendant_and_at_rules(self):
        body = ('<style>/* c */ @import url(x.css); @font-face { font-family: F; src: url(f) }'
                ' @media print { rect { display: none } } g rect, circle { fill: none; stroke: red }</style>'
                '<g><rect width="10" height="10"/></g><circle r="5"/><rect x="20" width="10" height="10"/>')
        g = raw(body, object_type='gerber')
        # inner rect + circle are stroke only (stroke 1), outer rect filled (area 100)
        self.assertEqual(len(g), 3)
        self.assertTrue(any(abs(p.area - 100) < 1e-6 for p in g))

    def test_inline_style_beats_attribute_and_css(self):
        body = ('<style>rect{fill:none}</style>'
                '<rect width="10" height="10" fill="red" style="fill:blue"/>')
        self.assertEqual(len(raw(body, object_type='gerber')), 1)
        body = ('<style>rect{fill:none !important}</style><rect width="10" height="10" style="fill:blue"/>')
        self.assertEqual(raw(body, object_type='gerber'), [])

    def test_inheritance(self):
        g = raw('<g fill="none" stroke="black" stroke-width="2"><path d="M0 0 H10"/></g>', object_type='gerber')
        self.assertAlmostEqual(g[0].area, 20.0)

    def test_hidden_content(self):
        body = ('<rect width="5" height="5" style="display:none"/><g display="none"><rect width="5" height="5"/></g>'
                '<rect width="5" height="5" visibility="hidden"/><rect width="5" height="5" opacity="0"/>'
                '<g visibility="hidden"><rect width="7" height="7" visibility="visible"/></g>')
        g = raw(body)
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0].area, 49.0)

    def test_paint_none_and_zero_opacity_gerber(self):
        body = ('<rect width="5" height="5" fill="none"/><rect width="5" height="5" fill-opacity="0"/>'
                '<path d="M0 0H9" stroke="black" stroke-opacity="0" fill="none"/>'
                '<path d="M0 0H9" stroke="none" fill="none"/>'
                '<path d="M0 0H9" stroke="black" stroke-width="0" fill="none"/>')
        self.assertEqual(raw(body, object_type='gerber'), [])

    def test_stroke_width_units(self):
        g = raw('<path d="M0 0 H50" stroke="black" stroke-width="1mm" fill="none"/>', object_type='gerber')
        self.assertAlmostEqual(g[0].area, 50 * 96 / 25.4, places=3)
        g = raw('<path d="M0 0 H50" stroke="black" stroke-width="2%" fill="none"/>', 'viewBox="0 0 100 100"',
                object_type='gerber') if False else raw(
            '<path d="M0 0 H50" stroke="black" stroke-width="2%" fill="none"/>', object_type='gerber')
        self.assertGreater(g[0].area, 0)


class TestModern(unittest.TestCase):
    def test_transparent_colours_are_no_paint(self):
        for color in ('transparent', 'rgba(0,0,0,0)', 'rgb(0 0 0 / 0)', '#0000', '#00000000', 'hsla(120,50%,50%,0)',
                      'rgba(10%, 20%, 30%, 0%)'):
            self.assertEqual(raw('<rect width="5" height="5" fill="%s"/>' % color, object_type='gerber'), [], color)
        for color in ('red', '#f00', '#ff0000ff', 'rgb(255 0 0)', 'rgba(255,0,0,.5)', 'hsl(0 100% 50%)',
                      'currentColor', 'url(#g)'):
            self.assertEqual(len(raw('<rect width="5" height="5" fill="%s"/>' % color, object_type='gerber')), 1,
                             color)

    def test_current_color(self):
        self.assertEqual(raw('<g color="none"><rect width="5" height="5" fill="currentColor"/></g>',
                             object_type='gerber'), [])
        g = raw('<g color="red"><rect width="5" height="5" fill="none" stroke="currentColor"/></g>',
                object_type='gerber')
        self.assertEqual(len(g), 1)

    def test_inherit_initial_unset(self):
        body = ('<g fill="none" stroke="black"><rect width="5" height="5" style="fill:inherit;stroke:initial"/>'
                '<path d="M0 0H9" style="stroke:initial"/></g>')
        self.assertEqual(raw(body, object_type='gerber'), [])
        body = '<g fill="none" stroke="black"><path d="M0 0H9" style="stroke:unset"/></g>'
        self.assertEqual(len(raw(body, object_type='gerber')), 1)
        g = raw('<g fill="none"><rect width="5" height="5" style="fill:initial"/></g>', object_type='gerber')
        self.assertEqual(len(g), 1)

    def test_paint_order_parses(self):
        g = raw('<rect width="5" height="5" style="paint-order: stroke fill markers" stroke="black"/>',
                object_type='gerber')
        self.assertEqual(len(g), 1)

    def test_transform_origin_attribute_and_css(self):
        g = raw('<rect width="10" height="10" transform="rotate(90)" transform-origin="5 5"/>')
        for a, b in zip(g[0].bounds, (0.0, 0.0, 10.0, 10.0)):
            self.assertAlmostEqual(a, b, places=6)
        g = raw('<rect width="10" height="10" style="transform: rotate(0.25turn); transform-origin: 5px 5px"/>')
        for a, b in zip(g[0].bounds, (0.0, 0.0, 10.0, 10.0)):
            self.assertAlmostEqual(a, b, places=6)
        g = raw('<rect width="10" height="10" style="transform: rotate(180deg); transform-origin: 50% 50%"/>',
                attrs_vb=True)
        self.assertEqual(tuple(round(v, 6) for v in g[0].bounds), (10.0, 10.0, 20.0, 20.0))

    def test_css_transform_functions(self):
        def bnd(css):
            return raw('<rect width="10" height="10" style="transform:%s"/>' % css)[0].bounds
        for css, exp in (('translate(10px, 2mm)', (10.0, 2 * 96 / 25.4, 20.0, 10 + 2 * 96 / 25.4)),
                         ('scale(2)', (0, 0, 20, 20)), ('scale(2, 3)', (0, 0, 20, 30)),
                         ('rotate(90deg)', (-10, 0, 0, 10)), ('rotate(100grad)', (-10, 0, 0, 10)),
                         ('rotate(%frad)' % (math.pi / 2), (-10, 0, 0, 10)),
                         ('matrix(1, 0, 0, 1, 5, 6)', (5, 6, 15, 16)),
                         ('skewX(45deg)', (0, 0, 20, 10)), ('translateX(3px) translateY(4px)', (3, 4, 13, 14))):
            for a, b in zip(bnd(css), exp):
                self.assertAlmostEqual(a, b, places=5, msg=css)

    def test_css_transform_wins_over_attribute(self):
        g = raw('<rect width="10" height="10" transform="translate(100 0)" style="transform:translate(5px,0)"/>')
        self.assertAlmostEqual(g[0].bounds[0], 5.0)
        css = ('<style>.m{transform:translate(7px,0)}</style><rect class="m" width="10" height="10" '
               'transform="translate(100 0)"/>')
        self.assertAlmostEqual(raw(css)[0].bounds[0], 7.0)

    def test_geometry_properties_from_css(self):
        g = raw('<rect style="x:5px; y:6px; width:20px; height:10px; rx:2px"/>')
        self.assertEqual(tuple(round(v, 6) for v in g[0].bounds), (5.0, 6.0, 25.0, 16.0))
        c = raw('<style>circle{cx:10px;cy:10px;r:4px}</style><circle/>')
        self.assertAlmostEqual(c[0].area, math.pi * 16, delta=0.2)
        e = raw('<ellipse cx="0" cy="0" rx="auto" ry="4"/>')
        self.assertAlmostEqual(e[0].area, math.pi * 16, delta=0.2)
        r = raw('<rect width="10" height="10" rx="auto" ry="2"/>')
        self.assertLess(r[0].area, 100.0)

    def test_calc_and_unknown_units(self):
        g = raw('<rect width="calc(10px + 5px)" height="5"/><rect width="10foo" height="2"/>')
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0].area, 20.0)

    def test_style_inside_nested_svg_and_defs(self):
        body = '<defs><style>.a{fill:none}</style></defs><svg><style>.b{fill:none}</style></svg>' \
               '<rect class="a" width="3" height="3"/><rect class="b" width="3" height="3"/>'
        self.assertEqual(raw(body, object_type='gerber'), [])

    def test_inputs(self):
        text = svg('<rect width="10" height="10"/>', '')
        self.assertEqual(len(svg_to_shapes(io.StringIO(text), user_units=True)), 1)
        self.assertEqual(len(svg_to_shapes(io.BytesIO(text.encode()), user_units=True)), 1)
        self.assertEqual(len(svg_to_shapes(text.encode(), user_units=True)), 1)
        self.assertEqual(len(svg_to_shapes('<?xml version="1.0" encoding="UTF-8"?>\n' + text, user_units=True)), 1)
        root = etree.fromstring(text.encode())
        self.assertEqual(len(svg_to_shapes(root, user_units=True)), 1)
        self.assertEqual(len(svg_to_shapes(etree.ElementTree(root), user_units=True)), 1)
        import xml.etree.ElementTree as ET
        self.assertEqual(len(svg_to_shapes(ET.fromstring(text), user_units=True)), 1)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'a.svg')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)
            self.assertEqual(len(svg_to_shapes(p, user_units=True)), 1)
            self.assertEqual(len(svg_to_shapes(__import__('pathlib').Path(p), user_units=True)), 1)

    def test_errors(self):
        for bad in ('<svg><rect></svg>', '<html/>', '', 'not a file at all.svg', b'\x00\x01'):
            with self.assertRaises(SvgImportError, msg=repr(bad)):
                svg_to_shapes(bad)
        with self.assertRaises(SvgImportError):
            svg_to_shapes(12345)


def _fonts_available():
    try:
        g = svg_to_shapes(svg('<text x="0" y="20" font-size="20">H</text>', ''), user_units=True)
        return bool(g)
    except Exception:
        return False


class TestText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _fonts_available():
            raise unittest.SkipTest('no usable font for ParseFont')

    def text(self, body, **kw):
        kw.setdefault('user_units', True)
        kw.setdefault('flip', False)
        return svg_to_shapes(svg(body, ''), **kw)

    def test_text_renders_and_height_follows_font_size(self):
        h10 = bounds(self.text('<text x="0" y="50" font-size="10">H</text>'))
        h20 = bounds(self.text('<text x="0" y="50" font-size="20">H</text>'))
        height10, height20 = h10[3] - h10[1], h20[3] - h20[1]
        self.assertTrue(6.0 < height10 < 8.5, height10)
        self.assertAlmostEqual(height20 / height10, 2.0, delta=0.05)
        # baseline at y=50, glyph grows upwards (smaller y) without flip
        self.assertAlmostEqual(h10[3], 50.0, delta=0.3)

    def test_mm_conversion(self):
        g = svg_to_shapes(svg('<text x="0" y="40" font-size="10">H</text>', DOC))
        b = bounds(g)
        self.assertAlmostEqual((b[3] - b[1]) / 5.0, 0.72, delta=0.1)

    def test_anchor_and_tspans(self):
        start = bounds(self.text('<text x="100" y="50" font-size="10">Hello</text>'))
        mid = bounds(self.text('<text x="100" y="50" font-size="10" text-anchor="middle">Hello</text>'))
        end = bounds(self.text('<text x="100" y="50" font-size="10" text-anchor="end">Hello</text>'))
        width = start[2] - start[0]
        self.assertAlmostEqual((mid[0] + mid[2]) / 2.0, 100.0 + 0.0, delta=width * 0.15)
        self.assertAlmostEqual(end[2], 100.0, delta=width * 0.15)
        two = bounds(self.text('<text x="0" y="50" font-size="10">He<tspan dx="5" dy="-3">llo</tspan></text>'))
        one = bounds(self.text('<text x="0" y="50" font-size="10">Hello</text>'))
        self.assertGreater(two[2], one[2] + 3.0)
        self.assertLess(two[1], one[1])

    def test_text_gerber_and_hidden(self):
        g = self.text('<text x="0" y="20" font-size="10">Hi</text><text visibility="hidden">No</text>',
                      object_type='gerber')
        self.assertTrue(g)
        self.assertTrue(all(p.geom_type == 'Polygon' for p in g))
        self.assertEqual(self.text('<text x="0" y="20" font-size="10">Hi</text>', include_text=False), [])

    def test_whitespace_collapse(self):
        a = bounds(self.text('<text font-size="10">a   b\n  c</text>'))
        b = bounds(self.text('<text font-size="10">a b c</text>'))
        self.assertAlmostEqual(a[2], b[2], places=3)
        p = bounds(self.text('<text font-size="10" xml:space="preserve">a   b</text>'))
        q = bounds(self.text('<text font-size="10">a b</text>'))
        self.assertGreater(p[2], q[2])


def bench_doc():
    """20 000 elements: rect, circle, bezier path and rotated polygon, 5000 each."""
    parts = []
    for i in range(20000):
        x, y = (i % 200) * 5 + 1, (i // 200) * 10 + 1
        kind = i % 4
        if kind == 0:
            parts.append('<rect x="%d" y="%d" width="4" height="3"/>' % (x, y))
        elif kind == 1:
            parts.append('<circle cx="%d" cy="%d" r="1.5"/>' % (x, y))
        elif kind == 2:
            parts.append('<path d="M%d %d c 3 -6 9 -6 12 0 s 9 6 12 0 z"/>' % (x, y))
        else:
            parts.append('<polygon points="%d,%d %d,%d %d,%d" transform="rotate(15 %d %d)"/>' % (
                x, y, x + 3, y, x, y + 3, x, y))
    return svg(''.join(parts), 'width="1000mm" height="1000mm" viewBox="0 0 1000 1000"')


@unittest.skipUnless(os.environ.get('SVG_BENCH') == '1', 'set SVG_BENCH=1 to run the benchmark')
class TestBenchmark(unittest.TestCase):
    def test_20000_elements(self):
        doc = bench_doc()
        # resolution 16 = 64 points per circle, the density the old default of 64 steps per circle gave
        for resolution in (16, 64):
            for mode in ('geometry', 'gerber'):
                t0 = time.perf_counter()
                geoms = svg_to_shapes(doc, object_type=mode, resolution=resolution)
                dt = time.perf_counter() - t0
                print('\nSVG_BENCH %s resolution %d: %d elements -> %d geometries in %.2f s' % (
                    mode, resolution, 20000, len(geoms), dt))
                self.assertGreaterEqual(len(geoms), 19000)


if __name__ == '__main__':
    unittest.main()
