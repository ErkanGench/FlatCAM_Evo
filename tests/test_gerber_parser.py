#!/usr/bin/env python
"""
Automated tests for Gerber parser parse_lines() method.

REQUIRED before any refactoring of the Gerber parser state management.
These tests validate the scattered variables approach.
(ParserState dataclass approach was abandoned - see docs/plans/)

Run: python tests/test_gerber_parser.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appParsers.ParseGerber import Gerber
from camlib import ApertureMacro, flatten_shapely_geometry
from unittest import mock

import shapely
from shapely import GeometryCollection, MultiPolygon, Polygon


class MockLog:
    """Mock logger for testing."""
    def debug(self, msg):
        pass
    
    def warning(self, msg):
        pass
    
    def error(self, msg):
        pass
    
    def info(self, msg):
        pass


class MockInform:
    """Mock inform emitter for testing."""
    def emit(self, msg):
        pass


class MockApp:
    """Mock application object for Gerber parser testing."""
    def __init__(self):
        self.options = {
            'gerber_def_units': 'MM',
            'gerber_def_zeros': 'L',
            'gerber_circle_steps': 64,
            'gerber_simp_tolerance': 0.001,
            'gerber_simplification': True,
            'gerber_buffering': True,
            'gerber_extra_buffering': 0.0,
            'gerber_clean_apertures': True,
            'gerber_use_buffer_for_union': True,
            'global_tolerance': 0.01,
        }
        self.decimals = 4
        self.abort_flag = False
        self.log = MockLog()
        self.inform = MockInform()
        self.app_units = 'MM'
        
        class MockPlotCanvas:
            class new_shape_collection:
                def __init__(self, layers=1):
                    pass
            def __init__(self):
                pass
        self.plotcanvas = MockPlotCanvas()
        
        class MockProcContainer:
            def update_view_text(self, text):
                pass
        self.proc_container = MockProcContainer()


def get_gerber_parser():
    """Create a Gerber parser with mock app for testing."""
    app = MockApp()
    return Gerber(app)


class TestGerberParserBasic:
    """Basic Gerber parser tests."""
    
    def test_simple_line_d01(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G01 X100Y100D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] Simple line D01 test passed")
    
    def test_flash_d03(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "X100Y100D03*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] Flash D03 test passed")
    
    def test_region_g36_g37(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G36*", "X100Y0D01*", "X100Y100D01*", "X0Y100D01*", "X0Y0D01*", "G37*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] Region G36-G37 test passed")
    
    def test_d02_new_path(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G01 X100Y0D01*", "G01 X50Y50D02*", "G01 X150Y150D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] D02 new path test passed")
    
    def test_all_aperture_types(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "%ADD11R,10X20*%", "D10*", "G01 X0Y0D02*", "G01 X100Y0D01*", "D11*", "G01 X0Y50D02*", "G01 X100Y50D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] All aperture types test passed")


class TestGerberParserEdgeCases:
    """Edge case tests for the Gerber parser."""
    
    def test_d02_before_g37(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G36*", "X100Y0D01*", "X100Y100D01*", "G01 X0Y100D02*", "G37*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] D02 before G37 edge case test passed")
    
    def test_empty_path_no_crash(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G01 X100Y100D02*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == "fail"
        print("[PASS] Empty path no crash test passed")
    
    def test_comments_ignored(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G04 This is a comment*", "G01 X0Y0D02*", "G04 Another comment*", "G01 X100Y100D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] Comments ignored test passed")
    
    def test_polarity_change_with_pending_path(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX23Y23*%", "%ADD10C,10*%", "D10*", "G01 X0Y0D02*", "G01 X1000Y0D01*", "G01 X1000Y1000D01*", "%LPC*%", "G01 X2000Y0D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert result is None or result == ""
        print("[PASS] Polarity change with pending path test passed")


    def test_aperture_macro_without_modifiers(self):
        gbr = get_gerber_parser()
        macro = ApertureMacro('NO_MODIFIERS')
        macro.raw = '1,1,1,0,0*'
        gbr.aperture_macros['NO_MODIFIERS'] = macro

        gbr.aperture_parse('10', 'NO_MODIFIERS', None)

        assert gbr.tools[10]['modifiers'] == []
        assert not macro.make_geometry(gbr.tools[10]['modifiers']).is_empty

    def test_disjoint_aperture_macro_primitives_are_not_shifted(self):
        macro = ApertureMacro('DISJOINT')
        macro.raw = '1,1,1,0,0*1,1,1,10,0*'

        result = macro.make_geometry([])

        assert isinstance(result, MultiPolygon)
        assert result.bounds == (-0.5, -0.5, 10.5, 0.5)

    def test_flatten_shapely_geometry_is_recursive_and_ordered(self):
        poly1 = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        poly2 = Polygon([(2, 0), (3, 0), (3, 1), (2, 1)])
        poly3 = Polygon([(4, 0), (5, 0), (5, 1), (4, 1)])
        multi = MultiPolygon([poly2, poly3])

        result = flatten_shapely_geometry([[[poly1]], [multi]])

        assert [geo.bounds for geo in result] == [
            poly1.bounds, poly2.bounds, poly3.bounds
        ]


class TestGerberParserUnits:
    """Test unit handling."""
    
    def test_inches_units(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOIN*%", "%ADD10C,10*%", "D10*", "G01X0Y0D02*", "G01X100Y100D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert gbr.units == 'IN'
        print("[PASS] Inches units test passed")
    
    def test_metric_units(self):
        gbr = get_gerber_parser()
        lines = ["%FSLAX24Y24*%", "%MOMM*%", "%ADD10C,10*%", "D10*", "G01X0Y0D02*", "G01X10000Y10000D01*", "M02*"]
        result = gbr.parse_lines(lines)
        assert gbr.units == 'MM'
        print("[PASS] Metric units test passed")


class TestGerberPolarityLayers:
    """The polarity layers (%LPD*% / %LPC*%) are composed 1 time at the end of the file.
    The reference is the old sequential fold (Gerber._fold_layers)."""

    HEADER = ["%FSLAX24Y24*%", "%MOMM*%", "%ADD10C,0.5*%", "%ADD11R,2X2*%", "%ADD12C,3*%",
              "%ADD13R,5X0.00000001*%", "G01*", "D10*"]

    @staticmethod
    def region(x0, y0, x1, y1):
        """A rectangular region, coordinates in 1e-4 mm."""
        return ["G36*", "X%dY%dD02*" % (x0, y0), "X%dY%dD01*" % (x1, y0), "X%dY%dD01*" % (x1, y1),
                "X%dY%dD01*" % (x0, y1), "X%dY%dD01*" % (x0, y0), "G37*"]

    @staticmethod
    def parser(**opts):
        app = MockApp()
        app.options.update({
            'gerber_buffering': 'full', 'gerber_use_buffer_for_union': True, 'gerber_circle_steps': 16,
            'gerber_simplification': False, 'gerber_extra_buffering': False,
        })
        app.options.update(opts)
        return Gerber(app)

    def parse(self, lines, legacy=False, **opts):
        gbr = self.parser(**opts)
        if legacy:
            with mock.patch.object(Gerber, '_compose_layers', lambda s, layers: s._fold_layers(layers)):
                ret = gbr.parse_lines(list(lines))
        else:
            ret = gbr.parse_lines(list(lines))
        return gbr, ret

    @staticmethod
    def parts(geo):
        if isinstance(geo, (list, tuple)):
            return list(geo)
        if hasattr(geo, 'geoms'):
            return list(geo.geoms)
        return [geo]

    def holes(self, geo):
        return sum(len(p.interiors) for p in self.parts(geo) if isinstance(p, Polygon))

    def union(self, geo):
        return shapely.unary_union([shapely.make_valid(p) for p in self.parts(geo)])

    def check(self, lines, **opts):
        """Parse with the composition and with the old fold; the results must be equal."""
        new, ret_new = self.parse(lines, **opts)
        old, ret_old = self.parse(lines, legacy=True, **opts)
        assert ret_new == ret_old, "return %r != %r" % (ret_new, ret_old)
        assert len(self.parts(new.solid_geometry)) == len(self.parts(old.solid_geometry)), "number of polygons"
        assert self.holes(new.solid_geometry) == self.holes(old.solid_geometry), "number of holes"
        diff = self.union(new.solid_geometry).symmetric_difference(self.union(old.solid_geometry)).area
        assert diff < 1e-9, "symmetric difference %g" % diff
        return new, old, ret_new

    def test_ends_in_lpc(self):
        lines = self.HEADER + self.region(0, 0, 100000, 100000) + ["%LPC*%"] + self.region(20000, 20000, 40000, 40000) + \
            ["M02*"]
        new, old, ret = self.check(lines)
        assert self.holes(new.solid_geometry) == 1
        print("[PASS] Polarity layers: ends in LPC")

    def test_ends_in_lpd(self):
        lines = self.HEADER + self.region(0, 0, 100000, 100000) + ["%LPC*%"] + self.region(20000, 20000, 60000, 60000) + \
            ["%LPD*%"] + self.region(30000, 30000, 40000, 40000) + ["M02*"]
        new, old, ret = self.check(lines)
        assert self.holes(new.solid_geometry) == 1
        assert len(self.parts(new.solid_geometry)) == 2
        print("[PASS] Polarity layers: ends in LPD")

    def test_repeated_lpd(self):
        lines = self.HEADER + ["%LPD*%"] + self.region(0, 0, 50000, 50000) + ["%LPD*%"] + \
            self.region(30000, 30000, 80000, 80000) + ["%LPD*%", "%LPC*%"] + self.region(40000, 40000, 45000, 45000) + \
            ["%LPD*%"] + self.region(90000, 0, 100000, 10000) + ["M02*"]
        self.check(lines)
        print("[PASS] Polarity layers: repeated LPD")


    def test_only_full_clear(self):
        lines = self.HEADER + self.region(10000, 10000, 20000, 20000) + ["%LPC*%"] + \
            self.region(0, 0, 100000, 100000) + ["%LPD*%", "M02*"]
        new, old, ret = self.check(lines)
        assert self.union(new.solid_geometry).area == 0
        print("[PASS] Polarity layers: only a full clear (return %r)" % (ret,))

    def test_leading_clear_layer(self):
        lines = self.HEADER + ["%LPC*%"] + self.region(0, 0, 30000, 30000) + ["%LPD*%"] + \
            self.region(20000, 20000, 80000, 80000) + ["M02*"]
        new, old, ret = self.check(lines)
        assert abs(self.union(new.solid_geometry).area - 6 * 6) < 1e-6
        print("[PASS] Polarity layers: leading clear layer")


    def test_dark_restores_cleared_copper(self):
        lines = self.HEADER + self.region(0, 0, 100000, 100000) + ["%LPC*%"] + \
            self.region(20000, 20000, 80000, 80000) + ["%LPD*%"] + self.region(40000, 40000, 60000, 60000) + \
            ["%LPC*%"] + self.region(45000, 45000, 55000, 55000) + ["%LPD*%", "D11*", "X50000Y50000D03*", "M02*"]
        new, old, ret = self.check(lines)
        print("[PASS] Polarity layers: a dark layer restores cleared copper")


def test_load_real_gerber_files():
    """Test loading actual Gerber files from test_files directory."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    files_dir = os.path.join(test_dir, 'test_files')
    
    test_files = ['simple_line.gbr', 'region_test.gbr', 'flash_test.gbr']
    
    for filename in test_files:
        filepath = os.path.join(files_dir, filename)
        if os.path.exists(filepath):
            gbr = get_gerber_parser()
            result = gbr.parse_file(filepath)
            assert result is None or result != 'fail', f"{filename} failed to parse"
            print(f"[PASS] Loaded {filename}")
        else:
            print(f"[SKIP] {filename} not found")


def run_all_tests():
    """Run all tests and report results."""
    import traceback
    
    test_classes = [TestGerberParserBasic, TestGerberParserEdgeCases, TestGerberParserUnits, TestGerberPolarityLayers]
    
    passed = 0
    failed = 0
    errors = []
    
    for test_class in test_classes:
        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                test_name = f"{test_class.__name__}.{method_name}"
                try:
                    method = getattr(instance, method_name)
                    method()
                    passed += 1
                except AssertionError as e:
                    failed += 1
                    errors.append((test_name, str(e)))
                    print(f"[FAIL] {test_name}: {e}")
                except Exception as e:
                    failed += 1
                    errors.append((test_name, traceback.format_exc()))
                    print(f"[ERROR] {test_name}: {e}")
    
    print("\n--- Integration Tests ---")
    try:
        test_load_real_gerber_files()
        passed += 1
    except AssertionError as e:
        failed += 1
        errors.append(("test_load_real_gerber_files", str(e)))
        print(f"[FAIL] test_load_real_gerber_files: {e}")
    except Exception as e:
        failed += 1
        errors.append(("test_load_real_gerber_files", traceback.format_exc()))
        print(f"[ERROR] test_load_real_gerber_files: {e}")
    
    print(f"\n{'='*60}")
    print(f"Test Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    
    if errors:
        print("\nFailures:")
        for test_name, error in errors:
            print(f"  - {test_name}: {error}")
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
