"""
The CNC job of the Milling plugin (and of the Tcl 'cncjob' command) reads the 'tools_mill_*' options from the tool
data. The tool data of a Geometry made by an older app version (e.g. in an older project) lacks the options added
later: 'tools_mill_laser_on' (2023-12) in an older FlatCAM Evo project. A FlatCAM 8.994 project has no 'tools_mill_*'
key: its tool data keeps the settings under older names ('cutz', 'feedrate'...) and the tool itself keeps 'tooldia',
'offset', 'offset_value', 'type' and 'tool_type'. The CNC job failed with a KeyError.

A missing option now gets, in this order: the value of its older name in the tool, the application value. A saved
preprocessor that was renamed gets its current name; one that the app does not have counts as absent. An older combo
box text gets its modern index; a text that is not recognized counts as absent.
"""
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6 import QtWidgets
from shapely import LineString

from appPlugins.ToolMilling import (ToolMilling, LEGACY_MILL_DATA_KEYS, LEGACY_MILL_DATA_TEXTS, LEGACY_MILL_TOOL_KEYS,
                                     legacy_mill_value)
from camlib import CNCjob
from defaults import AppDefaults
from preprocessors.GRBL_11 import GRBL_11
from preprocessors.GRBL_laser import GRBL_laser
from preprocessors.GRBL_laser_z import GRBL_laser_z
from preprocessors.Line_xyz import Line_xyz
from preprocessors.default import default
from test_unify_regressions_0b import make_app

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

MILL_OPTIONS = {k: v for k, v in AppDefaults.factory_defaults.items() if k.startswith('tools_mill_')}
# the options added in 2023-12: the tool data of a project saved before does not have them
ADDED_2023_12 = ('tools_mill_laser_on', 'tools_mill_z_p_depth')

# application options that differ from the settings saved in the FlatCAM 8.994 tools below
OTHER_OPTIONS = dict(tools_mill_cutz=-0.5, tools_mill_multidepth=False, tools_mill_depthperpass=0.3,
                     tools_mill_travelz=5.0, tools_mill_feedrate=300.0, tools_mill_feedrate_z=30.0,
                     tools_mill_ppname_g='GRBL_laser', tools_mill_spindlespeed=500, tools_mill_endz=25.0,
                     tools_mill_tooldia=2.4, tools_mill_offset_type=2, tools_mill_job_type=3, tools_mill_tool_shape=5,
                     tools_mill_laser_on='M4', tools_mill_min_power=7.0, tools_mill_toolchange=False)


class MillingHarness(SimpleNamespace):
    """Run the real controller methods without constructing its application GUI."""
    def __getattr__(self, name):
        method = getattr(ToolMilling, name)
        return method.__get__(self, type(self))


def evo_2023_tool_data():
    data = {k: deepcopy(v) for k, v in MILL_OPTIONS.items() if k not in ADDED_2023_12}
    data.update(tools_mill_tooldia=0.1, tools_mill_offset_type=0, tools_mill_job_type=0, tools_mill_cutz=-0.05,
                tools_mill_travelz=2.0, tools_mill_multidepth=False, tools_mill_toolchange=False,
                tools_mill_spindlespeed=800, tools_mill_optimization_type='R', tools_mill_ppname_g='GRBL_laser')
    # the probe depth had this name before 2023-12
    data['tools_mill_z_pdepth'] = -0.03
    return data


def flatcam_8_994_cutout_tool(**data_changes):
    """A tool of an Edge_Cuts cutout Geometry in a real FlatCAM 8.994 project: no 'tools_mill_*' key."""
    data = {'area_exclusion': False, 'area_overz': 1.0, 'area_shape': 'polygon', 'area_strategy': 'over',
            'cutz': -2.4, 'depthperpass': 1.2, 'dwell': False, 'dwelltime': 1.0, 'endxy': None, 'endz': 15.0,
            'extracut': False, 'extracut_length': 0.1, 'feedrate': 120.0, 'feedrate_rapid': 500.0, 'feedrate_z': 60.0,
            'multidepth': True, 'name': 'board-Edge_Cuts.gbr_cutout', 'optimization_type': 'R', 'plot': True,
            'ppname_g': 'default', 'spindledir': 'CW', 'spindlespeed': 0, 'startz': None, 'toolchange': False,
            'toolchangexy': [0.0, 0.0], 'toolchangez': 15.0, 'tools_cutout_tooldia': 2.4, 'tools_cutout_z': -1.8,
            'travelz': 2.0, 'vtipangle': 30.0, 'vtipdia': 0.1}
    data.update(data_changes)
    return {'offset': 'Path', 'offset_value': 0.0, 'tool_type': 'C1', 'tooldia': '1.75', 'type': 'Rough', 'data': data}


def flatcam_8_994_laser_tool():
    """A tool of an isolation Geometry in a real FlatCAM 8.994 project, for a laser: the power is its spindlespeed."""
    data = {'area_exclusion': False, 'area_overz': 1.0, 'area_shape': 'polygon', 'area_strategy': 'over',
            'cutz': 0.0, 'depthperpass': 0.8, 'dwell': False, 'dwelltime': 1.0, 'endxy': None, 'endz': 20.0,
            'extracut': False, 'extracut_length': 0.1, 'feedrate': 1000.0, 'feedrate_rapid': 500.0,
            'feedrate_z': 60.0, 'multidepth': False, 'name': 'board-F_Cu.gbr_iso_combined', 'optimization_type': 'R',
            'plot': True, 'polish': False, 'ppname_g': 'GRBL_laser', 'search_time': 3, 'spindledir': 'CW',
            'spindlespeed': 1000, 'startz': None, 'toolchange': False, 'toolchangexy': [0.0, 0.0],
            'toolchangez': 15.0, 'tools_iso_passes': 6, 'tools_iso_overlap': 30.0, 'travelz': 2.0, 'vtipangle': 30.0,
            'vtipdia': 0.1}
    return {'offset': 'Path', 'offset_value': 0.0, 'tool_type': 'V', 'tooldia': 0.1, 'type': 'Iso', 'data': data}


def milling_harness(tool, multigeo, **options):
    app = make_app(**options)
    # a plain dict, as in the app: a preprocessor name that it does not have raises a KeyError
    app.preprocessors = {'default': default(), 'GRBL_laser': GRBL_laser(), 'GRBL_11': GRBL_11(),
                         'Line_xyz': Line_xyz(), 'GRBL_laser_z': GRBL_laser_z()}
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.exc_areas = SimpleNamespace(travel_coordinates=lambda **kw: [(None, kw['end_point'])])

    geometry = [LineString([(0, 0), (10, 0)]), LineString([(0, 5), (10, 5)])]
    tools = {1: dict(tool, solid_geometry=geometry)}
    obj_options = dict(MILL_OPTIONS, name='old_geo', xmin=0, ymin=0, xmax=10, ymax=5)
    source = SimpleNamespace(multigeo=multigeo, tools=tools, solid_geometry=geometry, obj_options=obj_options)
    jobs = []

    def new_object(kind, name, initializer, **kwargs):
        job = CNCjob(app, pp_geometry_name='GRBL_laser')
        job.kind, job.obj_options, job.tools, job.gc_start = kind, {'name': name}, {}, ''
        if initializer(job, app) == 'fail':
            return 'fail'
        jobs.append(job)
        return job

    milling = MillingHarness(app=app, target_obj=source, sel_tools=tools, units='MM', decimals=4, circle_steps=16,
                             new_object=new_object)
    return milling, jobs


def make_cnc_job(tool, multigeo, **options):
    milling, jobs = milling_harness(tool, multigeo, **options)
    # the Tcl 'cncjob' command calls it like this
    result = milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)
    assert result is None and len(jobs) == 1
    return jobs[0].source_file, milling


@pytest.mark.parametrize('multigeo', [False, True])
def test_cnc_job_from_tool_data_without_the_laser_on_option(multigeo):
    data = evo_2023_tool_data()

    gcode, _milling = make_cnc_job({'tooldia': 0.1, 'data': data}, multigeo, tools_mill_laser_on='M4')

    # the laser is turned on with the code of the application options and the power of the tool data
    assert 'M4 S800' in gcode
    assert data['tools_mill_laser_on'] == 'M4'
    # the probe depth comes from its older name
    assert data['tools_mill_z_p_depth'] == -0.03
    # the options in the tool data are kept
    assert data['tools_mill_cutz'] == -0.05 and data['tools_mill_spindlespeed'] == 800


@pytest.mark.parametrize('multigeo', [False, True])
def test_cnc_job_from_flatcam_8_994_tool_data(multigeo):
    tool = flatcam_8_994_laser_tool()
    data = tool['data']

    gcode, _milling = make_cnc_job(tool, multigeo, **dict(OTHER_OPTIONS, tools_mill_ppname_g='default'))

    # the saved laser preprocessor and laser power; 8.994 has no setting for the laser ON code: application value
    assert 'M4 S1000' in gcode and 'S500' not in gcode
    assert data['tools_mill_ppname_g'] == 'GRBL_laser' and data['tools_mill_laser_on'] == 'M4'
    # the tool diameter comes from the tool, not from the application option
    assert data['tools_mill_tooldia'] == 0.1 != OTHER_OPTIONS['tools_mill_tooldia']
    assert data['tools_mill_job_type'] == 2 and data['tools_mill_tool_shape'] == 5   # 'Iso', 'V'
    assert all(k in data for k in MILL_OPTIONS)
    # the older keys stay in the tool data
    assert data['cutz'] == 0.0 and data['name'] == 'board-F_Cu.gbr_iso_combined'


@pytest.mark.parametrize('multigeo', [False, True])
def test_cnc_job_uses_the_saved_flatcam_8_994_settings(multigeo):
    tool = flatcam_8_994_cutout_tool()

    gcode, _milling = make_cnc_job(tool, multigeo, **OTHER_OPTIONS)

    # the saved preprocessor (the application option is a laser preprocessor), depth, passes and feed rates
    assert 'M4' not in gcode and 'G00 Z2.0000' in gcode
    assert 'G01 Z-1.2000' in gcode and 'G01 Z-2.4000' in gcode
    assert 'G01 F120.00' in gcode and 'G01 F60.00' in gcode
    # nothing of the application options
    for value in ('Z-0.5000', 'Z-0.3000', 'Z5.0000', 'F300.00', 'F30.00', 'Z25.0000'):
        assert value not in gcode
    data = tool['data']
    assert (data['tools_mill_cutz'], data['tools_mill_feedrate'], data['tools_mill_multidepth']) == (-2.4, 120.0, True)
    # the settings of the tool itself: 'Path', 'Rough', 'C1' and its diameter
    assert (data['tools_mill_offset_type'], data['tools_mill_job_type'], data['tools_mill_tool_shape']) == (0, 0, 0)
    assert data['tools_mill_tooldia'] == '1.75' and data['tools_mill_offset_value'] == 0.0


@pytest.mark.parametrize('multigeo', [False, True])
def test_modern_key_wins_over_its_older_name(multigeo):
    # a key with both names: the modern one is used, also when its value is falsy
    tool = flatcam_8_994_cutout_tool(tools_mill_cutz=-0.1, tools_mill_multidepth=False, tools_mill_feedrate=200.0,
                                     spindlespeed=12000, tools_mill_spindlespeed=0, tools_mill_offset_type=0)
    tool['offset'] = 'Out'

    gcode, _milling = make_cnc_job(tool, multigeo, **OTHER_OPTIONS)

    assert 'G01 Z-0.1000' in gcode and 'G01 F200.00' in gcode
    assert 'Z-1.2000' not in gcode and 'Z-2.4000' not in gcode and 'F120.00' not in gcode
    assert 'S12000' not in gcode
    data = tool['data']
    assert data['tools_mill_multidepth'] is False and data['tools_mill_spindlespeed'] == 0
    assert data['tools_mill_offset_type'] == 0


@pytest.mark.parametrize('multigeo', [False, True])
def test_application_value_only_for_absent_settings(multigeo):
    tool = flatcam_8_994_cutout_tool()

    make_cnc_job(tool, multigeo, **dict(OTHER_OPTIONS, tools_mill_polish=True))

    data = tool['data']
    # no older name in this tool: the application value
    assert data['tools_mill_laser_on'] == 'M4' and data['tools_mill_min_power'] == 7.0
    assert data['tools_mill_polish'] is True
    # an older name in this tool: its value, not the application value (here: Roughing, not Polishing)
    assert data['tools_mill_job_type'] == 0 and data['tools_mill_offset_type'] == 0
    assert data['tools_mill_endz'] == 15.0 and data['tools_mill_ppname_g'] == 'default'


def make_cnc_job_with_preprocessor(tool, multigeo, **options):
    """The CNC job, its G-code and the warnings that name the preprocessor saved in the tool."""
    saved = tool['data']['ppname_g']
    milling, jobs = milling_harness(tool, multigeo, **options)
    milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)
    assert len(jobs) == 1
    warnings = [c.args[0] for c in milling.app.inform.emit.call_args_list if saved in str(c.args[0])]
    return jobs[0], milling.app.preprocessors, warnings


@pytest.mark.parametrize('multigeo', [False, True])
@pytest.mark.parametrize('saved, current', [('grbl_11', 'GRBL_11'), ('line_xyz', 'Line_xyz'),
                                            ('Z_laser', 'GRBL_laser_z')])
def test_renamed_flatcam_8_994_preprocessor(saved, current, multigeo):
    # FlatCAM 8.994 had these preprocessors under another name
    tool = flatcam_8_994_laser_tool() if current == 'GRBL_laser_z' else flatcam_8_994_cutout_tool()
    tool['data']['ppname_g'] = saved

    job, preprocessors, warnings = make_cnc_job_with_preprocessor(
        tool, multigeo, **dict(OTHER_OPTIONS, tools_mill_ppname_g='default'))

    assert tool['data']['tools_mill_ppname_g'] == current
    assert job.pp_geometry_name == current and job.pp_geometry is preprocessors[current]
    assert not warnings


@pytest.mark.parametrize('multigeo', [False, True])
def test_unavailable_saved_preprocessor_gets_the_application_one(multigeo):
    # deleted after 8.994 (524b45617); a user preprocessor that is not installed is the same
    tool = flatcam_8_994_cutout_tool(ppname_g='Toolchange_Custom')

    job, preprocessors, warnings = make_cnc_job_with_preprocessor(
        tool, multigeo, **dict(OTHER_OPTIONS, tools_mill_ppname_g='GRBL_11'))

    assert tool['data']['tools_mill_ppname_g'] == 'GRBL_11'
    assert job.pp_geometry_name == 'GRBL_11' and job.pp_geometry is preprocessors['GRBL_11']
    # the other saved settings are kept
    gcode = job.source_file
    assert 'G01 Z-1.2000' in gcode and 'G01 Z-2.4000' in gcode and 'F120.00' in gcode
    assert len(warnings) == 1 and warnings[0].startswith('[WARNING_NOTCL]')


def test_older_tool_values_are_converted():
    tool = {'offset': 'Out', 'type': '           Iso', 'tool_type': 'V', 'data': {}}
    assert legacy_mill_value(tool, 'tools_mill_offset_type') == (True, 2)
    # FlatCAM 8.994 saved some job types with leading spaces
    assert legacy_mill_value(tool, 'tools_mill_job_type') == (True, 2)
    assert legacy_mill_value(tool, 'tools_mill_tool_shape') == (True, 5)
    # an older value that is not recognized is not used
    assert legacy_mill_value({'offset': 'Sideways', 'data': {}}, 'tools_mill_offset_type') == (False, None)
    assert legacy_mill_value({'data': {}}, 'tools_mill_cutz') == (False, None)
    # a job type saved by 8.994 in another language (here Turkish 'Rough'); an 8.994 'Polish' tool already holds the
    # painted paths, so it is not a Polishing job (that paints the area again)
    assert legacy_mill_value({'type': 'Kaba', 'data': {}}, 'tools_mill_job_type') == (False, None)
    assert legacy_mill_value({'type': 'Polish', 'data': {}}, 'tools_mill_job_type') == (False, None)
    # a valid falsy older value is used
    assert legacy_mill_value({'data': {'spindlespeed': 0}}, 'tools_mill_spindlespeed') == (True, 0)


@pytest.mark.parametrize('saved, app_value, expected', [
    ('Standard', 2, 0), ('Seed', 2, 1), ('lines', 0, 2), (0, 2, 0), (2, 0, 2),
    # not recognized, so the application value: a text of 8.994 in Spanish, an index that does not exist, a bool
    ('Semilla', 2, 2), (7, 1, 1), (True, 2, 2)])
def test_saved_polish_method(saved, app_value, expected):
    # the FlatCAM 8.994 release saved the text of the polish method combo box, its later builds the index
    tool = flatcam_8_994_cutout_tool(polish_method=saved)

    gcode, _milling = make_cnc_job(tool, True, **dict(OTHER_OPTIONS, tools_mill_polish_method=app_value))

    assert tool['data']['tools_mill_polish_method'] == expected
    assert type(tool['data']['tools_mill_polish_method']) is int
    # the other saved settings are kept
    assert 'G01 Z-2.4000' in gcode and 'G01 F120.00' in gcode


def test_older_names_are_application_options():
    for key in list(LEGACY_MILL_DATA_KEYS) + list(LEGACY_MILL_TOOL_KEYS):
        assert key in MILL_OPTIONS, key
    older = [name for names in LEGACY_MILL_DATA_KEYS.values() for name in names]
    assert len(older) == len(set(older))
    # the older texts are converted for an older name of the tool data
    assert set(LEGACY_MILL_DATA_TEXTS) <= set(LEGACY_MILL_DATA_KEYS)


def test_values_from_the_application_options_are_copies():
    data = evo_2023_tool_data()
    del data['tools_mill_toolchangexy']
    milling, jobs = milling_harness({'tooldia': 0.1, 'data': data}, True, tools_mill_toolchangexy=[1.0, 2.0])

    milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)

    assert data['tools_mill_toolchangexy'] == [1.0, 2.0]
    assert data['tools_mill_toolchangexy'] is not milling.app.options['tools_mill_toolchangexy']


def test_values_from_older_names_are_copies():
    tool = flatcam_8_994_cutout_tool(endxy=[3.0, 4.0])

    make_cnc_job(tool, True, **OTHER_OPTIONS)

    data = tool['data']
    assert data['tools_mill_toolchangexy'] == [0.0, 0.0] and data['tools_mill_endxy'] == [3.0, 4.0]
    assert data['tools_mill_toolchangexy'] is not data['toolchangexy']
    assert data['tools_mill_endxy'] is not data['endxy']
