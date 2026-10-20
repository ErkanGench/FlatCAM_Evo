"""join_geometry (Tcl) must join like Edit -> Join.

The command called GeometryObject.merge() without multi_geo and fuse_tools: two MultiGeo isolation objects were joined
into a SingleGeo object with one tool per source object, while Edit -> Join keeps MultiGeo and fuses the tools of the
same diameter and type (preference geometry_merge_fuse_tools). merge() also expected a multi-geometry: for a list
(the isolation geometry) or a single polygon it logged "'list' object has no attribute 'geoms'" for each object and
kept a nested list. When it fuses the tools, it expected a list as tool geometry: the tool of a SingleGeo object (it
holds the solid geometry, a Polygon for bbox) or of a cutout (a MultiLineString) failed the join with "'Polygon' object
is not iterable", also in Edit -> Join. The tests use the headless fixtures of test_unify_characterization.
"""

from copy import deepcopy
from unittest.mock import Mock

from shapely.geometry import MultiLineString, MultiPolygon, box

from appObjects.GeometryObject import GeometryObject
from tclCommands.TclCommandJoinGeometry import TclCommandJoinGeometry

from test_unify_characterization import _headless_qt, app, make_gerber, parts  # noqa: F401  (fixtures)


def capture_new_objects(app):
    """app_obj.new_object() runs the init callback on a real Geometry object; returns {name: object}."""
    created = {}

    def new_object(obj_kind, obj_name, initialize, plot=True, **kw):
        assert obj_kind == 'geometry'
        obj = GeometryObject(obj_name, app)
        if initialize(obj, app) == 'fail':
            return 'fail'
        created[obj_name] = obj
        return 'ok'

    app.app_obj.new_object = Mock(side_effect=new_object)
    return created


def isolation(app, name):
    created = capture_new_objects(app)
    make_gerber(app, name='g_' + name).isolate(dia=0.2, overlap=10, iso_type=2, plot=False, passes=2, combine=True,
                                              outname=name)
    return created[name]


def single_geo(app, name, geometry):
    """A SingleGeo object with the tool that GeometryObject.set_ui() gives it: the tool holds the solid geometry."""
    obj = GeometryObject(name, app)
    obj.solid_geometry = geometry
    data = {key: value for key, value in app.options.items() if key.startswith('tools_')}
    obj.tools = {1: {'tooldia': 1.0, 'data': data, 'solid_geometry': obj.solid_geometry}}
    return obj


def run_join(app, objs, *argv):
    app.collection.get_by_name = Mock(side_effect=lambda n: objs.get(n))
    created = capture_new_objects(app)
    cmd = TclCommandJoinGeometry(app)
    args, unnamed = cmd.check_args(tuple(objs) + argv)
    return cmd.execute(args, unnamed), created


def tool_geometry(obj):
    return {uid: sorted(g.wkb_hex for g in parts(tool['solid_geometry'])) for uid, tool in obj.tools.items()}


def test_multigeo_objects_are_joined_as_in_the_gui(app):
    a, b = isolation(app, 'a'), isolation(app, 'b')
    assert a.multigeo and b.multigeo

    ret, created = run_join(app, {'a': a, 'b': b}, '-outname', 'joined')
    assert ret != 'fail'
    joined = created['joined']

    gui = GeometryObject('gui', app)
    GeometryObject.merge(geo_list=[a, b], geo_final=gui, multi_geo=True,
                         fuse_tools=app.options['geometry_merge_fuse_tools'], log=app.log)

    assert joined.multigeo is True
    assert tool_geometry(joined) == tool_geometry(gui)
    # with the default preference the tools of the same diameter and type are fused into 1 tool
    assert app.options['geometry_merge_fuse_tools'] is True
    assert list(joined.tools) == [1]
    assert len(parts(joined.tools[1]['solid_geometry'])) == len(parts(a.solid_geometry)) + len(parts(b.solid_geometry))


def test_list_solid_geometry_is_flattened_without_errors(app):
    a, b = isolation(app, 'a'), isolation(app, 'b')
    assert isinstance(a.solid_geometry, list)
    app.log = Mock()

    ret, created = run_join(app, {'a': a, 'b': b}, '-outname', 'joined')
    assert ret != 'fail'
    joined = created['joined']

    assert not any(isinstance(g, list) for g in joined.solid_geometry)
    assert len(joined.solid_geometry) == len(parts(a.solid_geometry)) + len(parts(b.solid_geometry))
    app.log.error.assert_not_called()


def test_singlegeo_objects_stay_singlegeo(app):
    a = single_geo(app, 'a', box(0, 0, 1, 1))
    b = single_geo(app, 'b', MultiPolygon([box(2, 0, 3, 1), box(4, 0, 5, 1)]))
    app.log = Mock()

    ret, created = run_join(app, {'a': a, 'b': b}, '-outname', 'joined')
    assert ret != 'fail'
    joined = created['joined']

    expected = [(0.0, 0.0, 1.0, 1.0), (2.0, 0.0, 3.0, 1.0), (4.0, 0.0, 5.0, 1.0)]
    assert joined.multigeo is False
    assert sorted(g.bounds for g in joined.solid_geometry) == expected
    # the 2 tools of the same diameter and type are fused; their geometry is a Polygon and a MultiPolygon
    assert list(joined.tools) == [1]
    assert sorted(g.bounds for g in joined.tools[1]['solid_geometry']) == expected
    app.log.error.assert_not_called()


def test_multigeo_tool_geometry_of_a_cutout_is_joined(app):
    a = isolation(app, 'a')
    # as the cutout makes it: MultiGeo, the tool geometry is the MultiLineString of the solid geometry
    cut = GeometryObject('cut', app)
    cut.multigeo = True
    cut.solid_geometry = MultiLineString([[(0, -2), (5, -2)], [(5, -3), (0, -3)]])
    cut.tools = {1: {'tooldia': '1.0', 'data': deepcopy(a.tools[1]['data']), 'solid_geometry': cut.solid_geometry}}

    ret, created = run_join(app, {'a': a, 'cut': cut}, '-outname', 'joined')
    assert ret != 'fail'
    joined = created['joined']

    assert joined.multigeo is True
    lines = {float(tool['tooldia']): len(parts(tool['solid_geometry'])) for tool in joined.tools.values()}
    assert lines == {float(a.tools[1]['tooldia']): len(parts(a.solid_geometry)), 1.0: 2}


def test_multigeo_and_singlegeo_objects_are_not_joined(app):
    a = isolation(app, 'a')
    single = GeometryObject('single', app)
    single.solid_geometry = list(parts(a.solid_geometry))
    assert a.multigeo and not single.multigeo

    ret, created = run_join(app, {'a': a, 'single': single}, '-outname', 'joined')
    assert ret == 'fail'
    assert created == {}
    app.app_obj.new_object.assert_not_called()
