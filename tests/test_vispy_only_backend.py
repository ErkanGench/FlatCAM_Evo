"""GPU-free startup checks for the VisPy-only canvas."""

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest

import appMain


def canvas_app(engine='2D', pan='2', cursor='small', snap=True):
    return SimpleNamespace(
        options={'global_graphic_engine': engine, 'global_pan_button': pan,
                 'global_cursor_type': cursor},
        defaults={}, log=Mock(), inform=Mock(), headless=False,
        ui=SimpleNamespace(keyPressEvent=Mock(), grid_snap_btn=Mock(isChecked=Mock(return_value=snap))),
        on_mouse_move_over_plot=Mock(), on_mouse_click_over_plot=Mock(),
        on_mouse_click_release_over_plot=Mock(), on_mouse_double_click_over_plot=Mock()
    )


@pytest.mark.parametrize('engine', ['2D', '3D', 'unexpected'])
@pytest.mark.parametrize('control', [False, True])
def test_startup_always_constructs_vispy(monkeypatch, engine, control):
    app = canvas_app(engine)
    canvas = Mock()
    constructor = Mock(return_value=canvas)
    modifiers = Mock(return_value=(appMain.QtCore.Qt.KeyboardModifier.ControlModifier if control
                                  else appMain.QtCore.Qt.KeyboardModifier.NoModifier))
    monkeypatch.setattr(appMain, 'PlotCanvas', constructor)
    monkeypatch.setattr(appMain.QtWidgets.QApplication, 'queryKeyboardModifiers', modifiers)

    assert appMain.App.on_plotcanvas_setup(app) is canvas
    constructor.assert_called_once_with(app)
    modifiers.assert_not_called()
    assert app.options['global_graphic_engine'] == engine


@pytest.mark.parametrize('pan, button', [('2', 2), ('3', 3)])
@pytest.mark.parametrize('cursor, snap', [('small', True), ('big', False)])
def test_startup_preserves_canvas_wiring(monkeypatch, pan, button, cursor, snap):
    app = canvas_app(pan=pan, cursor=cursor, snap=snap)
    canvas = Mock()
    canvas.graph_event_connect.return_value = None
    monkeypatch.setattr(appMain, 'PlotCanvas', Mock(return_value=canvas))

    assert appMain.App.on_plotcanvas_setup(app) is canvas
    canvas.native.setFocus.assert_called_once_with()
    assert canvas.view.camera.pan_button_setting == button
    assert canvas.graph_event_connect.call_args_list == [
        call('mouse_move', app.on_mouse_move_over_plot),
        call('mouse_press', app.on_mouse_click_over_plot),
        call('mouse_release', app.on_mouse_click_release_over_plot),
        call('mouse_double_click', app.on_mouse_double_click_over_plot),
        call('key_press', app.ui.keyPressEvent)
    ]
    canvas.new_cursor.assert_called_once_with(**({} if cursor == 'small' else {'big': True}))
    assert app.app_cursor is canvas.new_cursor.return_value
    assert app.app_cursor.enabled is snap


def test_canvas_failure_is_visible_and_logged(monkeypatch):
    app = canvas_app()
    dialog = Mock()
    monkeypatch.setattr(appMain, 'PlotCanvas', Mock(side_effect=RuntimeError('driver detail')))
    message_box = Mock(return_value=dialog)
    monkeypatch.setattr(appMain, 'FCMessageBox', message_box)

    assert appMain.App.on_plotcanvas_setup(app) == 'fail'
    message_box.assert_called_once_with(parent=app.ui)
    dialog.exec.assert_called_once_with()
    message = dialog.setInformativeText.call_args.args[0]
    assert 'OpenGL' in message
    assert 'drivers' in message
    assert 'remote' in message
    assert 'VM' in message
    assert 'Legacy' not in message
    assert 'Technical details are available in the application log and error details.' in message
    assert 'driver detail' in dialog.setDetailedText.call_args.args[0]
    assert 'Traceback' in dialog.setDetailedText.call_args.args[0]
    assert any('driver detail' in str(args) for args in app.log.error.call_args_list)


@pytest.mark.parametrize('failed', [False, True])
def test_setup_gui_collections_and_failure_cleanup(monkeypatch, failed):
    options = MagicMock()
    values = {'global_serial': 'existing-serial-number', 'global_graphic_engine': '2D'}
    options.get.side_effect = values.get
    app = Mock(options=options, resource_location='assets', version='test', date='test',
               data_path='.', _current_theme='default', _show_splash=True, headless=False)
    canvas = Mock()
    app.on_plotcanvas_setup.return_value = 'fail' if failed else canvas
    settings = Mock()
    settings.value.return_value = 1
    monkeypatch.setattr(appMain, 'QSettings', Mock(return_value=settings))
    monkeypatch.setattr(appMain.QtCore, 'QSettings', Mock(return_value=settings))
    monkeypatch.setattr(appMain.QtCore, 'QTimer', Mock())
    monkeypatch.setattr(appMain.QtGui, 'QPixmap', Mock())
    monkeypatch.setattr(appMain.QtWidgets, 'QSplashScreen', Mock())
    monkeypatch.setattr(appMain.QtWidgets, 'QWidget', Mock())
    monkeypatch.setattr(appMain.QtWidgets.QApplication, 'screenAt', Mock(return_value=None))
    monkeypatch.setattr(appMain.fcTranslate, 'load_languages', Mock(return_value={}))
    monkeypatch.setattr(appMain.fcTranslate, 'apply_language', Mock(return_value='English'))
    monkeypatch.setattr(appMain, 'load_preprocessors', Mock(return_value={}))
    for name in ('MainGUI', 'FCShell', 'RegisterFK', 'PreferencesUIManager', 'ObjectCollection',
                 'AppObject', 'FCVisibleProcessContainer', 'ProjectManager', 'ProjectSelector'):
        monkeypatch.setattr(appMain, name, Mock())
    # the shape collections are made by the canvas (plotcanvas.new_shape_collection)
    canvas.new_shape_collection.side_effect = [Mock(), Mock(), Mock()]
    shapes = canvas.new_shape_collection
    pool_constructor = Mock(side_effect=AssertionError('Replacement pool created during GUI setup'))
    monkeypatch.setattr(appMain, 'Pool', pool_constructor)

    if failed:
        with pytest.raises(SystemError, match='Failed to start the Canvas'):
            appMain.App._setup_gui(app)
        app.splash.finish.assert_called_once_with(app.ui)
        assert app.pool.method_calls == [call.terminate(), call.join()]
        app.clear_pool.assert_not_called()
        app.pool_recreated.emit.assert_not_called()
        pool_constructor.assert_not_called()
        app.log.error.assert_called_once_with('Failed to start the Canvas')
        app.on_plotcanvas_add.assert_not_called()
        shapes.assert_not_called()
    else:
        appMain.App._setup_gui(app)
        assert app.plotcanvas is canvas
        app.on_plotcanvas_add.assert_called_once_with(canvas, app.ui.right_layout)
        assert shapes.call_args_list == [call(layers=1)] * 3
        assert len({id(app.tool_shapes), id(app.hover_shapes), id(app.sel_shapes)}) == 3
        app.clear_pool.assert_not_called()


def test_canvas_failure_leaves_no_pool_workers():
    script = '''
import ast
import gc
import multiprocessing
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

tree = ast.parse(Path('appMain.py').read_text(encoding='utf-8'))
app_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'App')
setup = next(node for node in app_class.body if isinstance(node, ast.FunctionDef) and node.name == '_setup_gui')
failure = next(node for node in setup.body if isinstance(node, ast.If)
               and ast.unparse(node.test) == "self.plotcanvas == 'fail'")
clear_pool = next(node for node in app_class.body if isinstance(node, ast.FunctionDef) and node.name == 'clear_pool')
setup.body = [failure]
constructor = Mock(side_effect=AssertionError('Replacement pool created during fatal cleanup'))
namespace = {'Pool': constructor, 'gc': gc}
exec(compile(ast.fix_missing_locations(ast.Module(body=[setup, clear_pool], type_ignores=[])),
             'appMain.py', 'exec'), namespace)

pool = multiprocessing.get_context('spawn').Pool(processes=2)
workers = list(pool._pool)
app = SimpleNamespace(pool=pool, plotcanvas='fail', splash=Mock(), ui=Mock(), log=Mock(),
                      pool_recreated=Mock(), options={}, defaults={})
app.clear_pool = MethodType(namespace['clear_pool'], app)
try:
    assert all(worker.is_alive() for worker in workers)
    try:
        namespace['_setup_gui'](app)
    except SystemError as error:
        assert str(error) == 'Failed to start the Canvas'
    else:
        raise AssertionError('Fatal canvas failure did not raise SystemError')
    assert app.pool is pool
    assert all(not worker.is_alive() and worker.exitcode is not None for worker in workers)
    assert not multiprocessing.active_children()
    constructor.assert_not_called()
    app.pool_recreated.emit.assert_not_called()
    app.splash.finish.assert_called_once_with(app.ui)
    print('Fatal canvas cleanup joined all pool workers')
finally:
    pool.terminate()
    pool.join()
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Fatal canvas cleanup joined all pool workers' in result.stdout


def test_application_import_without_legacy_canvas():
    script = '''
import importlib
import importlib.abc
import sys

sys.argv = ['flatcam.py']

class BlockLegacyCanvas(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'appGUI.PlotCanvasLegacy' or fullname.startswith('appGUI.PlotCanvasLegacy.'):
            raise AssertionError('Legacy canvas import attempted: ' + fullname)

sys.meta_path.insert(0, BlockLegacyCanvas())
application = importlib.import_module('appMain')
from appGUI.PlotCanvas import PlotCanvas
assert application.PlotCanvas is PlotCanvas
assert not any(name == 'appGUI.PlotCanvasLegacy' or name.startswith('appGUI.PlotCanvasLegacy.')
               for name in sys.modules)
print('VisPy-only application import passed')
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VisPy-only application import passed' in result.stdout
