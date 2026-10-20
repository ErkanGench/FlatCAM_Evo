"""The switches of App for the headless mode, tested on the methods without a full App."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from appCommon.Headless import HeadlessExit
from appGUI.NullCanvas import NullCanvas


def test_the_headless_canvas_is_the_null_canvas():
    from appMain import App
    fake = SimpleNamespace(headless=True, log=Mock())
    canvas = App.on_plotcanvas_setup(fake)
    assert isinstance(canvas, NullCanvas)
    assert fake.app_cursor is not None


def test_quit_in_headless_mode_ends_the_run_and_saves_nothing():
    from appHandlers.appLifecycle import AppLifecycle
    app = Mock()
    app.headless = True
    app.headless_exit_code = None
    lifecycle = AppLifecycle(app=app)
    with pytest.raises(HeadlessExit) as info:
        lifecycle.quit_application(silent=True)
    assert info.value.code == 0
    assert app.headless_exit_code == 0
    app.preferencesUiManager.save_defaults.assert_not_called()


def test_quit_in_gui_mode_is_unchanged():
    from appHandlers.appLifecycle import AppLifecycle
    import inspect
    source = inspect.getsource(AppLifecycle.quit_application)
    assert 'save_defaults' in source
