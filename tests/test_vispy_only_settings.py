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

