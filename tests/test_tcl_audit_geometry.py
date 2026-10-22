"""Geometry/CNC consistency regressions for Tcl editing and tool selection."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely import LineString, box
from shapely.ops import unary_union

from camlib import Geometry
from tclCommands.TclCommandMillDrills import TclCommandMillDrills
from tclCommands.TclCommandMillSlots import TclCommandMillSlots
from test_tcl_audit_regressions import make_app, object_app, FCShell


def geometry(multigeo):
    app = Mock(app_units='MM', decimals=4)
    geo = Geometry(app)
    geo.kind = 'geometry'
    geo.obj_options = {}
    geo.multigeo = multigeo
    a, b = LineString([(0, 0), (3, 0)]), LineString([(2, 0), (5, 0)])
    geo.solid_geometry = [a, b]
    geo.tools = {7: {'solid_geometry': [a], 'data': {'depth': -1}},
                 9: {'solid_geometry': [b], 'data': {'depth': -2}}}
    return geo


@pytest.mark.parametrize('multigeo', [False, True])
def test_path_subtraction_updates_cnc_tools_and_bounds(multigeo):
    geo = geometry(multigeo)
    geo.subtract_polygon(box(-1, -1, 1, 1))
    paths = unary_union([g for tool in geo.tools.values() for g in tool['solid_geometry']])
    assert paths.equals(unary_union(geo.solid_geometry))
    assert paths.intersection(box(-1, -1, 0.9, 1)).is_empty
    assert geo.obj_options['xmin'] == 1
    assert geo.tools[9]['data']['depth'] == -2


def test_union_updates_each_tool_without_mixing_multigeometry_depths():
    geo = geometry(True)
    geo.tools[7]['solid_geometry'].append(LineString([(1, 0), (4, 0)]))
    geo.union()
    assert sum(g.length for g in geo.tools[7]['solid_geometry']) == 4
    assert unary_union(geo.tools[7]['solid_geometry']).bounds == (0, 0, 4, 0)
    assert unary_union(geo.tools[9]['solid_geometry']).bounds == (2, 0, 5, 0)
    assert unary_union(geo.solid_geometry).bounds == (0, 0, 5, 0)


@pytest.mark.parametrize('tool_id', [7, '7'])
def test_real_drill_generator_keeps_tool_ids_and_stores_text_source(tool_id):
    from camlib import CNCjob
    from tclCommands.TclCommandDrillcncjob import TclCommandDrillcncjob
    from tests.helpers_objects import make_app_0b as make_app, make_excellon_0b as make_excellon  # noqa: F401,E402
    app = make_app(tools_drill_toolchange=False)
    app.exc_areas = SimpleNamespace(exclusion_areas_storage=[],
                                    travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    source = make_excellon(app, drills=((1, 1), (3, 2)), slots=())
    source.tools = {tool_id: source.tools[1]}
    source.obj_options.update(app.options)
    source.obj_options.update(zip(('xmin', 'ymin', 'xmax', 'ymax'), source.bounds()))
    app.collection.get_by_name.return_value = source
    job = CNCjob(app)
    job.kind = 'cncjob'
    job.obj_options = {}
    job.doformat = lambda *args, **kwargs: ''
    job.excellon_tool_gcode_parse = lambda *args, **kwargs: []

    def create(kind, name, init, **kwargs):
        result = init(job, app)
        assert result != 'fail'
        return job

    app.app_obj.new_object.side_effect = create
    TclCommandDrillcncjob(app).execute({'name': 'e', 'dpp': None, 'startz': 0, 'endz': 0}, [])
    assert tool_id in job.tools
    assert isinstance(job.source_file, str)
    assert job.startz == job.z_end == 0
