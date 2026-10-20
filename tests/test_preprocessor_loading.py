"""appPreProcessor.load_preprocessors() finds the preprocessors that come with the application next to
appPreProcessor.py (next to the executable in a frozen build), whatever the current working directory, and executes
every preprocessor file as a module of its own with importlib.util.spec_from_file_location() / exec_module().

Before, the built-in folder was 'preprocessors' relative to the current working directory (none was found from another
folder), every file was loaded with the deprecated SourceFileLoader.load_module() (1 DeprecationWarning per file on
Python 3.12) and all the files were executed in the same module, 'FlatCAMPostProcessor': a module level name of a
preprocessor file was replaced by the same name of the next file. A file written with 'from appPreProcessor import *'
still gets math from appPreProcessor.
"""

import ast
import glob
import os
import shutil
import sys
import warnings
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import appPreProcessor
from appPreProcessor import AppPreProcTools, PreProc, load_preprocessors

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_DIR = os.path.join(ROOT, 'preprocessors')


def builtin_class_names():
    """The names of the classes defined in the preprocessor files that come with the application."""
    names = set()
    for file in glob.glob(os.path.join(BUILTIN_DIR, '*.py')):
        with open(file, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        names.update(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    return names


def write_user_preprocessor(folder, name, source=None, mark=None):
    """Writes <folder>/<name>.py. Without source: a class <name> whose methods return the module level name MARK."""
    os.makedirs(folder, exist_ok=True)
    if source is None:
        methods = ''.join("    def %s(self, p):\n        return MARK\n" % m
                          for m in sorted(AppPreProcTools.__abstractmethods__))
        source = "from appPreProcessor import AppPreProcTools\n\nMARK = %r\n\n\nclass %s(AppPreProcTools):\n%s" % (
            mark, name, methods)
    with open(os.path.join(folder, name + '.py'), 'w', encoding='utf-8') as f:
        f.write(source)


def load(app):
    """load_preprocessors() and the load_module() deprecation warnings it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = load_preprocessors(app)
    deprecated = [str(w.message) for w in caught
                  if issubclass(w.category, DeprecationWarning) and 'load_module' in str(w.message)]
    return result, deprecated


@pytest.fixture
def registry():
    """The registry is module wide: start empty, then restore it and remove the preprocessor modules."""
    saved = dict(appPreProcessor.preprocessors)
    saved_modules = set(sys.modules)
    appPreProcessor.preprocessors.clear()
    yield appPreProcessor.preprocessors
    appPreProcessor.preprocessors.clear()
    appPreProcessor.preprocessors.update(saved)
    for name in set(sys.modules) - saved_modules:
        if name.startswith('FlatCAMPostProcessor'):
            del sys.modules[name]


@pytest.fixture
def app(tmp_path):
    return SimpleNamespace(data_path=str(tmp_path / 'data'), log=MagicMock())


def test_builtin_folder_is_next_to_the_module():
    assert os.path.normcase(appPreProcessor.builtin_preprocessors_path()) == \
        os.path.normcase(os.path.realpath(BUILTIN_DIR))


def test_builtin_preprocessors_load_from_another_working_directory(registry, app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result, _deprecated = load(app)

    assert result is appPreProcessor.preprocessors
    expected = builtin_class_names()
    assert {'default', 'GRBL_11', 'GRBL_laser', 'Marlin'} <= expected
    assert sorted(expected - set(result)) == []
    for name, pp in result.items():
        assert type(pp).__name__ == name
        assert isinstance(pp, (PreProc, AppPreProcTools))
    app.log.error.assert_not_called()
    assert result['default'].lift_code(SimpleNamespace(z_move=2.0, coords_decimals=4)) == 'G00 Z2.0000'


def test_frozen_build_loads_the_folder_next_to_the_executable(registry, app, tmp_path, monkeypatch):
    # a frozen build: the executable with the preprocessors folder next to it, the modules in lib/library.zip
    build_dir = tmp_path / 'build'
    (build_dir / 'preprocessors').mkdir(parents=True)
    (build_dir / 'lib').mkdir()
    shutil.copy(os.path.join(BUILTIN_DIR, 'default.py'), str(build_dir / 'preprocessors'))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(build_dir / 'FlatCAM.exe'))
    monkeypatch.chdir(build_dir / 'lib')

    result, _deprecated = load(app)

    assert sorted(result) == ['default']
    assert os.path.normcase(appPreProcessor.builtin_preprocessors_path()) == \
        os.path.normcase(os.path.realpath(str(build_dir / 'preprocessors')))


def test_no_load_module_deprecation_warning(registry, app, monkeypatch):
    monkeypatch.chdir(ROOT)
    write_user_preprocessor(os.path.join(app.data_path, 'preprocessors'), 'User_A', mark='A')

    result, deprecated = load(app)

    assert 'User_A' in result and 'default' in result
    assert deprecated == []


def test_user_preprocessor_from_the_data_folder(registry, app, monkeypatch):
    monkeypatch.chdir(ROOT)
    write_user_preprocessor(os.path.join(app.data_path, 'preprocessors'), 'User_A', mark='A')

    result, _deprecated = load(app)

    assert result['User_A'].start_code(None) == 'A'
    assert 'GRBL_11' in result
    app.log.error.assert_not_called()


def test_each_file_keeps_its_own_module_level_names(registry, app, monkeypatch):
    monkeypatch.chdir(ROOT)
    folder = os.path.join(app.data_path, 'preprocessors')
    write_user_preprocessor(folder, 'User_A', mark='A')
    write_user_preprocessor(folder, 'User_B', mark='B')

    result, _deprecated = load(app)

    assert result['User_A'].start_code(None) == 'A'
    assert result['User_B'].start_code(None) == 'B'
    assert type(result['User_A']).__module__ != type(result['User_B']).__module__


def test_star_import_preprocessor_still_gets_math(registry, app, monkeypatch):
    # user copies of the built-in preprocessors of 2020-11 to 2023-05 use math without importing it
    monkeypatch.chdir(ROOT)
    methods = ''.join("    def %s(self, p):\n        return str(math.ceil(2.5))\n" % m
                      for m in sorted(PreProc.__abstractmethods__))
    write_user_preprocessor(os.path.join(app.data_path, 'preprocessors'), 'User_M',
                            source="from appPreProcessor import *\n\n\nclass User_M(PreProc):\n%s" % methods)

    result, _deprecated = load(app)

    assert result['User_M'].start_code(None) == '3'
    app.log.error.assert_not_called()


def test_folders_with_glob_characters_in_the_path(registry, tmp_path, monkeypatch):
    app = SimpleNamespace(data_path=str(tmp_path / 'data [1]'), log=MagicMock())
    write_user_preprocessor(os.path.join(app.data_path, 'preprocessors'), 'User_A', mark='A')
    build_dir = tmp_path / 'FlatCAM [1]'
    (build_dir / 'preprocessors').mkdir(parents=True)
    shutil.copy(os.path.join(BUILTIN_DIR, 'default.py'), str(build_dir / 'preprocessors'))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(build_dir / 'FlatCAM.exe'))
    monkeypatch.chdir(tmp_path)

    result, _deprecated = load(app)

    assert sorted(result) == ['User_A', 'default']


def test_broken_file_is_logged_and_the_others_load(registry, app, monkeypatch):
    monkeypatch.chdir(ROOT)
    write_user_preprocessor(os.path.join(app.data_path, 'preprocessors'), 'Broken',
                            source="raise RuntimeError('broken preprocessor')\n")

    result, _deprecated = load(app)

    app.log.error.assert_called_once()
    assert 'broken preprocessor' in app.log.error.call_args.args[0]
    assert 'default' in result
    assert 'FlatCAMPostProcessor_Broken' not in sys.modules
