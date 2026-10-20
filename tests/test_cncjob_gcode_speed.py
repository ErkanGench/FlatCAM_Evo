"""CNC job from a Geometry: the faster code gives the same G-code, the same parsed G-code and the same copies.

Run from the repository root:
    .venv/Scripts/python -m pytest tests/test_cncjob_gcode_speed.py -q
"""
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import shapely
from shapely import LinearRing, LineString, MultiLineString, Point

import camlib
from camlib import CNCjob, deepcopy_keep_geometry, simplify_paths
from defaults import AppDefaults
from test_unify_regressions_0b import make_app


def noisy_paths(count, seed=3):
    """Open and closed paths with many points close to straight lines (they simplify to a few points)."""
    rng = np.random.default_rng(seed)
    paths = []
    for k in range(count):
        x0, y0 = (k % 20) * 3.0, (k // 20) * 3.0
        t = np.linspace(0, 1, 40 + k % 30)
        xs = x0 + 2 * t + rng.normal(0, 0.0004, len(t))
        ys = y0 + np.where(t < 0.5, t, 1 - t) + rng.normal(0, 0.0004, len(t))
        coords = np.column_stack([xs, ys])
        if k % 3 == 0:
            paths.append(LinearRing(np.vstack([coords, [[x0 + 1, y0 - 1]]])))
        else:
            paths.append(LineString(coords))
    return paths


class TestDeepcopyKeepGeometry:
    def test_geometries_shared_containers_copied(self):
        line = LineString([(0, 0), (1, 1)])
        lines = [line, Point(2, 2)]
        src = {'solid_geometry': lines, 'again': lines, 'pair': (line, [3]), 'data': {'a': [1, 2], 'b': 'x'},
               'multi': MultiLineString([[(0, 0), (1, 0)]])}
        src['self'] = src
        dup = deepcopy_keep_geometry(src)

        assert dup['solid_geometry'][0] is line
        assert dup['pair'][0] is line
        assert dup['multi'] is src['multi']
        assert dup['solid_geometry'] is not lines
        # a container referenced twice is copied once, as deepcopy() does
        assert dup['again'] is dup['solid_geometry']
        assert dup['self'] is dup
        dup['data']['a'].append(3)
        dup['pair'][1].append(4)
        dup['solid_geometry'].append(line)
        assert src['data']['a'] == [1, 2]
        assert src['pair'][1] == [3]
        assert len(lines) == 2

    def test_plain_values(self):
        assert deepcopy_keep_geometry(None) is None
        assert deepcopy_keep_geometry([1, 'a', 2.5]) == [1, 'a', 2.5]


class TestSimplifyPaths:
    @pytest.mark.parametrize('count', [5, 300])
    def test_same_as_one_by_one(self, count):
        paths = noisy_paths(count)
        paths += [paths[1], Point(1, 2)]    # a path twice and a point
        simplified = simplify_paths(paths, 0.005)
        assert len(simplified) == len(paths)
        for path, result in zip(paths, simplified):
            assert result.geom_type == path.simplify(0.005).geom_type
            assert result.wkb == path.simplify(0.005).wkb
        assert simplified[1] is simplified[-2]

    def test_empty(self):
        assert simplify_paths([], 0.005) == []


def gcode_job(pp_name, app=None):
    app = app or make_app()
    module = __import__('preprocessors.%s' % pp_name, fromlist=[pp_name])
    app.preprocessors[pp_name] = getattr(module, pp_name)()
    app.exc_areas = SimpleNamespace(travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    job = CNCjob(app, pp_geometry_name=pp_name)
    job.obj_options = {'name': 'job', 'type': 'Geometry'}
    job.coords_decimals = 4
    job.fr_decimals = 2
    job.z_cut = -0.1
    job.z_move = 2.0
    return job


PREPROCESSORS = ['default', 'GRBL_laser', 'GRBL_11', 'Marlin', 'Line_xyz', 'hpgl', 'Roland_MDX_20', 'ISEL_ICP_CNC']


class TestLinear2Gcode:
    @pytest.mark.parametrize('pp_name', PREPROCESSORS)
    def test_cut_lines_same_as_doformat(self, pp_name):
        job = gcode_job(pp_name)
        p = job.pp_geometry
        path = noisy_paths(2)[1]
        gcode = job.linear2gcode(path, 0.1, tolerance=0)

        coords = list(path.coords)
        cuts = [job.doformat(p.linear_code, x=x, y=y, z_cut=job.z_cut) for x, y in coords[1:]]
        assert all(line.strip() for line in cuts)
        assert ''.join(cuts) in gcode
        last_x, last_y = coords[-1]
        assert gcode.endswith(job.doformat(p.lift_code, x=last_x, y=last_y, z_move=job.z_move))

    def test_preprocessor_errors_as_doformat(self):
        job = gcode_job('default')

        def broken(_attributes):
            raise ValueError('broken preprocessor')

        attributes = camlib.AttrDict(job.postdata)
        assert job.doformat_attributes(broken, attributes) == ''
        assert job.doformat(broken) == '\n'
        job.pp_solderpaste_name = 'Paste_1'
        with pytest.raises(ValueError):
            job.doformat_attributes(broken, attributes)


def milling_tools(paths, **data_changes):
    data = dict(AppDefaults.factory_defaults)
    data.update(tools_mill_tooldia=0.1, tools_mill_offset_value=0.0, tools_mill_optimization_type='R',
                tools_mill_multidepth=False, tools_mill_extracut=False, tools_mill_cutz=-0.05,
                tools_mill_travelz=2.0, tools_mill_feedrate=300.0, tools_mill_spindlespeed=1000.0)
    data.update(data_changes)
    return {1: {'tooldia': 0.1, 'data': data, 'solid_geometry': paths}}


def tool_gcode(pp_name, paths, per_path=False, **data_changes):
    """
    :param per_path:    True: the reference, every path simplified by linear2gcode(), one by one (as before)
    :return:            G-code, if the paths were simplified at once, (travel distance, routing time)
    """
    job = gcode_job(pp_name)
    tools = milling_tools(paths, tools_mill_ppname_g=pp_name, **data_changes)
    if per_path:
        presimplify = patch.object(camlib, 'simplify_paths', return_value=None)
    else:
        presimplify = patch.object(camlib, 'simplify_paths', wraps=camlib.simplify_paths)
    with presimplify as mock:
        gcode, __ = job.geometry_tool_gcode_gen(1, tools, (0, 0), (0, 0), 0.005, is_first=True, is_last=True)
    return gcode, mock.called, (job.travel_distance, job.routing_time)


class TestGeometryToolGcode:
    @pytest.mark.parametrize('pp_name', ['GRBL_laser', 'default'])
    @pytest.mark.parametrize('opt_type', ['R', 'N'])
    def test_simplified_at_once_same_gcode(self, pp_name, opt_type):
        paths = noisy_paths(120)
        # reversed paths: the optimization picks their last point, the path is reversed before its simplification
        paths = [LineString(list(path.coords)[::-1]) if k % 4 == 1 else path for k, path in enumerate(paths)]
        gcode, presimplified, totals = tool_gcode(pp_name, paths, tools_mill_optimization_type=opt_type)
        reference, __, reference_totals = tool_gcode(pp_name, paths, per_path=True,
                                                     tools_mill_optimization_type=opt_type)
        assert presimplified
        assert gcode.count('\n') > 500
        assert gcode == reference
        assert totals == reference_totals

    @pytest.mark.parametrize('changes', [{'tools_mill_multidepth': True, 'tools_mill_depthperpass': 0.02},
                                         {'tools_mill_extracut': True, 'tools_mill_extracut_length': 0.2}])
    def test_multi_depth_and_extra_cut_simplify_each_path(self, changes):
        __, presimplified, __ = tool_gcode('default', noisy_paths(40), **changes)
        assert not presimplified


class TestMillingCopies:
    @pytest.mark.parametrize('multigeo', [False, True])
    def test_job_tools_share_geometries_not_containers(self, multigeo):
        from preprocessors.default import default
        from test_milling_lifecycle import _cnc_harness

        milling = _cnc_harness(multigeo)[0]
        app = make_app()
        app.preprocessors['default'] = default()
        app.dec_format = lambda value, decimals: round(value, decimals)
        app.exc_areas = SimpleNamespace(travel_coordinates=lambda **kw: [(None, kw['end_point'])])
        milling.app = app
        milling.sel_tools = {7: milling.sel_tools[7]}
        milling.target_obj.tools = milling.sel_tools
        source_geometry = milling.target_obj.tools[7]['solid_geometry']
        milling.sel_tools[7]['data'].update(tools_mill_offset_type=0, tools_mill_toolchange=False,
                                            tools_mill_cutz=-0.5, tools_mill_feedrate=120)
        jobs = []

        def new_object(kind, name, initializer, **kwargs):
            job = CNCjob(app)
            job.kind, job.obj_options, job.tools, job.gc_start = kind, {'name': name}, {}, ''
            assert initializer(job, app) != 'fail'
            jobs.append(job)
            return job

        milling.new_object = new_object
        milling.generate_cnc_job_handler(use_thread=False, toolchange=False)
        record = jobs[0].tools[7]

        assert record['solid_geometry'] is not source_geometry
        assert all(a is b for a, b in zip(record['solid_geometry'], source_geometry))
        assert record['data'] is not milling.sel_tools[7]['data']
        parsed = record['gcode_parsed']
        assert parsed and parsed is not jobs[0].gcode_parsed
        assert all(a is not b and a['geom'] is b['geom'] for a, b in zip(parsed, jobs[0].gcode_parsed))
        assert all(isinstance(g['geom'], shapely.Geometry) for g in parsed)
