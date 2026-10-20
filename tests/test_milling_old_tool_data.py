"""
The CNC job of the Milling plugin (and of the Tcl 'cncjob' command) reads the 'tools_mill_*' options from the tool
data. The tool data of a Geometry made by an older app version (e.g. in an older project) lacks the options added
later: 'tools_mill_laser_on' (2023-12) in an older FlatCAM Evo project, all of them in a FlatCAM 8.994 project. The
CNC job failed with a KeyError. The missing options now get the application value.
"""
import os
from copy import deepcopy
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6 import QtWidgets
from shapely import LineString

from appPlugins.ToolMilling import ToolMilling
from camlib import CNCjob
from defaults import AppDefaults
from preprocessors.GRBL_laser import GRBL_laser
from test_unify_regressions_0b import make_app

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

MILL_OPTIONS = {k: v for k, v in AppDefaults.factory_defaults.items() if k.startswith('tools_mill_')}
# the options added in 2023-12: the tool data of a project saved before does not have them
ADDED_2023_12 = ('tools_mill_laser_on', 'tools_mill_z_p_depth')


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
    return data


def flatcam_8_994_tool_data():
    # the keys of the tool data of a Geometry in a FlatCAM 8.994 project: no 'tools_mill_*' key
    return {'name': 'old_iso', 'plot': True, 'tooldia': 0.1, 'cutz': -0.05, 'travelz': 2.0, 'feedrate': 120.0,
            'spindlespeed': 800, 'ppname_g': 'GRBL_laser', 'tools_iso_passes': 1, 'tools_iso_overlap': 10}


def milling_harness(tool_data, multigeo, **options):
    app = make_app(**options)
    app.preprocessors['GRBL_laser'] = GRBL_laser()
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.exc_areas = SimpleNamespace(travel_coordinates=lambda **kw: [(None, kw['end_point'])])

    geometry = [LineString([(0, 0), (10, 0)]), LineString([(0, 5), (10, 5)])]
    tools = {1: {'tooldia': 0.1, 'data': tool_data, 'solid_geometry': geometry}}
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


@pytest.mark.parametrize('multigeo', [False, True])
def test_cnc_job_from_tool_data_without_the_laser_on_option(multigeo):
    data = evo_2023_tool_data()
    milling, jobs = milling_harness(data, multigeo, tools_mill_laser_on='M4')

    # the Tcl 'cncjob' command calls it like this
    result = milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)

    assert result is None and len(jobs) == 1
    # the laser is turned on with the code of the application options and the power of the tool data
    assert 'M4 S800' in jobs[0].source_file
    assert data['tools_mill_laser_on'] == 'M4'
    assert data['tools_mill_z_p_depth'] == MILL_OPTIONS['tools_mill_z_p_depth']
    # the options in the tool data are kept
    assert data['tools_mill_cutz'] == -0.05 and data['tools_mill_spindlespeed'] == 800


@pytest.mark.parametrize('multigeo', [False, True])
def test_cnc_job_from_flatcam_8_994_tool_data(multigeo):
    data = flatcam_8_994_tool_data()
    milling, jobs = milling_harness(data, multigeo, tools_mill_ppname_g='GRBL_laser', tools_mill_laser_on='M4',
                                    tools_mill_spindlespeed=500, tools_mill_offset_type=0, tools_mill_toolchange=False)

    result = milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)

    assert result is None and len(jobs) == 1
    assert 'M4 S500' in jobs[0].source_file
    # the tool diameter comes from the tool, not from the application option
    assert data['tools_mill_tooldia'] == 0.1 != MILL_OPTIONS['tools_mill_tooldia']
    assert all(k in data for k in MILL_OPTIONS)
    assert data['cutz'] == -0.05 and data['name'] == 'old_iso'


def test_values_from_the_application_options_are_copies():
    data = evo_2023_tool_data()
    del data['tools_mill_toolchangexy']
    milling, jobs = milling_harness(data, True, tools_mill_toolchangexy=[1.0, 2.0])

    milling.generate_cnc_job_handler(toolchange=False, plot=False, use_thread=False, from_tcl=True)

    assert data['tools_mill_toolchangexy'] == [1.0, 2.0]
    assert data['tools_mill_toolchangexy'] is not milling.app.options['tools_mill_toolchangexy']
