"""FLATCAM_DATA_PATH: a folder for the application settings instead of the default one."""
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import MagicMock, Mock, mock_open

import pytest

import appMain
from appCommon.DataPath import data_path_from_env


@pytest.mark.parametrize('environ', [{}, {'FLATCAM_DATA_PATH': ''}, {'FLATCAM_DATA_PATH': '   '}],
                         ids=['unset', 'empty', 'blank'])
def test_not_set_or_empty_gives_no_folder(environ):
    assert data_path_from_env(environ) is None


def test_absolute_path_and_spaces_around_it(tmp_path):
    folder = str(tmp_path / 'FlatCAM settings')
    assert data_path_from_env({'FLATCAM_DATA_PATH': folder}) == folder
    assert data_path_from_env({'FLATCAM_DATA_PATH': ' %s ' % folder}) == folder


def test_relative_path_is_taken_from_the_working_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert data_path_from_env({'FLATCAM_DATA_PATH': 'settings'}) == os.path.join(os.getcwd(), 'settings')


def test_home_folder_is_expanded():
    expected = os.path.abspath(os.path.join(os.path.expanduser('~'), 'flatcam-test'))
    assert data_path_from_env({'FLATCAM_DATA_PATH': '~/flatcam-test'}) == expected


def test_reads_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('FLATCAM_DATA_PATH', str(tmp_path))
    assert data_path_from_env() == str(tmp_path)
    monkeypatch.delenv('FLATCAM_DATA_PATH')
    assert data_path_from_env() is None


class SetupStub:
    """The attributes and the path helpers of App that App._setup_paths_and_config uses."""
    headless = False
    version = appMain.App.version
    tools_database_path = appMain.App.tools_database_path
    defaults_path = appMain.App.defaults_path
    factory_defaults_path = appMain.App.factory_defaults_path
    recent_files_path = appMain.App.recent_files_path
    recent_projects_path = appMain.App.recent_projects_path
    preprocessors_path = appMain.App.preprocessors_path

    def __init__(self):
        self.log = Mock()
        self.on_startup_args = Mock()


@pytest.fixture
def setup_paths(tmp_path, monkeypatch):
    """App._setup_paths_and_config with the default settings folders under tmp_path: never the real ones."""
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    monkeypatch.delenv('FLATCAM_DATA_PATH', raising=False)
    # the method changes the working folder to the application folder; monkeypatch changes it back
    monkeypatch.chdir(tmp_path)
    # on Windows the method also starts the listener for the arguments of a second instance
    monkeypatch.setattr(appMain, 'ArgsThread', MagicMock())
    monkeypatch.setattr(appMain, 'QtCore', MagicMock())

    def run():
        app = SetupStub()
        appMain.App._setup_paths_and_config(app)
        return app

    return run


def test_app_makes_the_settings_in_the_folder_of_the_variable(tmp_path, monkeypatch, setup_paths):
    settings = tmp_path / 'settings'
    monkeypatch.setenv('FLATCAM_DATA_PATH', str(settings))

    app = setup_paths()

    assert app.data_path == str(settings)
    for path in (app.defaults_path(), app.factory_defaults_path(), app.tools_database_path(),
                 app.recent_files_path(), app.recent_projects_path()):
        assert os.path.isfile(path)
        assert os.path.dirname(path) == str(settings)
    assert os.path.isdir(os.path.join(str(settings), 'preprocessors'))
    # nothing is written in the default folder
    assert not (tmp_path / 'appdata').exists()
    assert not (tmp_path / 'home').exists()


def test_app_takes_a_relative_folder_from_the_working_folder_at_the_start(tmp_path, monkeypatch, setup_paths):
    monkeypatch.setenv('FLATCAM_DATA_PATH', 'settings')
    start_folder = os.getcwd()

    app = setup_paths()

    assert app.data_path == os.path.join(start_folder, 'settings')
    # the working folder is now the application folder and the settings are still found
    assert os.path.normcase(os.getcwd()) != os.path.normcase(start_folder)
    assert os.path.isfile(app.defaults_path())
    # the absolute path is kept for a restart, which starts from the application folder
    assert os.environ['FLATCAM_DATA_PATH'] == os.path.join(start_folder, 'settings')

    restarted = setup_paths()

    assert restarted.data_path == app.data_path


@pytest.mark.parametrize('frozen', [False, True], ids=['source', 'frozen'])
def test_startup_override_without_appdata(tmp_path, monkeypatch, frozen):
    from appGUI import VisPyPatches

    settings = tmp_path / 'settings'
    monkeypatch.setenv('FLATCAM_DATA_PATH', str(settings))
    monkeypatch.delenv('APPDATA', raising=False)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr('multiprocessing.freeze_support', lambda: None)
    monkeypatch.setattr('builtins.open', mock_open(read_data='portable=False\n'))

    def stop_after_paths():
        raise RuntimeError('startup paths ready')

    monkeypatch.setattr(VisPyPatches, 'apply_patches', stop_after_paths)
    with pytest.raises(RuntimeError, match='startup paths ready'):
        runpy.run_path(str(Path(appMain.__file__).with_name('flatcam.py')), run_name='__main__')
    assert settings.is_dir()


@pytest.mark.parametrize('value', [None, '', '  '], ids=['unset', 'empty', 'blank'])
def test_app_without_the_variable_uses_the_default_folder(tmp_path, monkeypatch, setup_paths, value):
    if value is not None:
        monkeypatch.setenv('FLATCAM_DATA_PATH', value)

    app = setup_paths()

    if sys.platform == 'win32':
        expected = os.path.join(str(tmp_path / 'appdata'), 'FlatCAM')
    else:
        expected = os.path.join(str(tmp_path / 'home'), '.FlatCAM')
    assert app.data_path == expected
    assert os.path.isfile(app.defaults_path())
