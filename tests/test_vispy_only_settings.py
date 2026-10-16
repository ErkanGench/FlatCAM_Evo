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


@pytest.mark.parametrize('cli,accept', [(False, True), (False, False), (True, True)])
def test_project_settings_import(cli, accept):
    from PyQt6 import QtWidgets
    from appHandlers.appIO import appIO

    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app = MagicMock()
    app.options = {'existing': 1}
    app.resource_location = 'assets/resources'
    handler = SimpleNamespace(app=app, on_file_new_project=MagicMock())
    project = {'objs': [], 'options': {'global_graphic_engine': '2D',
                                     'global_graphic_engine_3d_no_mp': True, 'unrelated': 9}}
    with patch('appHandlers.appIO.FCMessageBox') as message:
        yes, no = object(), object()
        message.return_value.addButton.side_effect = [yes, no]
        message.return_value.clickedButton.return_value = yes if accept else no
        assert appIO._restore_project_handler(handler, project, 'board.FlatPrj',
                                             True, True, cli, False) is True
    expected = {'existing': 1}
    if accept:
        expected.update(global_graphic_engine_3d_no_mp=True, unrelated=9)
    assert app.options == expected
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
