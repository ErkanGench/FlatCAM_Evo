"""cncjob and drillcncjob (Tcl) with a laser preprocessor took the laser power only from -las_power and ignored
-spindlespeed, which is how scripts for older versions set it: the G-code had 'M03' without S. The tests make the real
G-code with the GRBL_laser preprocessor."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely import LineString

from appObjects.GeometryObject import GeometryObject
from camlib import CNCjob
from preprocessors.GRBL_laser import GRBL_laser
from preprocessors.default import default
from tclCommands.TclCommandCncjob import TclCommandCncjob
from tclCommands.TclCommandDrillcncjob import TclCommandDrillcncjob

from tests.helpers_objects import _headless_qt, make_app, make_excellon  # noqa: F401,E402


def laser_app():
    app = make_app()
    app.preprocessors = {'default': default(), 'GRBL_laser': GRBL_laser()}
    app.dec_format = lambda value, decimals: round(value, decimals)
    app.exc_areas = SimpleNamespace(exclusion_areas_storage=[],
                                    travel_coordinates=lambda **kw: [(None, kw['end_point'])])
    jobs = []

    def new_object(kind, name, initializer, **kwargs):
        job = CNCjob(app)
        job.kind, job.obj_options, job.tools = kind, {'name': name}, {}
        assert initializer(job, app) != 'fail'
        jobs.append(job)
        return job

    app.app_obj.new_object = Mock(side_effect=new_object)
    return app, jobs


def run(command_class, app, *argv):
    cmd = command_class(app)
    args, unnamed = cmd.check_args(('src',) + argv + ('-pp', 'GRBL_laser'))
    cmd.execute(args, unnamed)


def laser_on_lines(gcode):
    return {line for line in gcode.splitlines() if line.startswith('M03')}


def cncjob_gcode(*argv):
    app, jobs = laser_app()
    source = GeometryObject('src', app)
    source.solid_geometry = [LineString([(0, 0), (10, 0), (10, 10)])]
    source.multigeo = False
    source.obj_options.update(zip(('xmin', 'ymin', 'xmax', 'ymax'), source.bounds()))
    app.collection.get_by_name = Mock(return_value=source)
    run(TclCommandCncjob, app, '-dia', '0.1', '-z_cut', '0', '-feedrate', '1000', *argv)
    return jobs[0].source_file


def drillcncjob_gcode(*argv):
    app, jobs = laser_app()
    source = make_excellon(app, name='src')
    source.obj_options.update(zip(('xmin', 'ymin', 'xmax', 'ymax'), source.bounds()))
    app.collection.get_by_name = Mock(return_value=source)
    run(TclCommandDrillcncjob, app, '-drillz', '-1', '-travelz', '2', '-feedrate_z', '100', *argv)
    return jobs[0].source_file


@pytest.mark.parametrize('argv, expected', [
    (('-spindlespeed', '500'), {'M03 S500'}),
    (('-las_power', '300', '-spindlespeed', '500'), {'M03 S300'}),
    ((), {'M03 S0'}),
    (('-spindlespeed',), {'M03 S0'}),
], ids=['spindlespeed', 'las_power_first', 'no_power', 'bare_spindlespeed'])
def test_cncjob_laser_power(argv, expected):
    assert laser_on_lines(cncjob_gcode(*argv)) == expected


@pytest.mark.parametrize('argv, expected', [
    (('-spindlespeed', '500'), {'M03 S500.0'}),
    (('-las_power', '300', '-spindlespeed', '500'), {'M03 S300.0'}),
    ((), {'M03 S0'}),
], ids=['spindlespeed', 'las_power_first', 'no_power'])
def test_drillcncjob_laser_power(argv, expected):
    assert laser_on_lines(drillcncjob_gcode(*argv)) == expected


def test_cncjob_multigeo_laser_power_from_spindlespeed():
    source = Mock(kind='geometry', multigeo=True)
    source.tools = {7: {'data': {}, 'solid_geometry': [LineString([(0, 0), (1, 0)])]}}
    source.obj_options = {}
    app = make_app()
    app.collection.get_by_name = Mock(return_value=source)
    app.milling_tool = Mock()

    run(TclCommandCncjob, app, '-spindlespeed', '500')

    data = app.milling_tool.generate_cnc_job_handler.call_args.kwargs['tools_dict'][7]['data']
    assert data['tools_mill_spindlespeed'] == 500
