"""Tests of the Stage 2 read accessors (``appParsers/feature_access.py``) on the unification fixtures.

Everything is headless. The helpers come from ``tests.helpers_objects``.
"""

import pytest
import shapely
from shapely.errors import GEOSException
from shapely.geometry import (
    GeometryCollection, LineString, MultiPolygon, Point, Polygon, box,
)
from shapely.ops import unary_union

from appObjects.ExcellonObject import ExcellonObject
from appObjects.GerberObject import GerberObject
from appParsers.feature_access import (
    FeatureRecord, fused_solid, is_empty, iter_features, iter_items, normalize_polygonal,
)

from tests.helpers_objects import (  # noqa: F401,E402
    app, assert_poly_equiv, excellon, gerber, _headless_qt, make_excellon, make_same_diameter_excellon,
    sym_diff_area,
)


def feats(obj):
    return list(iter_features(obj))


def of_item(obj, key):
    return [f for f in iter_features(obj) if f.item_key == key]


# ---------------------------------------------------------------------------------------------------------------
# Gerber
# ---------------------------------------------------------------------------------------------------------------

class TestGerberFeatures:
    def test_order_is_aperture_order_then_feature_order(self, gerber):
        keys_in_tools = list(gerber.tools)
        seen = []
        for f in iter_features(gerber):
            if not seen or seen[-1] != f.item_key:
                seen.append(f.item_key)
        assert seen == [k for k in keys_in_tools if gerber.tools[k]['geometry']]
        for key, tool in gerber.tools.items():
            got = of_item(gerber, key)
            assert [f.feature_index for f in got] == list(range(len(tool['geometry'])))
            for f, rec in zip(got, tool['geometry']):
                assert f.solid is (rec['solid'] if 'solid' in rec else rec['clear'])
                assert f.follow is rec['follow']

    def test_aperture_10_flash_track_clear_track(self, gerber):
        got = of_item(gerber, 10)
        assert [(f.kind, f.polarity) for f in got] == [('flash', 'dark'), ('route', 'dark'), ('route', 'clear')]
        assert isinstance(got[0].follow, Point) and isinstance(got[1].follow, LineString)
        # the clear feature carries its 'clear' geometry as solid
        assert got[2].solid is gerber.tools[10]['geometry'][2]['clear']
        assert 'solid' not in gerber.tools[10]['geometry'][2]

    @pytest.mark.parametrize('ap', [11, 12, 13, 14, 15, 17])
    def test_flash_apertures(self, gerber, ap):
        got = of_item(gerber, ap)
        assert len(got) == 1
        assert (got[0].kind, got[0].polarity) == ('flash', 'dark')

    def test_region(self, gerber):
        got = of_item(gerber, 0)
        assert [(f.kind, f.polarity) for f in got] == [('region', 'dark')]
        assert isinstance(got[0].solid, Polygon) and got[0].solid.area == pytest.approx(80.0)

    def test_record_with_both_keys_gives_two_records_same_index(self, gerber):
        rec = gerber.tools[11]['geometry'][0]
        rec['clear'] = box(0, 0, 1, 1)
        got = of_item(gerber, 11)
        assert [(f.feature_index, f.polarity) for f in got] == [(0, 'dark'), (0, 'clear')]
        assert got[1].solid is rec['clear']

    def test_record_without_solid_or_clear(self, gerber):
        rec = gerber.tools[11]['geometry'][0]
        del rec['solid']
        got = of_item(gerber, 11)
        assert len(got) == 1 and got[0].polarity == 'dark' and got[0].solid.is_empty

# ---------------------------------------------------------------------------------------------------------------
# Excellon
# ---------------------------------------------------------------------------------------------------------------

class TestExcellonFeatures:
    def test_solids_equal_tool_solid_geometry(self, excellon):
        for t, tool in excellon.tools.items():
            got = [f.solid for f in of_item(excellon, t)]
            assert len(got) == len(tool['solid_geometry']) == 3
            for mine, parsed in zip(got, tool['solid_geometry']):
                assert mine.equals_exact(parsed, 0.0), 'solid of tool %s differs from create_geometry' % t

    def test_solid_uses_the_circle_steps(self, excellon):
        excellon.app.options.update({'excellon_circle_steps_mode': 'fixed', 'excellon_circle_steps': 16})
        a = of_item(excellon, 1)[0].solid
        b = Point(5.0, 5.0).buffer(0.4, 4)
        assert a.equals_exact(b, 0.0) and len(a.exterior.coords) == 17

    def test_same_diameter_tools_stay_separate(self, app):
        obj = make_same_diameter_excellon(app)
        assert list(iter_items(obj)) == [(1, 1.0), (2, 1.0)]
        assert [f.item_key for f in iter_features(obj)] == [1, 1, 2, 2]


# ---------------------------------------------------------------------------------------------------------------
# normalize_polygonal
# ---------------------------------------------------------------------------------------------------------------

def bowtie():
    return Polygon([(0, 0), (4, 4), (4, 0), (0, 4)])


class TestNormalizePolygonal:
    def test_bowtie_with_overlapping_rectangle(self):
        bad = bowtie()
        rect = box(1, -1, 3, 5)
        assert not bad.is_valid
        # meaningful only if the plain union is broken: it raises or returns an invalid result
        try:
            plain = unary_union([bad, rect])
            plain_broken = (not plain.is_valid)
        except GEOSException:
            plain_broken = True
        assert plain_broken, 'plain unary_union handled the bow-tie, the test would prove nothing'

        result = normalize_polygonal([bad, rect])
        assert isinstance(result, (Polygon, MultiPolygon)) and result.is_valid and not result.is_empty
        expected = unary_union([shapely.make_valid(bad), rect])
        assert result.symmetric_difference(expected).area < 1e-9
        assert result.contains(Point(2, 4.5))   # the rectangle
        assert result.contains(Point(0.5, 2))  # a lobe of the bow-tie

    def test_only_lines_gives_empty_polygon(self):
        result = normalize_polygonal([LineString([(0, 0), (1, 1)]), Point(1, 1)])
        assert isinstance(result, Polygon) and result.is_empty

    def test_failure_is_raised(self, monkeypatch):
        import appParsers.feature_access as fa

        def boom(_):
            raise GEOSException('boom')
        monkeypatch.setattr(fa, 'unary_union', boom)
        with pytest.raises(GEOSException):
            normalize_polygonal([box(0, 0, 1, 1)])


# ---------------------------------------------------------------------------------------------------------------
# fused_solid, is_empty
# ---------------------------------------------------------------------------------------------------------------

class TestFusedSolid:
    def test_dark_clear_dark_equals_composed_geometry(self, gerber):
        fused = fused_solid(gerber)
        assert isinstance(fused, (Polygon, MultiPolygon)) and fused.is_valid
        composed = unary_union([shapely.make_valid(g) for g in gerber.solid_geometry])
        assert fused.symmetric_difference(composed).area < 1e-6
        assert_poly_equiv(fused, gerber.solid_geometry, msg='fused vs parser')
        # the clear gap is applied: a union of the dark records would cover it
        assert not fused.contains(Point(15, 33))
        assert fused.contains(Point(15, 35))     # the dark flash after the clear
        assert fused.contains(Point(8, 35))      # the track away from the gap
        dark_union = unary_union([f.solid for f in iter_features(gerber) if f.polarity == 'dark'])
        assert dark_union.contains(Point(15, 33))

    def test_excellon(self, excellon):
        fused = fused_solid(excellon)
        assert isinstance(fused, (Polygon, MultiPolygon)) and fused.is_valid
        parts = [g for t in excellon.tools.values() for g in t['solid_geometry']]
        assert fused.symmetric_difference(unary_union(parts)).area < 1e-9
        assert fused.contains(Point(5, 5)) and not fused.contains(Point(1, 1))

    def test_invalid_part_in_composed_geometry(self, gerber):
        gerber.solid_geometry = [bowtie(), box(1, -1, 3, 5)]
        fused = fused_solid(gerber)
        assert fused.is_valid and fused.contains(Point(2, 4.5))


class TestIsEmpty:
    def test_new_objects_are_empty(self, app):
        grb = GerberObject('g', app)
        exc = ExcellonObject('e', app)
        assert grb.tools == {} and is_empty(grb) is True
        assert is_empty(exc) is True

    def test_gerber_with_empty_solid_geometry_list(self, gerber):
        gerber.tools = {}
        gerber.solid_geometry = []
        assert is_empty(gerber) is True

    def test_gerber_with_only_empty_geometry(self, gerber):
        gerber.tools = {}
        gerber.solid_geometry = [Polygon(), GeometryCollection()]
        assert is_empty(gerber) is True

    def test_excellon_tool_without_features(self, excellon):
        for tool in excellon.tools.values():
            tool['drills'] = []
            tool['slots'] = []
        assert is_empty(excellon) is True
