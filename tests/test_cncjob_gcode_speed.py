"""CNC job from a Geometry: the faster code gives the same G-code, the same parsed G-code and the same copies.

Run from the repository root:
    .venv/Scripts/python -m pytest tests/test_cncjob_gcode_speed.py -q
"""
from types import SimpleNamespace

import pytest
import shapely
from shapely import LineString, MultiLineString, Point

from camlib import CNCjob, deepcopy_keep_geometry
from test_unify_regressions_0b import make_app


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
