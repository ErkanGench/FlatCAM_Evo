"""Tests for appCommon/imagetrace.py: the tracing mode of the Image import plugin (vtracer)."""

import os
import re
import subprocess
import sys
import tempfile
import unittest

from lxml import etree as ET
from PIL import Image, ImageDraw
from shapely import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from appCommon import imagetrace  # noqa: E402
from appCommon.imagetrace import trace, PRESETS, PRESET_NAMES, CURVE_MODES  # noqa: E402
from appParsers.ParseSVG import getsvggeo  # noqa: E402


def svg_to_shape(svg_text):
    """The geometry that the plugin imports (in pixels, not flipped)."""
    geos = getsvggeo(ET.fromstring(svg_text), 'gerber', units='MM', res=16, factor=1.0)
    return unary_union([g for g in geos if g is not None and not g.is_empty])


class ImageTraceTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def save(self, img, name='img.png'):
        path = os.path.join(self.tmp.name, name)
        img.save(path)
        return path

    def test_square_outline_is_exact(self):
        img = Image.new('RGB', (64, 64), 'white')
        ImageDraw.Draw(img).rectangle((20, 20, 43, 43), fill='black')
        shape = svg_to_shape(trace(self.save(img)))
        self.assertEqual(shape.bounds, (20.0, 20.0, 44.0, 44.0))
        self.assertAlmostEqual(shape.area, 24 * 24)

    def test_enclosed_white_area_stays_a_hole(self):
        # imagetracer.js (the old svgtrace engine) filled white areas enclosed by traces: a short on a PCB
        img = Image.new('RGB', (100, 100), 'white')
        ImageDraw.Draw(img).rectangle((10, 10, 89, 89), outline='black', width=6)
        shape = svg_to_shape(trace(self.save(img)))
        self.assertEqual(len(shape.interiors), 1)
        self.assertAlmostEqual(shape.area, 80 * 80 - 68 * 68)

    def test_close_traces_are_not_bridged(self):
        img = Image.new('RGB', (120, 60), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 20, 55, 39), fill='black')
        draw.rectangle((59, 20, 110, 39), fill='black')
        shape = svg_to_shape(trace(self.save(img)))
        self.assertEqual(shape.geom_type, 'MultiPolygon')
        self.assertEqual(len(shape.geoms), 2)

    def test_red_artwork_is_traced_in_bw(self):
        # the binary mode of vtracer looks only at the red channel: without the grayscale step this is empty
        img = Image.new('RGB', (64, 64), 'white')
        ImageDraw.Draw(img).rectangle((20, 20, 43, 43), fill=(220, 20, 60))
        self.assertAlmostEqual(svg_to_shape(trace(self.save(img))).area, 24 * 24)

    def test_transparent_background_is_white(self):
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle((20, 20, 43, 43), fill=(0, 0, 0, 255))
        self.assertAlmostEqual(svg_to_shape(trace(self.save(img))).area, 24 * 24)

    def test_threshold(self):
        img = Image.new('RGB', (64, 64), 'white')
        ImageDraw.Draw(img).rectangle((20, 20, 43, 43), fill=(150, 150, 150))
        path = self.save(img)
        self.assertEqual(trace(path, threshold=128).count('<path'), 0)
        self.assertAlmostEqual(svg_to_shape(trace(path, threshold=200)).area, 24 * 24)

    def test_color_regions_keep_their_colors(self):
        img = Image.new('RGB', (64, 64), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle((4, 4, 27, 27), fill=(255, 0, 0))
        draw.rectangle((36, 36, 59, 59), fill=(0, 0, 255))
        svg = trace(self.save(img), black_white=False)
        fills = {f.upper() for f in re.findall(r'fill="(#[0-9A-Fa-f]{6})"', svg)}
        self.assertTrue({'#FF0000', '#0000FF'} <= fills, fills)

    def test_filter_speckle(self):
        img = Image.new('RGB', (64, 64), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 39, 39), fill='black')
        draw.rectangle((50, 50, 51, 51), fill='black')
        path = self.save(img)
        self.assertEqual(trace(path, options={'filter_speckle': 0}).count('<path'), 2)
        self.assertEqual(trace(path, options={'filter_speckle': 4}).count('<path'), 1)

    def test_presets_and_curve_modes(self):
        img = Image.new('RGB', (64, 64), 'white')
        ImageDraw.Draw(img).ellipse((8, 8, 55, 55), fill='black')
        path = self.save(img)
        self.assertEqual(PRESET_NAMES, ['default', 'detailed', 'smooth', 'photo'])
        for name in PRESET_NAMES:
            self.assertIn(PRESETS[name]['mode'], CURVE_MODES)
            for bw in (True, False):
                self.assertIn('<path', trace(path, black_white=bw, options=PRESETS[name]), (name, bw))
        # polygon mode makes straight segments only, spline mode makes curves
        self.assertNotIn('C', re.findall(r' d="([^"]*)"', trace(path, options={'mode': 'polygon'}))[0])
        self.assertIn('C', re.findall(r' d="([^"]*)"', trace(path, options={'mode': 'spline'}))[0])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            trace(os.path.join(self.tmp.name, 'missing.png'))

    def test_missing_package_message(self):
        saved = imagetrace.vtracer
        imagetrace.vtracer = None
        imagetrace._VTRACER_IMPORT_ERROR = ImportError('test')
        try:
            with self.assertRaisesRegex(ImportError, "pip install vtracer"):
                trace(os.path.join(self.tmp.name, 'any.png'))
        finally:
            imagetrace.vtracer = saved

    def test_module_imports_without_vtracer(self):
        # the plugin must load (Raster mode works) when vtracer is not installed
        code = ("import sys; sys.modules['vtracer'] = None; sys.path.insert(0, %r); "
                "from appCommon import imagetrace; assert imagetrace.vtracer is None; print('ok')" % ROOT)
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), 'ok', out.stderr)

    def test_old_engine_is_gone(self):
        with open(os.path.join(ROOT, 'appPlugins', 'ToolImage.py'), encoding='utf-8') as f:
            src = f.read()
        for name in ('svgtrace', 'pyppeteer', 'check_chromium'):
            self.assertNotIn(name, src)
        for req in ('requirements.txt', 'environment.yml'):
            with open(os.path.join(ROOT, req), encoding='utf-8') as f:
                text = f.read()
            self.assertNotIn('svgtrace', text)
            self.assertNotIn('pyppeteer', text)
            self.assertIn('vtracer', text)


if __name__ == '__main__':
    unittest.main()
