"""App Undo / Redo history on real objects in a headless App: matrix, snapshot, delete + rebuild, create, rename."""

import os
import sys
import time

import numpy as np
import pytest
from PyQt6 import QtWidgets
from shapely.geometry import box

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import appGUI.GUIElements as gui
import appHandlers.appHistory as appHistory
from appHandlers.appHistory import apply_matrix_to_object
from appMain import App
from appObjects.AppObjectTemplate import FlatCAMObj
from appObjects.ExcellonObject import ExcellonObject

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
    """Wait for the tasks that an object rebuild starts (the history refuses Undo / Redo while the app is busy)."""
    end = time.time() + timeout
    while fc.projects.is_busy() and time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


def _bounds(obj):
    return np.array(obj.bounds())


def test_matrix_undo_redo(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_matrix')
    b0 = _bounds(grb)
    m = (0.0, -1.0, 1.0, 0.0, 10.0, 0.0)
    apply_matrix_to_object(grb, m)
    fc.history.record_matrix('rot', [(grb, m)])
    b1 = _bounds(grb)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)
    assert fc.history.redo() and np.allclose(_bounds(grb), b1)


def test_delete_undo_rebuilds_same_uid_and_later_steps_work(fc, no_plot):
    exc = _load(fc, 'excellon', 'unify_mixed.drl', 'e_del')
    uid, b0 = exc.history_uid, _bounds(exc)
    m = (1.0, 0.0, 0.0, 1.0, 5.0, 5.0)
    apply_matrix_to_object(exc, m)
    fc.history.record_matrix('move', [(exc, m)])
    fc.history.record_delete('del', [exc])
    fc.object_ops.delete_objects_now([exc])
    assert fc.history.find(uid) is None
    assert fc.history.undo()                    # rebuild
    _settle(fc)
    rebuilt = fc.history.find(uid)
    assert rebuilt is not None and rebuilt is not exc
    assert fc.history.undo()                    # the move, on the rebuilt object
    assert np.allclose(_bounds(rebuilt), b0)


def test_create_undo_redo(fc, no_plot):
    count = len(fc.collection.get_list())
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_create')
    assert fc.history.undo_label().endswith('g_create')
    uid = grb.history_uid
    assert fc.history.undo() and fc.history.find(uid) is None
    assert len(fc.collection.get_list()) == count
    assert fc.history.redo() and fc.history.find(uid) is not None


def test_create_undo_of_an_object_that_is_not_active(fc, no_plot):
    # a file import makes the object with autoselected=False: Undo deletes an object that is not the active one
    def init(obj, _app):
        obj.parse_file(os.path.join(FIX, 'unify_mixed.gbr'))
    grb = fc.app_obj.new_object('gerber', 'g_not_active', init, plot=False, autoselected=False)
    assert fc.collection.get_active() is not grb
    uid = grb.history_uid
    assert fc.history.undo()
    assert fc.history.find(uid) is None
    _settle(fc)
    assert fc.history.redo() and fc.history.find(uid) is not None


def test_snapshot_buffer(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_snap')
    b0 = _bounds(grb)
    with fc.history.snapshot('buffer', [grb]):
        grb.buffer(0.5, 1, None)
    assert not np.allclose(_bounds(grb), b0)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)


def test_rename(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_old')
    fc.history.record_rename(grb, 'g_old', 'g_new')
    fc.collection.rename_object(grb, 'g_new')
    assert fc.history.undo() and grb.obj_options['name'] == 'g_old'
    assert fc.history.redo() and grb.obj_options['name'] == 'g_new'


def _select(fc, monkeypatch, objs):
    monkeypatch.setattr(fc.collection, 'get_selected', lambda: list(objs))


def _fake_spinner(value):
    class _Spinner:
        def __init__(self, *a, **k):
            pass

        def setWindowIcon(self, *a):
            pass

        def get_value(self):
            return value, True
    return _Spinner


def test_flipy_two_objects_one_step(fc, no_plot, monkeypatch):
    g1 = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_flip1')
    g2 = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_flip2')
    apply_matrix_to_object(g2, (1.0, 0.0, 0.0, 1.0, 10.0, 10.0))      # the flip axis is not the center of g1 anymore
    _select(fc, monkeypatch, [g1, g2])
    b1, b2 = _bounds(g1), _bounds(g2)
    n = len(fc.history.undo_stack)
    fc.object_ops.on_flipy()
    assert len(fc.history.undo_stack) == n + 1
    assert not np.allclose(_bounds(g1), b1)
    assert fc.history.undo()
    assert np.allclose(_bounds(g1), b1) and np.allclose(_bounds(g2), b2)
    assert fc.history.redo()
    assert not np.allclose(_bounds(g1), b1)


def test_flipx_undo(fc, no_plot, monkeypatch):
    exc = _load(fc, 'excellon', 'unify_mixed.drl', 'e_flipx')
    # the bounds of 1 object do not change in a flip around its own center: a second object moves the axis
    other = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_flipx')
    apply_matrix_to_object(other, (1.0, 0.0, 0.0, 1.0, 20.0, 0.0))
    b0 = _bounds(exc)
    _select(fc, monkeypatch, [exc, other])
    fc.object_ops.on_flipx()
    assert not np.allclose(_bounds(exc), b0)
    assert fc.history.undo() and np.allclose(_bounds(exc), b0)


@pytest.mark.parametrize('kind,filename', [('gerber', 'unify_mixed.gbr'), ('excellon', 'unify_mixed.drl')])
def test_rotate_30_undo_restores_bounds(fc, no_plot, monkeypatch, kind, filename):
    obj = _load(fc, kind, filename, 'rot30_' + kind)
    b0 = _bounds(obj)
    _select(fc, monkeypatch, [obj])
    fc.object_ops.on_rotate(silent=True, preset=30)
    b1 = _bounds(obj)
    assert not np.allclose(b1, b0)
    # a hole polygon is rotated twice (not rebuilt), so its circle approximation differs by a tiny amount
    assert fc.history.undo() and np.allclose(_bounds(obj), b0, atol=1e-3)
    assert fc.history.redo() and np.allclose(_bounds(obj), b1, atol=1e-3)


def test_rotate_geometry_30_undo(fc, no_plot, monkeypatch):
    geo = fc.app_obj.new_object('geometry', 'geo_rot', lambda o, a: setattr(o, 'solid_geometry', [box(0, 0, 4, 1)]),
                                plot=False)
    b0 = _bounds(geo)
    _select(fc, monkeypatch, [geo])
    fc.object_ops.on_rotate(silent=True, preset=30)
    assert not np.allclose(_bounds(geo), b0)
    assert fc.history.undo() and np.allclose(_bounds(geo), b0, atol=1e-6)


@pytest.mark.parametrize('handler,args', [('on_skewx', 20.0), ('on_skewy', 15.0)])
def test_skew_undo_restores_bounds(fc, no_plot, monkeypatch, handler, args):
    monkeypatch.setattr(gui, 'FCInputDoubleSpinner', _fake_spinner(args))
    obj = _load(fc, 'gerber', 'unify_mixed.gbr', 'skew_' + handler)
    b0 = _bounds(obj)
    _select(fc, monkeypatch, [obj])
    getattr(fc.object_ops, handler)()
    b1 = _bounds(obj)
    assert not np.allclose(b1, b0)
    assert fc.history.undo() and np.allclose(_bounds(obj), b0, atol=1e-6)
    assert fc.history.redo() and np.allclose(_bounds(obj), b1, atol=1e-6)


def test_transform_tool_group_undo(fc, no_plot, monkeypatch):
    g1 = _load(fc, 'gerber', 'unify_mixed.gbr', 'tt1')
    g2 = _load(fc, 'gerber', 'unify_mixed.gbr', 'tt2')
    _select(fc, monkeypatch, [g1, g2])
    b1, b2 = _bounds(g1), _bounds(g2)
    n = len(fc.history.undo_stack)
    fc.transform_tool.on_rotate_action(30.0, (1.0, 2.0))
    assert len(fc.history.undo_stack) == n + 1
    assert not np.allclose(_bounds(g1), b1)
    assert fc.history.undo()
    assert np.allclose(_bounds(g1), b1, atol=1e-6) and np.allclose(_bounds(g2), b2, atol=1e-6)


def test_transform_tool_buffer_snapshot(fc, no_plot, monkeypatch):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'tt_buf')
    b0 = _bounds(grb)
    _select(fc, monkeypatch, [grb])
    fc.transform_tool.on_buffer_action(0.5, 1)
    assert not np.allclose(_bounds(grb), b0)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)


def test_move2origin_undo(fc, no_plot, monkeypatch):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_m2o')
    offset = (7.0, 9.0)
    apply_matrix_to_object(grb, (1.0, 0.0, 0.0, 1.0, offset[0], offset[1]))
    b0 = _bounds(grb)
    _select(fc, monkeypatch, [grb])
    fc.object_ops.on_move2origin(use_thread=False)
    assert not np.allclose(_bounds(grb), b0)
    assert fc.history.undo() and np.allclose(_bounds(grb), b0, atol=1e-6)


def test_move_tool_two_objects_one_step(fc, no_plot, monkeypatch):
    # the Move tool (M key) moves the objects in a worker; the move is 1 history step for all of them
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_move')
    exc = _load(fc, 'excellon', 'unify_mixed.drl', 'e_move')
    b_grb, b_exc = _bounds(grb), _bounds(exc)
    monkeypatch.setattr(type(grb), 'regenerate_source', lambda self, *a, **k: True)
    monkeypatch.setattr(type(exc), 'regenerate_source', lambda self, *a, **k: True)
    n = len(fc.history.undo_stack)
    fc.move_tool.move_handler((4.0, -2.5), objects=[grb, exc])
    _settle(fc)
    assert np.allclose(_bounds(grb), b_grb + [4.0, -2.5, 4.0, -2.5])
    assert len(fc.history.undo_stack) == n + 1
    assert fc.history.undo()
    assert np.allclose(_bounds(grb), b_grb) and np.allclose(_bounds(exc), b_exc)
    assert fc.history.redo()
    assert np.allclose(_bounds(exc), b_exc + [4.0, -2.5, 4.0, -2.5])


def test_align_records_one_step(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_align')
    b0 = _bounds(grb)
    m = (1.0, 0.0, 0.0, 1.0, 3.0, 4.0)
    n = len(fc.history.undo_stack)
    apply_matrix_to_object(grb, m)
    fc.history.record_matrix("Align Objects", [(grb, m)])
    assert len(fc.history.undo_stack) == n + 1 and fc.history.undo_label() == "Align Objects"
    assert hasattr(fc.align_objects_tool, 'on_apply') and not hasattr(fc.align_objects_tool, 'undo_stack')
    assert fc.history.undo() and np.allclose(_bounds(grb), b0)


def test_forget_drops_the_steps_of_the_object(fc, no_plot):
    grb = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_forget')
    other = _load(fc, 'gerber', 'unify_mixed.gbr', 'g_keep')
    m = (1.0, 0.0, 0.0, 1.0, 1.0, 0.0)
    for obj in (grb, other, grb):
        apply_matrix_to_object(obj, m)
        fc.history.record_matrix('move', [(obj, m)])
    fc.history.forget(grb.history_uid)
    for step in fc.history.undo_stack + fc.history.redo_stack:
        assert grb.history_uid not in step.uids()
    assert fc.history.undo_label() == 'move' and other.history_uid in fc.history.undo_stack[-1].uids()
