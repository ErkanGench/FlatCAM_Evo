"""Laser Min Power warning.

Above 0 the 'laser' preprocessors write the laser minimum power in place of the laser off code
(e.g. 'M03 S250 (laser OFF)' instead of 'M5'), so the laser is not turned off between the cuts.
Each G-code generator warns when its G-code has these 'laser OFF' lines.
"""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely.geometry import LineString

from camlib import AttrDict, CNCjob, Geometry
from defaults import AppDefaults
from test_unify_regressions_0b import make_app, make_excellon

LASER_PREPROCESSORS = ['GRBL_laser', 'GRBL_laser_z', 'default_laser', 'Marlin_laser_FAN_pin',
                       'Marlin_laser_Spindle_pin', 'Marlin_laser_z', 'grbl_laser_eleks_drd']


def laser_app(pp_name='GRBL_laser', **option_overrides):
    app = make_app(**option_overrides)
    app.preprocessors[pp_name] = getattr(importlib.import_module('preprocessors.%s' % pp_name), pp_name)()
    app.dec_format = round
    app.exc_areas = SimpleNamespace(exclusion_areas_storage=[],
                                    travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    return app


def laser_warnings(app):
    return [c.args[0] for c in app.inform.emit.call_args_list
            if c.args and str(c.args[0]).startswith('[WARNING]') and 'laser OFF' in str(c.args[0])]


def laser_job(app, obj_type='Geometry', **kwargs):
    job = CNCjob(app, **kwargs)
    job.obj_options = {'name': 'job', 'type': obj_type}
    job.coords_decimals = 4
    job.fr_decimals = 2
    return job


def mill_paths():
    return [LineString([(0, 0), (2, 0)]), LineString([(5, 0), (7, 0)])]


def milling_tool_job(pp_name, min_power):
    app = laser_app(pp_name)
    job = laser_job(app)
    data = dict(AppDefaults.factory_defaults)
    data.update(tools_mill_tooldia=0.1, tools_mill_offset_value=0, tools_mill_optimization_type='R',
                tools_mill_ppname_g=pp_name, tools_mill_min_power=min_power, tools_mill_cutz=0,
                tools_mill_spindlespeed=500, tools_mill_multidepth=False)
    tools = {1: {'data': data, 'tooldia': 0.1, 'solid_geometry': mill_paths()}}
    gcode, __ = job.geometry_tool_gcode_gen(1, tools, (0, 0), (0, 0), 0.001)
    return app, gcode


def test_warning_only_for_gcode_with_laser_off_lines():
    app = laser_app()
    job = CNCjob(app)
    job.laser_min_power = 250

    job.laser_min_power_warning('G0 X0 Y0\nM03 S500\nG1 X2 Y0 F100\nM5\n')
    assert laser_warnings(app) == []

    job.laser_min_power_warning('G0 X0 Y0\nM03 S500\nG1 X2 Y0 F100\nM03 S250 (laser OFF)\n')
    job.laser_min_power_warning('G0 X0 Y0\nM106 S255\nG1 X2 Y0 F100\nM106 S250 ;laser OFF\n')
    msgs = laser_warnings(app)
    assert len(msgs) == 2
    assert all('250' in m for m in msgs)


@pytest.mark.parametrize('pp_name', ['GRBL_laser', 'GRBL_laser_z', 'grbl_laser_eleks_drd'])
def test_grbl_laser_activation_does_not_reuse_previous_power(pp_name):
    pp = getattr(importlib.import_module('preprocessors.%s' % pp_name), pp_name)()
    p = AttrDict(units='MM', coords_decimals=4, fr_decimals=2, feedrate=1000, feedrate_rapid=1500,
                 steps_per_circle=64, obj_options={'type': 'Geometry', 'xmin': 0, 'xmax': 1, 'ymin': 0, 'ymax': 1},
                 pp_geometry_name=pp_name, spindledir='CW', laser_min_power=250)
    methods = (pp.start_code, pp.down_code) if pp_name == 'grbl_laser_eleks_drd' else \
        (pp.spindle_code, pp.down_code)

    for laser_on_code in ('M03', 'M04'):
        p['laser_on_code'] = laser_on_code
        for power in (500, 0, 0.0, None):
            p['spindlespeed'] = power
            for method in methods:
                lines = [line.split(';')[0] for line in method(p).splitlines()
                         if line.startswith(laser_on_code)]
                # A previous S500 (or minimum travel power) must not survive zero-power activation.
                assert lines == ['%s S%d' % (laser_on_code, power or 0)]

        expected_lift = 'M05;lift' if pp_name == 'grbl_laser_eleks_drd' else \
            '%s S250 (laser OFF)\n' % laser_on_code
        assert pp.lift_code(p) == expected_lift
        p['laser_min_power'] = 0
        assert pp.lift_code(p) == ('M05;lift' if pp_name == 'grbl_laser_eleks_drd' else 'M5')
        p['laser_min_power'] = 250


@pytest.mark.parametrize('min_power', [250, 0])
def test_milling_tool_job_warns_when_the_laser_off_lines_keep_the_laser_on(min_power):
    app, gcode = milling_tool_job('GRBL_laser', min_power)
    assert ('(laser OFF)' in gcode) is bool(min_power)
    assert len(laser_warnings(app)) == (1 if min_power else 0)


@pytest.mark.parametrize('pp_name', LASER_PREPROCESSORS)
def test_the_warning_follows_the_laser_off_lines_of_each_laser_preprocessor(pp_name):
    app, gcode = milling_tool_job(pp_name, 250)
    # grbl_laser_eleks_drd does not use Min Power: it always turns the laser off with M05
    assert ('laser OFF' in gcode) is (pp_name != 'grbl_laser_eleks_drd')
    assert len(laser_warnings(app)) == (1 if 'laser OFF' in gcode else 0)


@pytest.mark.parametrize('min_power', [250, 0])
def test_single_geometry_job_warns_when_the_laser_off_lines_keep_the_laser_on(min_power):
    app = laser_app()
    geo = Geometry(app)
    geo.solid_geometry = mill_paths()
    job = laser_job(app)
    gcode, __ = job.generate_from_geometry_2(geo, tooldia=0.1, tolerance=0.001, z_cut=0, z_move=2, feedrate=1000,
                                             feedrate_z=100, feedrate_rapid=1000, spindlespeed=500,
                                             laser_min_power=min_power, pp_geometry_name='GRBL_laser',
                                             is_first=True)
    assert ('(laser OFF)' in gcode) is bool(min_power)
    assert len(laser_warnings(app)) == (1 if min_power else 0)


@pytest.mark.parametrize('min_power', [250, 0])
def test_drilling_tool_job_warns_when_the_laser_off_lines_keep_the_laser_on(min_power):
    app = laser_app()
    source = make_excellon(app, slots=())
    job = laser_job(app, obj_type='Excellon', pp_excellon_name='GRBL_laser')
    data = dict(AppDefaults.factory_defaults)
    data.update(tools_drill_min_power=min_power, tools_drill_ppname_e='GRBL_laser')
    tools = {1: {'data': data, 'tooldia': 1.0, 'drills': source.tools[1]['drills']}}
    gcode, __, __ = job.excellon_tool_gcode_gen(1, source.tools[1]['drills'], tools, (0, 0), is_first=True,
                                                opt_type='R')
    assert ('(laser OFF)' in gcode) is bool(min_power)
    assert len(laser_warnings(app)) == (1 if min_power else 0)


@pytest.mark.parametrize('min_power', [250, 0])
def test_drillcncjob_tcl_command_warns_when_the_laser_off_lines_keep_the_laser_on(min_power):
    from tclCommands.TclCommandDrillcncjob import TclCommandDrillcncjob

    app = laser_app(tools_drill_toolchange=False)
    source = make_excellon(app, slots=())
    source.obj_options.update(app.options)
    source.obj_options.update(zip(('xmin', 'ymin', 'xmax', 'ymax'), source.bounds()))
    app.collection.get_by_name.return_value = source
    job = CNCjob(app)
    job.kind = 'cncjob'
    job.obj_options = {}
    job.excellon_tool_gcode_parse = Mock(return_value=[])

    def create(kind, name, init, **kwargs):
        assert init(job, app) != 'fail'
        return job

    app.app_obj.new_object.side_effect = create
    TclCommandDrillcncjob(app).execute({'name': 'e', 'pp': 'GRBL_laser', 'las_power': 500,
                                        'las_min_pwr': min_power}, [])
    assert ('(laser OFF)' in job.source_file) is bool(min_power)
    assert len(laser_warnings(app)) == (1 if min_power else 0)


def laser_warnings_per_tool(app):
    """The laser Min Power warnings, grouped by the tool whose G-code was being generated."""
    per_tool = []
    for c in app.inform.emit.call_args_list:
        msg = str(c.args[0]) if c.args else ''
        if msg.startswith('Starting G-Code for tool with diameter'):
            per_tool.append([])
        elif msg.startswith('[WARNING]') and 'laser OFF' in msg:
            per_tool[-1].append(msg)
    return per_tool


@pytest.mark.parametrize('first_min_power, second_min_power', [(250, 0), (0, 250)])
def test_multi_tool_single_geometry_job_warns_only_for_the_tool_that_keeps_the_laser_on(first_min_power,
                                                                                        second_min_power):
    # The Milling tool makes the G-code of a single geometry with 2 tools by calling generate_from_geometry_2() for
    # each tool on the same CNCjob, which appends to CNCjob.gcode: the 'laser OFF' lines of the first tool are still
    # there when the G-code of the second tool is checked.
    from appPlugins.ToolMilling import ToolMilling

    class Milling(SimpleNamespace):
        """The real ToolMilling methods, without its GUI."""
        def __getattr__(self, name):
            return getattr(ToolMilling, name).__get__(self, type(self))

    app = laser_app()
    tools = {}
    for uid, (tooldia, min_power) in enumerate(((0.1, first_min_power), (0.2, second_min_power)), 1):
        data = {key: value for key, value in AppDefaults.factory_defaults.items() if key.startswith('tools_mill_')}
        data.update(tools_mill_tooldia=tooldia, tools_mill_offset_type=0, tools_mill_optimization_type='R',
                    tools_mill_ppname_g='GRBL_laser', tools_mill_min_power=min_power, tools_mill_cutz=0,
                    tools_mill_spindlespeed=500, tools_mill_multidepth=False, tools_mill_toolchange=False)
        tools[uid] = {'tooldia': tooldia, 'data': data, 'solid_geometry': mill_paths()}
    geo = SimpleNamespace(multigeo=False, tools=tools, solid_geometry=mill_paths(),
                          obj_options=dict(tools[1]['data'], name='geo', xmin=0, ymin=0, xmax=7, ymax=0))
    jobs = []

    def new_object(kind, name, init, **kwargs):
        job = laser_job(app)
        job.kind, job.tools, job.gc_start = kind, {}, ''
        assert init(job, app) != 'fail'
        jobs.append(job)
        return job

    milling = Milling(app=app, units='MM', decimals=4, new_object=new_object)
    milling.generate_cnc_job_handler(geo_obj=geo, tools_dict=tools, use_thread=False, plot=False, from_tcl=True)

    assert len(jobs) == 1
    assert 'S250 (laser OFF)' in jobs[0].source_file
    warnings = laser_warnings_per_tool(app)
    assert [len(w) for w in warnings] == [1 if first_min_power else 0, 1 if second_min_power else 0]
    assert all('Laser Min Power is 250:' in m for w in warnings for m in w)
