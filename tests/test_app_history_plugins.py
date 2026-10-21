"""App Undo / Redo history on the in-place changes of the plugins and of the object handlers (headless App)."""

import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6 import QtWidgets
from shapely import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import appHandlers.appHistory as appHistory
from appMain import App
from appObjects.AppObjectTemplate import FlatCAMObj
from appObjects.ExcellonObject import ExcellonObject
from appPlugins.ToolCutOut import CutOut
from appPlugins.ToolDblSided import DblSidedTool
from appPlugins.ToolIsolation import ToolIsolation
from appPlugins.ToolQRCode import QRCode

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'unify')

pytestmark = pytest.mark.slow


@pytest.fixture(scope='module')
def fc():
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app = App(qapp=qapp, headless=True)
    # the history records nothing in headless mode; these tests need it
    appHistory.RECORD_IN_HEADLESS = True
    yield app
    appHistory.RECORD_IN_HEADLESS = False


@pytest.fixture
def no_plot(monkeypatch):
    monkeypatch.setattr(FlatCAMObj, 'plot', lambda *a, **k: None)
    monkeypatch.setattr(FlatCAMObj, 'plot_transformed', lambda *a, **k: True)
    monkeypatch.setattr(ExcellonObject, 'plot_transformed', lambda *a, **k: True)
    for _ in range(20):
        QtWidgets.QApplication.processEvents()


def _load(fc, kind, filename, name):
    def init(obj, _app):
        obj.parse_file(os.path.join(FIX, filename))
        if kind == 'excellon':
            obj.create_geometry()
    return fc.app_obj.new_object(kind, name, init, plot=False)


def _settle(fc, timeout=5.0):
    end = time.time() + timeout
    while fc.projects.is_busy() and time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


def _bounds(obj):
    return np.array(obj.bounds())


def _area(obj):
    geo = obj.solid_geometry
    return unary_union(geo if isinstance(geo, list) else [geo]).area


def _geometry(fc, name, multigeo=False):
    """A Geometry object with a closed contour (a 20 x 10 rectangle) and 1 tool."""
    contour = LineString(list(box(0, 0, 20, 10).exterior.coords))

    def init(obj, _app):
        obj.solid_geometry = [contour]
        obj.tools = {1: {'tooldia': 1.0, 'data': {'name': name}, 'solid_geometry': [contour] if multigeo else []}}
        obj.multigeo = multigeo
    return fc.app_obj.new_object('geometry', name, init, plot=False)


def _one_step(fc, before, label_part):
    """The history got exactly 1 new step since `before` (the undo stack length), with `label_part` in its label."""
    assert len(fc.history.undo_stack) == before + 1
    assert label_part in fc.history.undo_label()


def _stack(fc):
    return len(fc.history.undo_stack)


# ---------------------------------------------------------------------------------------------------------------------
# 1. Double-Sided: Mirror
# ---------------------------------------------------------------------------------------------------------------------
def test_dblsided_mirror_is_a_matrix_step(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_dbl')
    b0 = _bounds(grb)
    app = SimpleNamespace(
        history=fc.history,
        collection=SimpleNamespace(index=lambda *a: SimpleNamespace(internalPointer=lambda: SimpleNamespace(obj=grb))),
        app_obj=SimpleNamespace(object_changed=SimpleNamespace(emit=lambda o: None)),
        inform=SimpleNamespace(emit=lambda *a: None))
    ui = SimpleNamespace(
        object_combo=SimpleNamespace(currentIndex=lambda: 0, rootModelIndex=lambda: None),
        mirror_axis=SimpleNamespace(get_value=lambda: 'X'),
        axis_location=SimpleNamespace(get_value=lambda: 'point'),
        point_entry=SimpleNamespace(get_value=lambda: (3.0, 4.0)))
    stub = SimpleNamespace(app=app, ui=ui)
    n = _stack(fc)
    DblSidedTool.on_mirror(stub)
    _one_step(fc, n, 'Mirror')
    b1 = _bounds(grb)
    assert not np.allclose(b1, b0)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)
    assert fc.history.redo() and np.allclose(_bounds(grb), b1)


# ---------------------------------------------------------------------------------------------------------------------
# 2. QRCode: make() writes the existing Gerber
# ---------------------------------------------------------------------------------------------------------------------
def test_qrcode_make_is_a_snapshot_step(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_qr')
    area0, tools0, b0 = _area(grb), sorted(grb.tools, key=str), _bounds(grb)
    qr_geo = MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)])
    ui = SimpleNamespace(
        border_size_entry=SimpleNamespace(get_value=lambda: 1.0),
        bsize_entry=SimpleNamespace(get_value=lambda: 10.0),
        bb_radio=SimpleNamespace(get_value=lambda: 'r'),
        pol_radio=SimpleNamespace(get_value=lambda: 'pos'))
    stub = SimpleNamespace(app=fc, ui=ui, grb_object=grb, qrcode_utility_geometry=qr_geo, qrcode_geometry=qr_geo,
                           on_exit=lambda: None, replot=lambda obj=None: None)
    stub._write_qrcode = lambda pos: QRCode._write_qrcode(stub, pos)
    n = _stack(fc)
    QRCode.make(stub, (50.0, 50.0))
    _one_step(fc, n, 'QRCode')
    area1, tools1 = _area(grb), sorted(grb.tools, key=str)
    assert len(tools1) == len(tools0) + 1 and area1 != area0 and not np.allclose(_bounds(grb), b0)
    assert fc.history.undo()
    assert sorted(grb.tools, key=str) == tools0 and np.isclose(_area(grb), area0) and np.allclose(_bounds(grb), b0)
    assert fc.history.redo()
    assert sorted(grb.tools, key=str) == tools1 and np.isclose(_area(grb), area1)


# ---------------------------------------------------------------------------------------------------------------------
# 3. Cutout: manual gap, 1 step per click
# ---------------------------------------------------------------------------------------------------------------------
def _cutout_stub(fc, geo):
    ui = SimpleNamespace(
        dia=SimpleNamespace(get_value=lambda: 2.0),
        gapsize=SimpleNamespace(get_value=lambda: 1.0),
        gaptype_combo=SimpleNamespace(get_value=lambda: 1),          # thin gaps -> tool 99
        cutz_entry=SimpleNamespace(get_value=lambda: -1.0),
        thin_depth_entry=SimpleNamespace(get_value=lambda: -0.5),
        mpass_cb=SimpleNamespace(get_value=lambda: False),
        maxdepth_entry=SimpleNamespace(get_value=lambda: 0.5))
    fc.geo_editor = SimpleNamespace(snap=lambda x, y: (x, y))
    tool_dict = {'tooldia': 1.0, 'data': {}, 'solid_geometry': []}
    stub = SimpleNamespace(app=fc, ui=ui, man_cutout_obj=geo, cut_tool_dict=tool_dict, mb_manual_solid_geo=None,
                           mb_manual_cuts=[])
    return CutOut, stub


def test_manual_cutout_click_is_a_snapshot_step(fc, no_plot):
    geo = _geometry(fc, 'geo_cut')
    geo.plot = lambda *a, **k: None
    CutOut, stub = _cutout_stub(fc, geo)
    keys0 = sorted(geo.tools)
    n = _stack(fc)
    CutOut.on_manual_cutout(stub, (10.0, 0.0))
    _one_step(fc, n, 'Manual Cutout')
    assert geo.multigeo is True and 99 in geo.tools
    solid1 = geo.tools[1]['solid_geometry']
    assert fc.history.undo()
    assert geo.multigeo is False and sorted(geo.tools) == keys0 and geo.tools[1]['solid_geometry'] == []
    assert fc.history.redo()
    assert geo.multigeo is True and 99 in geo.tools
    assert geo.tools[1]['solid_geometry'].equals(solid1) if hasattr(solid1, 'equals') else True


def test_manual_cutout_that_fails_records_nothing(fc, no_plot):
    geo = _geometry(fc, 'geo_cut_fail')
    CutOut, stub = _cutout_stub(fc, geo)
    stub.ui.dia = SimpleNamespace(get_value=lambda: 0.0)         # a diameter of 0 is refused before any change
    n = _stack(fc)
    CutOut.on_manual_cutout(stub, (10.0, 0.0))
    assert _stack(fc) == n


# ---------------------------------------------------------------------------------------------------------------------
# 4 / 5. Single-geo <-> Multi-geo
# ---------------------------------------------------------------------------------------------------------------------
def test_convert_single_to_multi_and_back(fc, no_plot, monkeypatch):
    geo = _geometry(fc, 'geo_conv')
    geo.plot = lambda *a, **k: None
    monkeypatch.setattr(fc.collection, 'get_active', lambda: geo)
    n = _stack(fc)
    fc.edit_class.on_convert_singlegeo_to_multigeo()
    _one_step(fc, n, 'MultiGeo')
    assert geo.multigeo is True and geo.tools[1]['solid_geometry']
    n = _stack(fc)
    fc.edit_class.on_convert_multigeo_to_singlegeo()
    _one_step(fc, n, 'SingleGeo')
    assert geo.multigeo is False and geo.tools[1]['solid_geometry'] == []
    assert fc.history.undo()                                # back to multigeo
    assert geo.multigeo is True and geo.tools[1]['solid_geometry']
    assert fc.history.undo()                                # back to singlegeo
    assert geo.multigeo is False and geo.tools[1]['solid_geometry'] == []
    assert fc.history.redo() and geo.multigeo is True


# ---------------------------------------------------------------------------------------------------------------------
# 6. Simplify (runs in the worker)
# ---------------------------------------------------------------------------------------------------------------------
def test_simplify_is_a_snapshot_step(fc, no_plot, monkeypatch):
    # a rectangle contour with many collinear vertices
    pts = [(x, 0.0) for x in np.linspace(0, 20, 41)] + [(20.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    contour = LineString(pts)

    def init(obj, _app):
        obj.solid_geometry = [contour]
        obj.tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': [contour]}}
        obj.multigeo = True
    geo = fc.app_obj.new_object('geometry', 'geo_simp', init, plot=False)
    monkeypatch.setattr(fc, 'worker_task', SimpleNamespace(emit=lambda d: d['fcn'](*d['params'])))
    monkeypatch.setattr(fc, 'plot_all', lambda *a, **k: None)
    geo.ui = SimpleNamespace(geo_tol_entry=SimpleNamespace(get_value=lambda: 0.01))
    geo.on_calculate_vertex_points = lambda: None

    def count(g):
        return sum(len(p.coords) for p in g.tools[1]['solid_geometry'])
    c0 = count(geo)
    n = _stack(fc)
    geo.on_simplify_geometry()
    _one_step(fc, n, 'Simplify')
    assert count(geo) < c0
    assert fc.history.undo() and count(geo) == c0
    assert fc.history.redo() and count(geo) < c0


# ---------------------------------------------------------------------------------------------------------------------
# 7. Gerber buffer, 8. Isolation buffer
# ---------------------------------------------------------------------------------------------------------------------
def test_gerber_generate_buffer_is_a_snapshot_step(fc, no_plot, monkeypatch):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_buf')
    area0 = _area(grb)
    monkeypatch.setattr(fc, 'worker_task', SimpleNamespace(emit=lambda d: d['fcn'](*d['params'])))
    # the pool buffers by 0.5 (the real handler buffers by 1e-7 and back, which changes nothing to see)
    fake_pool = SimpleNamespace(apply_async=lambda fcn, args: SimpleNamespace(
        get=lambda: MultiPolygon([p.buffer(0.5) for p in args[0]]).buffer(0)))
    monkeypatch.setattr(fc, 'pool', fake_pool, raising=False)
    monkeypatch.setattr(type(grb), 'plot_single_object', SimpleNamespace(emit=lambda: None), raising=False)
    n = _stack(fc)
    grb.on_generate_buffer()
    _one_step(fc, n, 'Buffer')
    area1 = _area(grb)
    assert area1 > area0
    assert fc.history.undo() and np.isclose(_area(grb), area0)
    assert fc.history.redo() and np.isclose(_area(grb), area1)


def test_isolation_generate_buffer_is_a_snapshot_step(fc, no_plot, monkeypatch):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_iso_buf')
    grb.solid_geometry = list(grb.solid_geometry.geoms) if hasattr(grb.solid_geometry, 'geoms') \
        else list(grb.solid_geometry)
    monkeypatch.setattr(type(grb), 'plot_single_object', SimpleNamespace(emit=lambda: None), raising=False)
    monkeypatch.setattr(fc, 'worker_task', SimpleNamespace(emit=lambda d: d['fcn'](*d['params'])))
    stub = SimpleNamespace(app=fc, ui=SimpleNamespace(object_combo=SimpleNamespace(currentText=lambda: 'g_iso_buf')))
    n = _stack(fc)
    ToolIsolation.on_generate_buffer(stub)
    _one_step(fc, n, 'Buffer')
    assert not isinstance(grb.solid_geometry, list)          # the list became 1 buffered geometry
    assert fc.history.undo() and isinstance(grb.solid_geometry, list)
    assert fc.history.redo() and not isinstance(grb.solid_geometry, list)


# ---------------------------------------------------------------------------------------------------------------------
# 9. CNCJob source file, 10 / 11. Rename
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def cncjob(fc, no_plot):
    _load(fc, 'gerber', 'unify_mixed.gbr', 'g_job')
    fc.shell.tcl.eval('isolate g_job -dia 0.2 -passes 1 -outname g_job_iso')
    _settle(fc)
    fc.shell.tcl.eval('cncjob g_job_iso -dia 0.2 -z_cut -0.1 -z_move 2 -feedrate 100 -outname job_hist')
    _settle(fc)
    for _ in range(20):
        QtWidgets.QApplication.processEvents()
    job = fc.collection.get_by_name('job_hist')
    assert job is not None
    return job


def test_cncjob_creation_is_no_extra_history_step(fc, cncjob):
    # the snippets check box that is set while the job is made does not record a source file step
    assert not any('Source' in step.label for step in fc.history.undo_stack)


def test_cncjob_update_source_file_is_a_snapshot_step(fc, cncjob):
    src0 = cncjob.source_file
    cncjob.prepend_snippet = '(SNIPPET-START)\n'
    cncjob.append_snippet = '(SNIPPET-END)\n'
    cncjob.ui.snippets_cb.blockSignals(True)
    cncjob.ui.snippets_cb.set_value(True)
    cncjob.ui.snippets_cb.blockSignals(False)
    n = _stack(fc)
    cncjob.on_update_source_file()
    _one_step(fc, n, 'Source')
    src1 = cncjob.source_file
    assert src1 != src0 and '(SNIPPET-START)' in src1
    assert fc.history.undo() and cncjob.source_file == src0
    assert fc.history.redo() and cncjob.source_file == src1


def test_properties_name_field_rename_is_a_rename_step(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_name_a')
    n = _stack(fc)
    grb.on_name_activate(new_name='g_name_b')
    _one_step(fc, n, 'g_name_b')
    assert grb.obj_options['name'] == 'g_name_b'
    assert fc.history.undo() and grb.obj_options['name'] == 'g_name_a'
    assert fc.history.redo() and grb.obj_options['name'] == 'g_name_b'
    n = _stack(fc)
    grb.on_name_activate(new_name='g_name_b')                  # no change, no step
    assert _stack(fc) == n


def test_cncjob_export_rename_is_a_rename_step(fc, cncjob, tmp_path):
    n = _stack(fc)
    cncjob.export_gcode_handler(str(tmp_path / 'exported_job.nc'))
    assert cncjob.obj_options['name'] == 'exported_job'
    _one_step(fc, n, 'exported_job')
    assert fc.history.undo() and cncjob.obj_options['name'] == 'job_hist'
    assert fc.history.redo() and cncjob.obj_options['name'] == 'exported_job'
