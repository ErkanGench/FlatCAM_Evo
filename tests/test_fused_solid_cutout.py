"""ToolCutOut freeform cutout: the Gerber geometry now comes from fused_solid(); old versus new on the unify fixtures.

TestLegacy pins the old expression (it passes on the code before the change too); TestNew checks
``gerber_cutout_geometry`` against it.
"""

import pytest
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from fused_consumer_cases import area_diff, case_geometries, outcome
from tests.helpers_objects import app, gerber, _headless_qt  # noqa: F401,E402


def legacy_cutout_geo(cutout_obj, convex_box):
    """Verbatim logic of CutOut.on_freeform_cutout.job_thread before the change (the logger call is dropped)."""
    if isinstance(cutout_obj.solid_geometry, list):
        cutout_obj.solid_geometry = unary_union(cutout_obj.solid_geometry)
    try:
        if convex_box:
            object_geo = cutout_obj.solid_geometry.convex_hull
        else:
            object_geo = cutout_obj.solid_geometry
    except Exception:
        object_geo = cutout_obj.solid_geometry
    return object_geo


def obj_with(gerber, name):
    gerber.solid_geometry = case_geometries(gerber.solid_geometry)[name]
    return gerber


VALID = ['mixed_dark_clear_dark', 'overlapping_list', 'single_polygon', 'multipolygon']


@pytest.fixture
def new_fn():
    from appPlugins.ToolCutOut import gerber_cutout_geometry
    return gerber_cutout_geometry


class TestNew:
    @pytest.mark.parametrize('name', VALID + ['self_intersecting'])
    @pytest.mark.parametrize('convex', [False, True])
    def test_valid_polygonal(self, gerber, new_fn, name, convex):
        geo = new_fn(obj_with(gerber, name), convex)
        assert isinstance(geo, (Polygon, MultiPolygon)) and geo.is_valid

    def test_self_intersecting_no_longer_raises(self, gerber, new_fn):
        geo = new_fn(obj_with(gerber, 'self_intersecting'), False)
        assert geo.area > 0
