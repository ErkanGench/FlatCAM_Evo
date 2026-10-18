"""Retired renderer selection must not survive persistence boundaries."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from defaults import AppDefaults, AppOptions


@pytest.mark.parametrize('engine', [None, '2D', '3D', 'unexpected'])
def test_settings_migration(tmp_path, engine):
    payload = {'global_graphic_engine_3d_no_mp': True, 'unrelated_setting': {'value': 7}}
    if engine is not None:
        payload['global_graphic_engine'] = engine
    filename = tmp_path / 'settings.FlatConfig'
    filename.write_text(json.dumps(payload))
    inform = MagicMock()
    defaults = AppDefaults(beta=False)
    defaults.load(str(filename), inform)
    options = AppOptions(version='test', baseline=payload)
    for snapshot in (AppDefaults.factory_defaults, defaults.defaults, defaults.current_defaults,
                     options.baseline, options.options, options.current_options):
        assert 'global_graphic_engine' not in snapshot
    options.load(str(filename), inform, baseline=payload)
    for snapshot in (defaults.defaults, defaults.current_defaults, options.baseline,
                     options.options, options.current_options):
        assert 'global_graphic_engine' not in snapshot
        assert snapshot['global_graphic_engine_3d_no_mp'] is True
        assert snapshot['unrelated_setting'] == {'value': 7}
    assert ('global_graphic_engine' in payload) is (engine is not None)
    options.load(str(filename), inform)
    assert 'global_graphic_engine' not in options.current_options
    assert 'global_graphic_engine' not in AppOptions(version='test').baseline


@pytest.mark.parametrize('cli', [False, True])
def test_project_open_loads_only_project_options(cli):
    from PyQt6 import QtWidgets
    from appHandlers.appIO import appIO

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    defaults = AppDefaults(beta=False)
    defaults['global_appearance'] = 'light'
    app = MagicMock()
    app.defaults = defaults
    app.options = AppOptions(version='test', baseline=defaults, defaults=defaults)
    app.resource_location = 'assets/resources'
    handler = SimpleNamespace(app=app, on_file_new_project=MagicMock())
    project = {'objs': [], 'options': {'global_graphic_engine': '2D', 'global_appearance': 'dark',
                                     'gerber_bboxmargin': 0.75}}
    with patch('appHandlers.appIO.FCMessageBox') as message:
        assert appIO._restore_project_handler(handler, project, 'board.FlatPrj',
                                             True, True, cli, False) is True
    message.assert_not_called()
    assert defaults['global_appearance'] == 'light'
    assert app.options['global_appearance'] == 'light'
    assert app.options['gerber_bboxmargin'] == 0.75
    assert app.options['gerber_bboxrounded'] == defaults['gerber_bboxrounded']
    assert 'global_graphic_engine' not in list(defaults)
    assert app.preferencesUiManager.defaults_write_form.called is (not cli)
    assert project['options']['global_graphic_engine'] == '2D'


def test_preferences_have_only_shape_processing_control():
    from PyQt6 import QtWidgets
    from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
    from appGUI.preferences.general.GeneralAppPrefGroupUI import GeneralAppPrefGroupUI
    from appGUI.preferences.PreferencesUIManager import PreferencesUIManager

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = MagicMock()
    app.decimals = 4
    app.options = dict(AppDefaults.factory_defaults)
    with patch.object(OptionsGroupUI, 'app', app):
        group = GeneralAppPrefGroupUI(app)
    try:
        assert not hasattr(group, 'ge_radio')
        assert not hasattr(group, 'ge_label')
        assert group.ge_comp_cb.text() == 'Disable parallel shape processing'
        assert 'synchronously' in group.ge_comp_cb.toolTip()
        ui = MagicMock()
        ui.general_pref_form.general_app_group = group
        manager = PreferencesUIManager(AppDefaults(), '', ui, MagicMock(), app.options)
        try:
            assert 'global_graphic_engine' not in manager.defaults_form_fields
            assert manager.defaults_form_fields['global_graphic_engine_3d_no_mp'] is group.ge_comp_cb
        finally:
            manager.deleteLater()
    finally:
        group.deleteLater()
