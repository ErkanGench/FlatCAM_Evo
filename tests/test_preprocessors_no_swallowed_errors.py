"""
A preprocessor that raises is not noticed by the user: CNCjob.doformat2() logs
"Exception occurred within a preprocessor" and returns '' for that part of the G-code. The Tcl command and the GUI go
on as if nothing had happened.

  * Line_xyz.start_code() read ``p['end_xy']``; the attribute of the job is ``xy_end`` (every other preprocessor reads
    that one). The whole start block was lost: no units (G21), no absolute mode (G90), no feed-rate mode (G94).
  * ISEL_ICP_CNC.toolchange_code() read ``p['obj_options']['Tools_in_use']`` for a drill job. Nothing sets that key and
    the value computed from it was never used. Every tool change of a drill job with tool change was lost (no GETTOOL).
  * Berta_CNC.start_code() tested the tool change position (``coords_xy``) before it printed the end position
    (``end_coords_xy``), as a typo of the check the other preprocessors make. With a tool change position and no end
    position it raised a TypeError.

These tests call the preprocessors through the real CNCjob.doformat2(), with the attributes of a generated job.
"""

import importlib
import pkgutil
from unittest.mock import Mock

import pytest

import appPreProcessor
import preprocessors
from camlib import CNCjob
from tests.helpers_objects import make_app_0b as make_app  # noqa: F401,E402

for _module in pkgutil.iter_modules(preprocessors.__path__):
    importlib.import_module('preprocessors.' + _module.name)

# the registry is module wide and other tests empty or reload it: keep the preprocessors of the collection time
PREPROCESSORS = dict(appPreProcessor.preprocessors)
# the solder paste preprocessors need the solder paste options of a solder paste job
GENERAL = sorted(name for name in PREPROCESSORS if not name.startswith('Paste_'))


def _job(kind, pp_name, toolchange_xy='1.0,2.0', end_xy=None):
    app = make_app()
    app.preprocessors = PREPROCESSORS
    app.log = Mock()
    job = CNCjob(app, units='MM', pp_geometry_name=pp_name, pp_excellon_name=pp_name)
    job.obj_options = {'name': 'job', 'type': kind, 'xmin': 0.0, 'ymin': 0.0, 'xmax': 10.0, 'ymax': 20.0,
                       'tool_dia': 0.2}
    # CNCJobObject sets these 2 on the job
    job.coords_decimals, job.fr_decimals = 4, 2
    job.feedrate_probe = 3.0
    job.xy_toolchange = [float(a) for a in toolchange_xy.split(',')]
    job.xy_end = end_xy
    job.z_cut, job.z_move, job.z_toolchange, job.z_end, job.startz = -1.7, 2.0, 15.0, 15.0, None
    job.multidepth, job.f_plunge, job.f_retract, job.toolchange = False, True, False, True
    job.tool, job.toolC, job.tooldia = 1, 0.8, 0.8
    job.spindlespeed, job.spindledir, job.dwell, job.dwelltime = 10000, 'CW', True, 1000
    job.exc_tools = {1: {'tooldia': 0.8, 'nr_drills': 3, 'data': {}}}
    job.tools = {1: {'tooldia': 0.8, 'nr_drills': 3, 'data': {}}}
    return app, job


def _exceptions(app):
    return [call for call in app.log.error.call_args_list
            if 'Exception occurred within a preprocessor' in str(call)]


@pytest.mark.parametrize('pp_name', GENERAL[::4])
def test_no_preprocessor_swallows_an_exception(pp_name):
    pp = PREPROCESSORS[pp_name]
    swallowed = []

    for kind in ('Geometry', 'Excellon'):
        # the factory default of the end position (Milling and Drilling preferences) is None
        for end_xy in (None, [0.0, 0.0]):
            for method in ('start_code', 'toolchange_code', 'end_code'):
                app, job = _job(kind, pp_name, end_xy=end_xy)
                job.doformat2(getattr(pp, method))
                if _exceptions(app):
                    swallowed.append((kind, end_xy, method, str(_exceptions(app)[0])[-300:]))

    assert swallowed == []


@pytest.mark.parametrize('end_xy', [None, [3.0, 4.0]])
def test_line_xyz_writes_its_start_block(end_xy):
    app, job = _job('Geometry', 'Line_xyz', end_xy=end_xy)

    code = job.doformat2(appPreProcessor.preprocessors['Line_xyz'].start_code)

    assert _exceptions(app) == []
    assert 'G21' in code and 'G90' in code and 'G94' in code
    if end_xy is None:
        assert '(X,Y End: None mm)' in code
    else:
        assert '(X,Y End: 3.0000, 4.0000 mm)' in code

