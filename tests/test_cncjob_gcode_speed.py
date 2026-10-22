"""CNC job from a Geometry: the faster code gives the same G-code, the same parsed G-code and the same copies.

Run from the repository root:
    .venv/Scripts/python -m pytest tests/test_cncjob_gcode_speed.py -q
"""
import re
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import shapely
from shapely import LinearRing, LineString, MultiLineString, Point

import camlib
from camlib import CNCjob, deepcopy_keep_geometry, simplify_paths
from defaults import AppDefaults
from tests.helpers_objects import make_app_0b as make_app  # noqa: F401,E402


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
    @pytest.mark.parametrize('pp_name', PREPROCESSORS[::4])
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
    @pytest.mark.parametrize('workers', [2])
    @pytest.mark.parametrize('count', [5])
    @pytest.mark.parametrize('cancel_before', [False, True])
    def test_cancel_stops_simplification(self, count, cancel_before, workers):
        job = gcode_job('default')
        tools = milling_tools(noisy_paths(count))
        original_simplify = shapely.simplify

        def emit(message):
            if cancel_before and 'Starting G-Code for tool with diameter' in message:
                job.app.abort_flag = True

        def simplify(piece, tolerance):
            job.app.abort_flag = True
            return original_simplify(piece, tolerance)

        with patch.object(job.app.inform, 'emit', side_effect=emit), \
                patch.object(camlib.os, 'cpu_count', return_value=workers), \
                patch.object(shapely, 'simplify', side_effect=simplify) as mock:
            with pytest.raises(camlib.grace):
                job.geometry_tool_gcode_gen(1, tools, (0, 0), (0, 0), 0.005, is_first=True, is_last=True)
        assert mock.call_count == (0 if cancel_before else 1)
        if not cancel_before and count == 300:
            assert len(mock.call_args.args[0]) < count

    @pytest.mark.parametrize('changes', [{'tools_mill_multidepth': True, 'tools_mill_depthperpass': 0.02},
                                         {'tools_mill_extracut': True, 'tools_mill_extracut_length': 0.2}])
    def test_multi_depth_and_extra_cut_simplify_each_path(self, changes):
        __, presimplified, __ = tool_gcode('default', noisy_paths(40), **changes)
        assert not presimplified


def old_codes_split(job, gline):
    """CNCjob.codes_split() before the patterns were compiled once: the reference."""
    command = {}

    if job.pp_solderpaste_name is not None:
        if gline.strip() in ('(PASTE_ON)', ';PASTE_ON'):
            return {'Z': 0}
        if gline.strip() in ('(PASTE_OFF)', ';PASTE_OFF'):
            return {'Z': 1}
        dot = re.match(r'^[;(]PASTE_DOT X([+\-\d.]+) Y([+\-\d.]+) D([+\-\d.]+)', gline)
        if dot:
            return {'X': float(dot[1]), 'Y': float(dot[2]), '_paste_dot': float(dot[3])}

    if 'Roland' in job.pp_excellon_name or 'Roland' in job.pp_geometry_name:
        match_z = re.search(r"^Z(\s*-?\d+\.\d+?),(\s*\s*-?\d+\.\d+?),(\s*\s*-?\d+\.\d+?)*;$", gline)
        if match_z:
            command['G'] = 0
            command['X'] = float(match_z.group(1).replace(" ", "")) * 0.01
            command['Y'] = float(match_z.group(2).replace(" ", "")) * 0.01
            command['Z'] = float(match_z.group(3).replace(" ", "")) * 0.025
    elif 'hpgl' in job.pp_excellon_name or 'hpgl' in job.pp_geometry_name:
        match_pa = re.search(r"^PA(\s*-?\d+\.\d+?),(\s*\s*-?\d+\.\d+?)*;$", gline)
        if match_pa:
            command['G'] = 0
            command['X'] = float(match_pa.group(1).replace(" ", "")) / 40
            command['Y'] = float(match_pa.group(2).replace(" ", "")) / 40
        match_pen = re.search(r"^(P[U|D])", gline)
        if match_pen:
            command['Z'] = 1 if match_pen.group(1) == 'PU' else 0
        if re.search(r"^SP\d*", gline):
            command['Z'] = 1
    elif 'laser' in job.pp_excellon_name.lower() or 'laser' in job.pp_geometry_name.lower() or \
            (job.pp_solderpaste_name is not None and 'paste' in job.pp_solderpaste_name.lower()):
        match_lsr = re.search(r"X([+-]?\d+.[+-]?\d+)\s*Y([+-]?\d+.[+-]?\d+)", gline)
        if match_lsr:
            command['X'] = float(match_lsr.group(1).replace(" ", ""))
            command['Y'] = float(match_lsr.group(2).replace(" ", ""))
        match_lsr_pos = re.search(r"^(M0?[3-5])", gline)
        if match_lsr_pos:
            command['Z'] = 1 if ('M05' in match_lsr_pos.group(1) or 'M5' in match_lsr_pos.group(1)) else 0
        match_lsr_pos_2 = re.search(r"^(M10[6|7])", gline)
        if match_lsr_pos_2:
            command['Z'] = 1 if 'M107' in match_lsr_pos_2.group(1) else 0
        match_lsr_pos_3 = re.search(r"^.*(laser OFF).*", gline)
        if match_lsr_pos_3:
            command['Z'] = 1 if 'laser OFF' in match_lsr_pos_3.group(1) else 0
    elif job.pp_solderpaste_name is not None:
        if 'Paste' in job.pp_solderpaste_name:
            match_paste = re.search(r"X([+-]?\d+.[+-]?\d+)\s*Y([+-]?\d+.[+-]?\d+)", gline)
            if match_paste:
                command['X'] = float(match_paste.group(1).replace(" ", ""))
                command['Y'] = float(match_paste.group(2).replace(" ", ""))
    else:
        match = re.search(r'^\s*([A-Z])\s*([+\-.\d\s]+)', gline)
        while match:
            command[match.group(1)] = float(match.group(2).replace(" ", ""))
            gline = gline[match.end():]
            match = re.search(r'^\s*([A-Z])\s*([+\-.\d\s]+)', gline)
    return command


LINES = [
    'G0 X1.0000 Y2.0000', 'G1 X-1.5 Y2.5 F1000', 'G01 X1.2 Y-3.4 Z0.5', '  G1X1Y2', 'G00 Z2.0000', 'T1', 'M6',
    'M3 S500', 'M03 S500', 'M4', 'M5', 'M05', ' M5', 'M106 S255', 'M107', 'M3 S0 (laser OFF)', 'G94', 'G21',
    '(comment X1 Y2)', '', 'X1.0 Y2.0', 'G1 X 1.25 Y 2.5', 'PA10.0,20.0;', 'PU;', 'PD;', 'SP1;',
    'Z100.0,200.0,-50.0;', 'Z1.5,2.5;', 'G1 X1.0000Y2.0000', 'M5 (laser OFF)', 'G0 X1e3 Y2', 'G1 X1 Y2 ; laser OFF',
    '(PASTE_ON)', ';PASTE_OFF', ';PASTE_DOT X1.5 Y-2 D0.4', 'G4 P1.5', 'G1 X1.2.3', 'MOVEABS 1000, 2000',
]
NAMES = [
    ('default', 'default', None), ('default', 'GRBL_laser', None), ('GRBL_laser_z', 'default', None),
    ('default', 'Roland_MDX_20', None), ('default', 'hpgl', None), ('default', 'default', 'Paste_1'),
    ('default', 'default', 'other'), ('default', 'Marlin_laser_FAN_pin', None), ('default', 'GRBL_11', None),
]


class TestCodesSplit:
    @pytest.mark.parametrize('names', NAMES)
    def test_same_as_before(self, names):
        job = SimpleNamespace(pp_excellon_name=names[0], pp_geometry_name=names[1], pp_solderpaste_name=names[2])
        for line in LINES:
            try:
                expected = old_codes_split(job, line)
            except ValueError:
                with pytest.raises(ValueError):
                    CNCjob.codes_split(job, line)
                continue
            assert CNCjob.codes_split(job, line) == expected, (names, line)

