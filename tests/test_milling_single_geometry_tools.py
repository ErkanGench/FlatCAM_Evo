"""A single-geometry Milling job with 2 or more tools had the paths of the earlier tools in its G-code again.

generate_from_geometry_2() adds its G-code to the job (append=True) and returns all the G-code of the job. The
Milling tool called it once per tool on the same job, so the 'gcode' of tool 2 was tool 1 + tool 2 and the exported
file was tool 1 + (tool 1 + tool 2): the paths of tool 1 were made twice (a laser burns them twice, a mill cuts them
twice). Now each tool's 'gcode' holds only that tool and the file has every path once, in the same order. The job
itself keeps the G-code of all the tools, as before (Tcl export_gcode, the project, the levelling probe points).

The tests make the real G-code (default and GRBL_laser preprocessors) with the real Milling tool code and export it
with the real CNCJobObject.
"""

import importlib
import re
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from shapely.geometry import LineString, Polygon

from appObjects.CNCJobObject import CNCJobObject
from appPlugins.ToolMilling import ToolMilling
from tests.helpers_objects import make_app_0b as make_app  # noqa: F401,E402

# 3 paths with 9 X-Y cut moves in all (4 + 4 + 1)
PATHS = [Polygon([(0, 0), (10, 0), (10, 5), (0, 5)]).exterior,
         Polygon([(20, 0), (30, 0), (30, 5), (20, 5)]).exterior,
         LineString([(0, 10), (30, 10)])]
N_PATHS = 3
CUT_MOVES = 9


class MillingHarness(SimpleNamespace):
    """The real ToolMilling methods, without the application GUI."""
    def __getattr__(self, name):
        return getattr(ToolMilling, name).__get__(self, type(self))


def preprocessor(name):
    return getattr(importlib.import_module('preprocessors.' + name), name)()


def tool_data(app, uid, pp, min_power=0):
    data = {key: value for key, value in app.options.items() if key.startswith('tools_mill_')}
    data.update(tools_mill_tooldia=0.1 * uid, tools_mill_offset_type=0, tools_mill_ppname_g=pp,
                tools_mill_travelz=2.0, tools_mill_multidepth=False, tools_mill_toolchange=False,
                tools_mill_optimization_type='R', tools_mill_feedrate=100.0 * uid, tools_mill_min_power=min_power,
                # each tool is told apart by its Cut Z (mill) or by its power (laser)
                tools_mill_cutz=0.0 if 'laser' in pp else -0.05 * uid, tools_mill_spindlespeed=100 * uid)
    return data


def milling_job(n_tools, pp='default', multigeo=False, min_power=(), from_tcl=False):
    app = make_app()
    app.preprocessors = {name: preprocessor(name) for name in ('default', pp)}
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.exc_areas = SimpleNamespace(exclusion_areas_storage=[],
                                    travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    app.regFK, app.ui = Mock(), Mock()
    tools = {uid: {'tooldia': 0.1 * uid, 'solid_geometry': list(PATHS),
                   'data': tool_data(app, uid, pp, min_power[uid - 1] if min_power else 0)}
             for uid in range(1, n_tools + 1)}
    source = SimpleNamespace(multigeo=multigeo, tools=tools, solid_geometry=list(PATHS),
                             obj_options=dict(tools[1]['data'], name='board', xmin=0, ymin=0, xmax=30, ymax=10))
    jobs = []

    def new_object(kind, name, initializer, **kwargs):
        with patch('appObjects.AppObjectTemplate.ShapeCollection', Mock()):
            job = CNCJobObject(name, app)
        assert initializer(job, app) != 'fail'
        jobs.append(job)
        return job

    milling = MillingHarness(app=app, target_obj=source, sel_tools=tools, units='MM', decimals=4, circle_steps=64,
                             new_object=new_object,
                             ui=SimpleNamespace(toolchange_cb=SimpleNamespace(get_value=lambda: False)))
    milling.generate_cnc_job_handler(from_tcl=from_tcl, use_thread=False, plot=False)
    job = jobs[0]
    job.gc_header = ''
    return app, job


def exported(job):
    """The text of the exported file (File -> Save CNC Code, Tcl write_gcode, View Source)."""
    return job.export_gcode(to_file=True).getvalue()


def tool_marks(gcode, laser=False):
    """How many paths each tool has in the G-code: the plunges to its Cut Z (mill) or the laser on lines with its
    power (laser)."""
    if laser:
        return Counter(re.findall(r'^M0?3 S(\d+)$', gcode, re.MULTILINE))
    return Counter(re.findall(r'^G0?1 Z(-\d+\.\d+)$', gcode, re.MULTILINE))


def cut_moves(gcode):
    return len(re.findall(r'^G0?1 X', gcode, re.MULTILINE))


def expected_marks(tool_numbers, laser=False):
    return Counter({('%d' % (100 * k) if laser else '%.4f' % (-0.05 * k)): N_PATHS for k in tool_numbers})


def cut_items(parsed):
    return sum(1 for geo in parsed if geo['kind'][0] == 'C')


@pytest.mark.parametrize('pp', ['default', 'GRBL_laser'])
@pytest.mark.parametrize('n_tools', [2, 3])
def test_each_tool_gcode_holds_only_that_tool(n_tools, pp):
    __, job = milling_job(n_tools, pp)
    laser = 'laser' in pp
    assert list(job.tools) == list(range(1, n_tools + 1))
    for k, tool in job.tools.items():
        assert tool_marks(tool['gcode'], laser) == expected_marks([k], laser), k
        assert cut_moves(tool['gcode']) == CUT_MOVES, k


@pytest.mark.parametrize('pp', ['default', 'GRBL_laser'])
@pytest.mark.parametrize('n_tools', [2, 3])
def test_the_exported_file_has_every_path_once(n_tools, pp):
    __, job = milling_job(n_tools, pp)
    laser = 'laser' in pp
    body = ''.join(tool['gcode'] for tool in job.tools.values())
    for text in (exported(job), job.source_file):
        assert tool_marks(text, laser) == expected_marks(range(1, n_tools + 1), laser)
        assert cut_moves(text) == CUT_MOVES * n_tools
        # the start code, then the tools in their order, each one once
        assert text.count(body) == 1
        assert text.index(job.gc_start) < text.index(body)
    assert job.source_file == job.gc_start + body


@pytest.mark.parametrize('n_tools', [2, 3])
def test_multi_geometry_job_has_every_path_once(n_tools):
    # the multi-geometry path makes each tool's G-code apart (geometry_tool_gcode_gen()); not changed
    __, job = milling_job(n_tools, multigeo=True, from_tcl=True)
    body = ''.join(tool['gcode'] for tool in job.tools.values())
    for k, tool in job.tools.items():
        assert tool_marks(tool['gcode']) == expected_marks([k]), k
    assert job.source_file == body
    assert tool_marks(exported(job)) == expected_marks(range(1, n_tools + 1))
    assert exported(job).count(body) == 1


def test_the_laser_min_power_warning_looks_at_each_tool_only():
    # tool 1 keeps the laser on between the cuts (Min Power 250), tool 2 turns it off (Min Power 0): 1 warning, for
    # tool 1. With the G-code of tool 1 in the G-code of tool 2 there was a second warning that said 'Min Power is 0'.
    app, job = milling_job(2, 'GRBL_laser', min_power=(250, 0))
    warnings = [c.args[0] for c in app.inform.emit.call_args_list
                if c.args and str(c.args[0]).startswith('[WARNING]') and 'laser OFF' in str(c.args[0])]
    assert len(warnings) == 1
    assert '250' in warnings[0]
    assert '(laser OFF)' in job.tools[1]['gcode']
    assert '(laser OFF)' not in job.tools[2]['gcode']
