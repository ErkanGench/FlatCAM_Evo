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

from camlib import CNCjob, Geometry
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
