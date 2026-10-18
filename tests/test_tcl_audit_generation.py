"""Headless command-generation regressions, including factory failure contracts."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from shapely import box

from defaults import AppDefaults
from tclCommands.TclCommandAlignDrill import TclCommandAlignDrill
from tclCommands.TclCommandAlignDrillGrid import TclCommandAlignDrillGrid
from tclCommands.TclCommandBbox import TclCommandBbox
from tclCommands.TclCommandNregions import TclCommandNregions
from tclCommands.TclCommandCncjob import TclCommandCncjob
from tclCommands.TclCommandOpenSVG import TclCommandOpenSVG
from tclCommands.TclCommandOpenDXF import TclCommandOpenDXF
from tclCommands.TclCommandImportSvg import TclCommandImportSvg
from tclCommands.TclCommandSplitGeometry import TclCommandSplitGeometry
from test_tcl_audit_regressions import object_app, FCShell


def factory_app(obj):
    app = object_app(obj)
    app.app_obj = Mock()
    app.options.update(AppDefaults.factory_defaults)
    app.app_units = 'MM'
    app.plotcanvas = Mock()
    app.proc_container = Mock()
    app.proc_container.new.side_effect = lambda *args: nullcontext()
    app.file_opened = Mock()
    return app


@pytest.mark.parametrize('cls,key', [(TclCommandBbox, 'gerber_bboxrounded'),
                                    (TclCommandNregions, 'gerber_noncopperrounded')])
def test_boolean_defaults_work_headlessly_without_toggling_source(cls, key):
    source = SimpleNamespace(kind='geometry', solid_geometry=[box(0, 0, 3, 2)],
                             bounds=lambda: (0, 0, 3, 2))
    app = factory_app(source)
    app.options[key] = False
    output = SimpleNamespace(kind='geometry')
    app.app_obj.new_object.side_effect = lambda kind, name, init, **kw: init(output, app)
    cls(app).execute({'name': 'g'}, [])
    assert output.solid_geometry.area > 0


@pytest.mark.parametrize('key,value', [('rows', 0), ('columns', -1), ('gridx', 0), ('dia', -1)])
def test_alignment_grid_rejects_invalid_domains(key, value):
    app = factory_app(None)
    args = dict(rows=2, columns=2, gridx=1, gridy=1, dia=0.8)
    args[key] = value
    with pytest.raises(FCShell.TclErrorException):
        TclCommandAlignDrillGrid(app).execute(args, [])
    app.app_obj.new_object.assert_not_called()


def test_alignment_drills_install_tools_before_geometry_creation():
    from appParsers.ParseExcellon import Excellon
    source = SimpleNamespace(kind='geometry', bounds=lambda: (10, 10, 20, 20))
    app = factory_app(source)
    app.decimals = 4
    app.abort_flag = False
    app.dec_format = lambda value, decimals: round(value, decimals)
    output = Excellon(app)
    output.regenerate_source = Mock()

    def create(kind, name, init, **kwargs):
        assert init(output, app) != 'fail'
        return output

    app.app_obj.new_object.side_effect = create
    TclCommandAlignDrill(app).execute({'name': 'g', 'axis': 'X', 'dia': 1,
                                       'holes': '(1,2),(3,4)', 'dist': 0}, [])
    assert len(output.tools[1]['drills']) == 4
    assert len(output.solid_geometry) == 4


def test_cncjob_zero_heights_bare_dwell_and_segment_y_are_preserved():
    obj = Mock(kind='geometry', multigeo=True)
    obj.tools = {7: {'data': {}, 'solid_geometry': [box(0, 0, 1, 1)]}}
    obj.obj_options = {}
    app = factory_app(obj)
    app.options.update(geometry_seg_x=1, geometry_seg_y=2, tools_mill_startz=9, tools_mill_endz=9)
    app.milling_tool = Mock()
    TclCommandCncjob(app).execute({'name': 'g', 'startz': 0, 'endz': 0, 'dwelltime': None}, [])
    data = app.milling_tool.generate_cnc_job_handler.call_args.kwargs['tools_dict'][7]['data']
    assert data['tools_mill_startz'] == data['tools_mill_endz'] == 0
    assert data['seg_y'] == 2
    assert data['tools_mill_dwelltime'] == app.options['tools_mill_dwelltime']


@pytest.mark.parametrize('cls,method,extra', [(TclCommandOpenSVG, 'import_svg', {}),
                                            (TclCommandImportSvg, 'import_svg', {}),
                                            (TclCommandOpenDXF, 'import_dxf_as_geo', {})])
def test_import_failure_is_returned_to_factory_and_never_announced(cls, method, extra):
    app = factory_app(None)
    from camlib import Geometry
    geo = Mock(spec=Geometry)
    getattr(geo, method).return_value = 'fail'
    results = []

    def create(kind, name, init, **kwargs):
        results.append(init(geo, app))
        return 'fail'

    app.app_obj.new_object.side_effect = create
    command = cls(app)
    result = command.execute({'filename': 'drawing.svg', 'outname': 'custom', **extra}, [])
    assert result == 'fail'
    assert results and all(r == 'fail' for r in results)
    app.file_opened.emit.assert_not_called()


def test_split_geometry_populates_root_and_only_the_selected_tool():
    obj = SimpleNamespace(kind='geometry', tools={7: {'solid_geometry': [box(0, 0, 1, 1)]}})
    app = factory_app(obj)
    output = SimpleNamespace(tools={1: {'solid_geometry': []}})
    app.app_obj.new_object.side_effect = lambda kind, name, init, **kw: init(output, app)
    TclCommandSplitGeometry(app).execute({'source_name': 'g'}, [])
    assert list(output.tools) == [7]
    assert output.solid_geometry[0].equals(obj.tools[7]['solid_geometry'][0])


def test_single_geometry_generation_does_not_replace_zero_or_false_with_defaults():
    from appObjects.GeometryObject import GeometryObject
    app = factory_app(None)
    options = dict(app.options)
    options.update(name='g', xmin=0, ymin=0, xmax=1, ymax=1)
    source = SimpleNamespace(app=app, obj_options=options, _app_option=app.options.get)
    job = Mock(kind='cncjob', obj_options={})
    job.generate_from_geometry_2.return_value = ('body', 'start')

    def create(kind, name, init, **kwargs):
        return init(job, app)

    app.app_obj.new_object.side_effect = create
    GeometryObject.generatecncjob(source, dia=1, toolchangez=0, toolchange=False,
                                  spindlespeed=0, las_min_pwr=0, dwell=False, dwelltime=0, use_thread=False)
    kwargs = job.generate_from_geometry_2.call_args.kwargs
    assert kwargs['toolchangez'] == kwargs['spindlespeed'] == kwargs['laser_min_power'] == kwargs['dwelltime'] == 0
    assert kwargs['toolchange'] is kwargs['dwell'] is False
