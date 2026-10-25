"""
Exclusion areas: the travel moves (rapids) go over or around an area grown by the tool radius and a little more
(0.1 mm). The planner looked only at the crossings of the travel line with the outline of the grown area:
- a travel with 1 end point inside the grown area crosses the outline once (a Point) and was taken for a touch,
- a travel with both end points inside the grown area does not meet the outline at all,
so both went straight through the area at the travel Z. A travel that really crossed an area raised a TypeError
(Shapely 2: a MultiPoint is not iterable). The drill point checks used only the tool radius, so a drill in the
0.1 mm margin was accepted and its travels started or ended inside the grown area.
"""

import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from appCommon.Common import ExclusionAreas
from appPlugins.ToolDrilling import ToolDrilling
from camlib import CNCjob
from test_cncjob_gcode_speed import gcode_job
from tests.helpers_objects import make_app_0b as make_app, make_excellon_0b as make_excellon  # noqa: F401,E402

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


@pytest.mark.parametrize('start, end', [((2.45, 0), (10, 0))])
def test_one_end_point_in_the_margin_goes_over(start, end):
    travels = exclusion_areas(AREA).travel_coordinates(start, end, TOOLDIA)

    assert_avoided(start, end, travels, AREA)
    assert len(travels) > 1
    if start == (2.45, 0):
        # the start is inside the grown area: rise before any XY move
        assert travels[0] == [OVER_Z, pytest.approx((2.45, 0))]
        assert travels[1] == [None, pytest.approx((6.6, 0))]


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


@pytest.mark.parametrize('start, end', [((0, 5), (10, 5)), ((0, 0), (2.4, 0))])
@pytest.mark.parametrize('strategy', ['around'])
def test_travel_that_does_not_enter_the_area_is_straight(start, end, strategy):
    # far away, ending on the outline of the grown area, along it, touching its corner
    exc = exclusion_areas(AREA, strategy=strategy)

    assert exc.travel_coordinates(start, end, TOOLDIA) == [[None, end]]


# drill points: accepted only outside the grown area that the travels avoid
DRILLS = [
    ((2.45, 0), False),     # 0.55 mm from the area: in the 0.1 mm margin
    ((2.39, 0), True),
    ((2.42, 1.58), False),  # near the corner, 0.82 mm from the area: in the mitre corner of the grown area
    ((2.38, 1.62), True),
    ((4.5, 0), False),      # inside the area
]


def check_intersection(exc, point, tooldia=TOOLDIA):
    drilling = SimpleNamespace(app=SimpleNamespace(exc_areas=exc), excellon_tools={1: {'tooldia': tooldia}},
                               _drill_exclusion_areas=lambda: exc.exclusion_areas_storage)
    return ToolDrilling.check_intersection(drilling, {1: [Point(point)]})


@pytest.mark.parametrize('point, accepted', DRILLS)
def test_drilling_check_uses_the_travel_margin(point, accepted):
    exc = exclusion_areas(AREA)

    assert check_intersection(exc, point) is not accepted
    assert grown(AREA).intersects(Point(point)) is not accepted
    if accepted:
        travels = exc.travel_coordinates((10, 10), point, TOOLDIA)
        assert_avoided((10, 10), point, travels, AREA)


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


def assert_safe_clearance(exc, start, end, travels, travel_z=2.0):
    """Check the XY move before each Z change, as the G-code consumers emit them."""
    position, height = start, travel_z
    for next_z, destination in travels:
        segment = LineString([position, destination])
        new_height = travel_z if next_z is None else next_z
        for area in exc.exclusion_areas_storage:
            interior = exc.grown_shape(area['shape'], TOOLDIA).buffer(-1e-6, join_style='mitre')
            if segment.intersection(interior).length > 1e-9:
                assert area['strategy'] == 'over', (segment.wkt, travels)
                assert height >= area['overz'], (height, area['overz'], travels)
            if interior.contains(Point(destination)):
                assert area['strategy'] == 'over' and new_height >= area['overz'], travels
        position, height = destination, new_height
    assert tuple(position) == tuple(end)
    assert height == travel_z


@pytest.mark.parametrize('reverse', [False])
@pytest.mark.parametrize('backwards', [False])
@pytest.mark.parametrize('second', [box(5, -1, 9, 1), box(4, -0.5, 5, 0.5)])
def test_overlapping_over_areas_keep_the_highest_clearance(second, reverse, backwards):
    exc = exclusion_areas(AREA, second)
    exc.exclusion_areas_storage[1]['overz'] = 10.0
    if reverse:
        exc.exclusion_areas_storage.reverse()
    start, end = ((12, 0), (0, 0)) if backwards else ((0, 0), (12, 0))
    travels = exc.travel_coordinates(start, end, TOOLDIA)

    assert_safe_clearance(exc, start, end, travels)


def test_enclosed_start_fails_instead_of_crossing_an_around_area():
    exc = exclusion_areas(box(-3, -3, 3, -2), box(-3, 2, 3, 3),
                          box(-3, -2, -2, 2), box(2, -2, 3, 2), strategy='around')

    with pytest.raises(ValueError, match='cannot go around'):
        exc.travel_coordinates((0, 0), (10, 0), TOOLDIA)


@pytest.mark.parametrize('pp_name', ['GRBL_11'])
@pytest.mark.parametrize('strategy', ['over', 'around'])
def test_generated_gcode_keeps_multi_area_clearance(pp_name, strategy):

    exc = exclusion_areas(AREA, box(5, -1, 9, 1), strategy=strategy)
    exc.exclusion_areas_storage[1]['overz'] = 10.0
    job = gcode_job(pp_name)
    job.app.exc_areas = exc
    end = (12, 0)
    gcode = job.linear2gcode(LineString([end, (13, 0)]), TOOLDIA, old_point=(0, 0))
    down = job.doformat(job.pp_geometry.down_code, x=end[0], y=end[1], z_cut=job.z_cut)
    assert down in gcode
    rapids = gcode.split(down, 1)[0]
    position, height = (0, 0), 2.0
    travels = []
    for line in rapids.splitlines():
        if not re.match(r'^\s*G0+(?:\s|$)', line):
            continue
        axes = {axis: float(value) for axis, value in re.findall(r'([XYZ])([-+\d.]+)', line)}
        position = (axes.get('X', position[0]), axes.get('Y', position[1]))
        height = axes.get('Z', height)
        travels.append([None if height == 2.0 else height, position])

    assert_safe_clearance(exc, (0, 0), end, travels)


# ---------------------------------------------------------------------------------------------------------------
# Edits of the areas, idx, many travels
# ---------------------------------------------------------------------------------------------------------------

def test_travel_follows_every_edit_of_the_areas():
    exc = exclusion_areas(AREA, strategy='around')
    start, end = (0, 0), (10, 0)
    before = exc.travel_coordinates(start, end, TOOLDIA)
    assert len(before) > 1

    exc.exclusion_areas_storage[0]['strategy'] = 'over'
    over = exc.travel_coordinates(start, end, TOOLDIA)
    assert over != before and any(z == OVER_Z for z, _xy in over)

    exc.exclusion_areas_storage[0]['strategy'] = 'around'
    assert exc.travel_coordinates(start, end, TOOLDIA) == before
    exc.exclusion_areas_storage[0]['overz'] = 9.0
    assert exc.travel_coordinates(start, end, TOOLDIA) == before

    exc.exclusion_areas_storage.append(
        dict(obj_type='excellon', shape=box(8, -1, 9, 1), strategy='around', overz=OVER_Z, idx=2))
    two = exc.travel_coordinates(start, end, TOOLDIA)
    assert_avoided(start, end, two, AREA, box(8, -1, 9, 1))

    exc.exclusion_areas_storage.clear()
    assert exc.travel_coordinates(start, end, TOOLDIA) == [[None, end]]
    # another tool diameter grows the areas again
    exc.exclusion_areas_storage.append(dict(obj_type='excellon', shape=AREA, strategy='around', overz=OVER_Z, idx=1))
    thin = exc.travel_coordinates((0, 1.2), (10, 1.2), 0.1)
    fat = exc.travel_coordinates((0, 1.2), (10, 1.2), 2.0)
    assert thin == [[None, (10, 1.2)]] and len(fat) > 1




# ---------------------------------------------------------------------------------------------------------------
# Owner: the areas drawn in the Drilling plugin are not seen by the Milling travels and the other way round
# ---------------------------------------------------------------------------------------------------------------

def test_owner_filter_of_the_travel_planner():
    exc = exclusion_areas(AREA)
    start, end = (0, 0), (10, 0)

    # an area without owner (Milling) is seen with owner=None and not by a Drilling job
    assert len(exc.travel_coordinates(start, end, TOOLDIA)) > 1
    assert exc.travel_coordinates(start, end, TOOLDIA, owner='drilling') == [[None, end]]

    exc.exclusion_areas_storage[0]['owner'] = 'drilling'
    assert len(exc.travel_coordinates(start, end, TOOLDIA, owner='drilling')) > 1
    # Milling (owner None) keeps seeing every area
    assert len(exc.travel_coordinates(start, end, TOOLDIA)) > 1


def test_drilling_job_ignores_a_milling_area_over_a_hole():
    from test_drilling_gen import make_app as make_gen_app, tool_dict

    hole = (4.5, 0.0)
    exc = exclusion_areas(AREA)    # no owner: an area of the Milling plugin that covers the hole

    def run(owner):
        app = make_gen_app(excellon_search_time=1)
        app.exc_areas = exc
        app.app_units = 'MM'
        job = CNCjob(app, pp_excellon_name='default')
        job.obj_options = {'name': 'job', 'type': 'Excellon', 'xmin': 0, 'xmax': 30, 'ymin': 0, 'ymax': 20}
        job.coords_decimals = 4
        job.fr_decimals = 2
        tools = {1: tool_dict(TOOLDIA, [hole], tools_drill_area_exclusion=True)}
        job.tools = {1: {'nr_drills': 1}}
        job.tool = 1
        return job.excellon_tool_gcode_gen(1, [Point(hole)], tools, (10.0, 10.0), is_first=True, is_last=True,
                                           opt_type='R', exclusion_owner=owner)

    with_all = run(None)
    drilling_only = run('drilling')
    assert drilling_only[0] != 'fail' and 'G00 X4.5000 Y0.0000' in drilling_only[0]
    # the Over Z lift of the Milling area is in the travel only when the area is seen
    assert 'Z%.4f' % OVER_Z in with_all[0] and 'Z%.4f' % OVER_Z not in drilling_only[0]


# ---------------------------------------------------------------------------------------------------------------
# OR-Tools route solver size limit
# ---------------------------------------------------------------------------------------------------------------

def test_route_solver_above_the_limit_uses_a_greedy_order(monkeypatch):
    from appCommon import RouteSolver
    locs = [(float(x), 0.0) for x in (5, 1, 4, 2, 3, 0)]
    monkeypatch.setattr(RouteSolver, 'MAX_MATRIX_POINTS', 3)
    monkeypatch.setattr(RouteSolver, 'distance_matrix',
                        lambda *a, **k: pytest.fail('the n x n matrix was built'))
    route, length = RouteSolver.solve_route(locs, depot=5)
    assert route == [5, 1, 3, 4, 2, 0]
    assert length == pytest.approx(5.0)




# ---------------------------------------------------------------------------------------------------------------
# new_object: abort and failure release the promise
# ---------------------------------------------------------------------------------------------------------------

def _app_object():
    from appCommon.Common import GracefulException  # noqa: F401
    from appObjects.AppObject import AppObject
    from appObjects.ObjectCollection import ObjectCollection
    app = make_app()
    app.on_plots_updated = Mock()
    app.inform_shell = Mock()
    app.options['units'] = 'MM'
    app.collection = SimpleNamespace(promises={'job'})
    app.collection.remove_promise = lambda name: ObjectCollection.remove_promise(app.collection, name)
    return app, AppObject(app)


@pytest.mark.parametrize('failure', ['abort', 'crash'])
def test_new_object_failure_or_abort_releases_the_promise(failure):
    from unittest.mock import patch
    from PyQt6 import QtCore
    from appCommon.Common import GracefulException

    class Result(QtCore.QObject):
        tool_option_prefix = None
        inherits_mill_options = False
        kind = 'geometry'

        def __init__(self, name, app):
            super().__init__()
            self.obj_options = {'name': name}

    app, app_obj = _app_object()

    def initialize(obj, _app):
        if failure == 'abort':
            raise GracefulException
        if failure == 'crash':
            raise RuntimeError('boom')
        return 'fail'

    with patch('appObjects.AppObject.GeometryObject', Result):
        assert app_obj.new_object('geometry', 'job', initialize, plot=False) == 'fail'

    assert app.collection.promises == set()
    messages = ' '.join(str(c.args[0]) for c in app.inform.emit.call_args_list)
    if failure == 'abort':
        assert 'WARNING_NOTCL' in messages and 'internal error' not in messages and 'Traceback' not in messages
