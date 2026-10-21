"""
Exclusion areas: the travel moves (rapids) go over or around an area grown by the tool radius and a little more
(0.1 mm). The planner looked only at the crossings of the travel line with the outline of the grown area:
- a travel with 1 end point inside the grown area crosses the outline once (a Point) and was taken for a touch,
- a travel with both end points inside the grown area does not meet the outline at all,
so both went straight through the area at the travel Z. A travel that really crossed an area raised a TypeError
(Shapely 2: a MultiPoint is not iterable). The drill point checks used only the tool radius, so a drill in the
0.1 mm margin was accepted and its travels started or ended inside the grown area.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from appCommon.Common import ExclusionAreas
from appPlugins.ToolDrilling import ToolDrilling
from camlib import CNCjob
from test_unify_regressions_0b import make_app, make_excellon

TOOLDIA = 1.0
# the area grown by the tool radius and 0.1 mm: x 2.4 .. 6.6, y -1.6 .. 1.6
AREA = box(3, -1, 6, 1)
OVER_Z = 5.0


def exclusion_areas(*areas, strategy='over', units='MM'):
    exc = ExclusionAreas(SimpleNamespace(app_units=units, log=Mock()))
    exc.exclusion_areas_storage = [dict(obj_type='excellon', shape=shape, strategy=strategy, overz=OVER_Z)
                                   for shape in areas]
    return exc


def grown(shape, tooldia=TOOLDIA, margin=0.1):
    return shape.buffer(tooldia / 2.0 + margin, join_style='mitre')


def rapids_at_travel_z(start, travels):
    """
    The rapid segments made at the travel Z, as the G-code generators make them from the travel list: move to the
    point, then rise to the Over Z of the item, or go back down to the travel Z when the item has no Over Z.
    """
    segments = []
    pos, lifted = start, False
    for z, xy in travels:
        if not lifted and tuple(pos) != tuple(xy):
            segments.append(LineString([pos, xy]))
        pos, lifted = xy, z is not None
    assert not lifted, 'the travel ends at the Over Z'
    return segments


def assert_avoided(start, end, travels, *areas):
    assert tuple(travels[-1][1]) == tuple(end)
    for segment in rapids_at_travel_z(start, travels):
        for area in areas:
            # a segment on the outline of the grown area is allowed, a segment inside it is not
            inside = grown(area).buffer(-1e-6, join_style='mitre')
            assert not segment.intersects(inside), (segment.wkt, travels)


@pytest.mark.parametrize('start, end', [((2.45, 0), (10, 0)), ((10, 0), (2.45, 0))])
def test_one_end_point_in_the_margin_goes_over(start, end):
    travels = exclusion_areas(AREA).travel_coordinates(start, end, TOOLDIA)

    assert_avoided(start, end, travels, AREA)
    assert len(travels) > 1
    if start == (2.45, 0):
        # the start is inside the grown area: rise before any XY move
        assert travels[0] == [OVER_Z, pytest.approx((2.45, 0))]
        assert travels[1] == [None, pytest.approx((6.6, 0))]


def test_both_end_points_in_the_margin_go_over():
    travels = exclusion_areas(AREA).travel_coordinates((2.45, 0), (6.55, 0), TOOLDIA)

    assert_avoided((2.45, 0), (6.55, 0), travels, AREA)
    assert travels[0] == [OVER_Z, pytest.approx((2.45, 0))]


def test_both_end_points_inside_the_area_go_over():
    travels = exclusion_areas(AREA).travel_coordinates((4, 0), (5, 0.5), TOOLDIA)

    assert_avoided((4, 0), (5, 0.5), travels, AREA)
    assert travels[0][0] == OVER_Z


def test_crossing_goes_over():
    travels = exclusion_areas(AREA).travel_coordinates((0, 0), (10, 0), TOOLDIA)

    assert travels == [[OVER_Z, pytest.approx((2.4, 0))], [None, pytest.approx((6.6, 0))], [None, (10, 0)]]
    assert_avoided((0, 0), (10, 0), travels, AREA)


def test_crossing_goes_around():
    travels = exclusion_areas(AREA, strategy='around').travel_coordinates((0, 0.3), (10, -0.2), TOOLDIA)

    assert all(z is None for z, __ in travels)
    assert_avoided((0, 0.3), (10, -0.2), travels, AREA)


def test_crossing_a_concave_area_twice_goes_over_once():
    u_shape = Polygon([(3, -3), (9, -3), (9, 3), (7, 3), (7, -1), (5, -1), (5, 3), (3, 3)])
    travels = exclusion_areas(u_shape).travel_coordinates((0, 1), (12, 1), TOOLDIA)

    assert travels == [[OVER_Z, pytest.approx((2.4, 1))], [None, pytest.approx((9.6, 1))], [None, (12, 1)]]


def test_around_with_an_end_point_in_the_margin_fails():
    exc = exclusion_areas(AREA, strategy='around')

    with pytest.raises(ValueError, match='cannot go around an exclusion area'):
        exc.travel_coordinates((2.45, 0), (10, 0), TOOLDIA)


def test_the_area_entered_first_is_avoided_first():
    # the first area is the nearest one to the start point, but the travel line enters it only at x = 11.4
    near_but_entered_late = Polygon([(0, 1.5), (12, 1.5), (12, -1), (13, -1), (13, 3), (0, 3)])
    ahead = box(5, -1, 7, 1)
    exc = exclusion_areas(near_but_entered_late, ahead)
    travels = exc.travel_coordinates((0, 0), (20, 0), TOOLDIA)

    assert_avoided((0, 0), (20, 0), travels, near_but_entered_late, ahead)


@pytest.mark.parametrize('start, end', [((0, 5), (10, 5)), ((0, 0), (2.4, 0)), ((0, 1.6), (10, 1.6)),
                                        ((0, 0.8), (4.8, 2.4))])
@pytest.mark.parametrize('strategy', ['over', 'around'])
def test_travel_that_does_not_enter_the_area_is_straight(start, end, strategy):
    # far away, ending on the outline of the grown area, along it, touching its corner
    exc = exclusion_areas(AREA, strategy=strategy)

    assert exc.travel_coordinates(start, end, TOOLDIA) == [[None, end]]


def test_no_areas_is_straight():
    end = (10, 0)
    travels = exclusion_areas().travel_coordinates((0, 0), end, TOOLDIA)

    assert travels == [[None, end]]
    assert travels[0][1] is end


# drill points: accepted only outside the grown area that the travels avoid
DRILLS = [
    ((2.45, 0), False),     # 0.55 mm from the area: in the 0.1 mm margin
    ((2.39, 0), True),
    ((6.55, 0.5), False),
    ((4.5, 1.58), False),
    ((2.42, 1.58), False),  # near the corner, 0.82 mm from the area: in the mitre corner of the grown area
    ((2.38, 1.62), True),
    ((4.5, 0), False),      # inside the area
]


def check_intersection(exc, point, tooldia=TOOLDIA):
    drilling = SimpleNamespace(app=SimpleNamespace(exc_areas=exc), excellon_tools={1: {'tooldia': tooldia}})
    return ToolDrilling.check_intersection(drilling, {1: [Point(point)]})


@pytest.mark.parametrize('point, accepted', DRILLS)
def test_drilling_check_uses_the_travel_margin(point, accepted):
    exc = exclusion_areas(AREA)

    assert check_intersection(exc, point) is not accepted
    assert grown(AREA).intersects(Point(point)) is not accepted
    if accepted:
        travels = exc.travel_coordinates((10, 10), point, TOOLDIA)
        assert_avoided((10, 10), point, travels, AREA)


@pytest.mark.parametrize('distance, accepted', [(0.0215, False), (0.0245, True)])
def test_drilling_check_margin_in_inch(distance, accepted):
    exc = exclusion_areas(box(0, 0, 1, 1), units='IN')

    assert check_intersection(exc, (-distance, 0.5), tooldia=0.04) is not accepted


@pytest.mark.parametrize('point, accepted', [((2.45, 0), False), ((2.39, 0), True), ((2.42, 1.58), False)])
def test_drillcncjob_check_uses_the_travel_margin(point, accepted):
    from tclCommands.TclCommandDrillcncjob import TclCommandDrillcncjob
    from preprocessors.default import default

    app = make_app(tools_drill_toolchange=False)
    app.preprocessors['default'] = default()
    app.dec_format = round
    app.exc_areas = exclusion_areas(AREA)
    source = make_excellon(app, tooldia=TOOLDIA, drills=((10.0, 10.0), point), slots=())
    source.tools[1]['data'] = {k: v for k, v in app.options.items() if k.startswith('tools_drill_')}
    source.obj_options.update(app.options)
    source.obj_options.update(zip(('xmin', 'ymin', 'xmax', 'ymax'), source.bounds()))
    app.collection.get_by_name.return_value = source
    job = CNCjob(app)
    job.kind = 'cncjob'
    job.obj_options = {}
    job.excellon_tool_gcode_parse = Mock(return_value=[])
    results = []

    def create(kind, name, init, **kwargs):
        results.append(init(job, app))
        return job

    app.app_obj.new_object.side_effect = create
    TclCommandDrillcncjob(app).execute({'name': 'e', 'pp': 'default'}, [])
    messages = [str(c.args[0]) for c in app.inform.emit.call_args_list if c.args]

    assert (results == ['fail']) is not accepted
    assert any('Drill points inside the exclusion zones' in m for m in messages) is not accepted
