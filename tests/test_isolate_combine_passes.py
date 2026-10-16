"""GerberObject.isolate(combine=True) must keep every pass.

The combine branch assigned geo_obj.solid_geometry inside the loop over the passes, so only the last pass survived:
-passes 2 produced only the outer ring, -passes 3 only the outermost one. The non-combine branch (one object per pass)
was correct. The tests use the headless fixtures of test_unify_characterization.
"""

from unittest.mock import Mock

import pytest
from shapely.ops import unary_union

from appObjects.GeometryObject import GeometryObject
from appObjects.GerberObject import GerberObject

from test_unify_characterization import _headless_qt, app, make_gerber  # noqa: F401  (fixtures)

DIA = 0.2
OVERLAP = 10  # percent


def run_isolate(app, gerber, **kwargs):
    """Calls isolate() and returns {object name: Geometry object built by the init callback}."""
    created = {}

    def new_object(kind, name, initialize, plot=True, **kw):
        assert kind == 'geometry'
        obj = GeometryObject(name, app)
        assert initialize(obj, app) != 'fail'
        created[name] = obj
        return 'ok'

    app.app_obj.new_object = Mock(side_effect=new_object)
    gerber.isolate(dia=DIA, overlap=OVERLAP, iso_type=2, plot=False, **kwargs)
    return created


def wkb_set(geometries):
    return sorted(g.wkb_hex for g in geometries if not g.is_empty)


def expected_offsets(passes):
    """Offset of the centre line of every pass from the copper, as isolate() computes it."""
    return [DIA * ((2 * n + 1) / 2.0) - n * (OVERLAP / 100.0) * DIA for n in range(passes)]


@pytest.mark.parametrize('passes', [1, 2, 3])
def test_combined_result_is_the_union_of_the_separate_passes(app, passes):
    gerber = make_gerber(app, name='g')
    combined = run_isolate(app, gerber, passes=passes, combine=True, outname='combined')
    separate = run_isolate(app, gerber, passes=passes, combine=False)

    combined_geo = combined['combined'].solid_geometry
    separate_geo = [g for obj in separate.values() for g in obj.solid_geometry]

    assert len(separate) == passes
    assert wkb_set(combined_geo) == wkb_set(separate_geo)


def test_every_pass_offset_is_present_in_the_combined_result(app):
    gerber = make_gerber(app, name='g')
    passes = 3
    combined = run_isolate(app, gerber, passes=passes, combine=True, outname='combined')
    copper = unary_union([g for g in gerber.solid_geometry])
    ring_distances = [copper.distance(g.exterior if hasattr(g, 'exterior') else g)
                      for g in combined['combined'].solid_geometry]

    for offset in expected_offsets(passes):
        assert any(abs(d - offset) < 1e-3 for d in ring_distances), \
            'no toolpath at %.3f mm from the copper in %r' % (offset, sorted(set(round(d, 3) for d in ring_distances)))


def test_tool_data_of_the_combined_object_holds_all_passes(app):
    gerber = make_gerber(app, name='g')
    combined = run_isolate(app, gerber, passes=2, combine=True, outname='combined')['combined']
    assert combined.tools[1]['solid_geometry'] == combined.solid_geometry
    assert len(combined.solid_geometry) > 0
