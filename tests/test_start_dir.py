"""
Relative file names are relative to the folder FlatCAM was started from, not to the application folder it chdir()s into,
unless the user moved the process with set_path or the Tcl cd.

Windows paths are also tested on the other platforms with ntpath (the tests named ..._emulated); the tests that need the
real platform are skipped elsewhere.
"""

import importlib
import inspect
import ntpath
import os
import pkgutil
import re
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import tclCommands
from tclCommands.TclCommand import TclCommand
from tclCommands.TclCommandOpenGerber import TclCommandOpenGerber
from tclCommands.TclCommandSetPath import TclCommandSetPath
from appCommon import StartDir
from appCommon.StartDir import base_dir, compute_start_dir, resolve_existing_paths, resolve_user_path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.abspath(os.sep + 'home' + os.sep + 'user')

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason="needs the Windows path rules")
not_windows = pytest.mark.skipif(sys.platform == 'win32', reason="POSIX paths")


def same_folder(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


@pytest.fixture
def in_app_folder(monkeypatch):
    """the state of the running application: the process is in the application folder, the start folder is HOME"""
    monkeypatch.setattr(StartDir, 'START_DIR', HOME)
    monkeypatch.chdir(StartDir.APP_DIR)


@pytest.fixture
def windows_paths(monkeypatch):
    """StartDir with the path rules of Windows, on any platform"""
    monkeypatch.setattr(StartDir, 'os', SimpleNamespace(path=ntpath, getcwd=os.getcwd, environ=os.environ, sep='\\'))


def _all_commands():
    found = {}
    for module_info in pkgutil.walk_packages(tclCommands.__path__, 'tclCommands.'):
        module = importlib.import_module(module_info.name)
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, TclCommand) and cls.__module__ == module_info.name:
                found[name] = cls
    return found


def _path_commands():
    """(class name, the name of its file argument) for every command that has one"""
    result = []
    for name, cls in sorted(_all_commands().items()):
        for key in list(cls.arg_names) + list(cls.option_types):
            if key in cls.path_args:
                result.append((name, key))
    return result


def _command(cls):
    command = cls.__new__(cls)
    command.raise_tcl_error = Mock(side_effect=AssertionError)
    return command


class TestComputeStartDir:
    app_dir = os.path.join(HOME, 'FlatCAM.app', 'Contents', 'Frameworks')

    def test_normal_folder_is_kept(self):
        cwd = os.path.join(HOME, 'boards')
        assert compute_start_dir(cwd, self.app_dir, frozen=False, home=HOME) == cwd
        assert compute_start_dir(cwd, self.app_dir, frozen=True, home=HOME) == cwd

    def test_unreadable_working_directory_gives_home(self):
        assert compute_start_dir(None, self.app_dir, frozen=False, home=HOME) == HOME

    def test_root_gives_home(self):
        # a packaged application started from the Finder / Dock starts in the root folder
        assert compute_start_dir(os.path.abspath(os.sep), self.app_dir, frozen=True, home=HOME) == HOME

    def test_packaged_application_started_inside_itself_gives_home(self):
        assert compute_start_dir(self.app_dir, self.app_dir, frozen=True, home=HOME) == HOME
        assert compute_start_dir(os.path.join(self.app_dir, 'assets'), self.app_dir, frozen=True, home=HOME) == HOME

    def test_source_checkout_started_from_its_own_folder_is_kept(self):
        assert compute_start_dir(self.app_dir, self.app_dir, frozen=False, home=HOME) == self.app_dir

    def test_a_folder_inside_the_windows_folder_gives_home(self):
        # some launchers start in C:\Windows\System32, where the user cannot write
        system_root = os.path.join(HOME, 'Windows')
        cwd = os.path.join(system_root, 'System32')
        assert compute_start_dir(cwd, self.app_dir, frozen=True, home=HOME, system_root=system_root) == HOME
        assert compute_start_dir(system_root, self.app_dir, frozen=False, home=HOME, system_root=system_root) == HOME

class TestWindowsPathsEmulated:
    """the rules of Windows paths, run with ntpath on every platform"""

    app_dir = 'C:\\Program Files\\FlatCAM'
    home = 'C:\\Users\\me'

    def test_the_drive_root_gives_home(self, windows_paths):
        assert compute_start_dir('C:\\', self.app_dir, frozen=True, home=self.home) == self.home

    def test_a_unc_share_root_gives_home(self, windows_paths):
        assert compute_start_dir('\\\\server\\share\\', self.app_dir, frozen=True, home=self.home) == self.home

    def test_a_relative_name_is_joined_to_a_unc_folder(self, windows_paths):
        folder = '\\\\server\\share\\proj'
        assert resolve_user_path('board.gtl', start_dir=folder) == folder + '\\board.gtl'

@not_windows
class TestPosixLaunchers:
    def test_an_appimage_mount_is_the_application_folder(self):
        app_dir = '/tmp/.mount_FlatCAMab12cd/usr/lib/flatcam'
        assert compute_start_dir(app_dir, app_dir, frozen=True, home=HOME) == HOME
        assert compute_start_dir(app_dir + '/assets', app_dir, frozen=True, home=HOME) == HOME

    def test_a_launcher_that_starts_in_the_root_folder_gives_home(self):
        assert compute_start_dir('/', '/opt/flatcam', frozen=True, home=HOME) == HOME

class TestResolveUserPath:
    def test_relative_name_gets_the_start_folder(self):
        assert resolve_user_path('out.nc', start_dir=HOME) == os.path.join(HOME, 'out.nc')
        assert resolve_user_path(os.path.join('sub', 'out.nc'), start_dir=HOME) == os.path.join(HOME, 'sub', 'out.nc')

class TestResolveExistingPaths:
    def test_files_that_exist_are_made_absolute_and_the_other_words_stay(self, tmp_path):
        (tmp_path / 'board.gtl').write_text('M02*\n')
        assert resolve_existing_paths(['board.gtl', 'quit', 'missing.drl'], start_dir=str(tmp_path)) == [
            str(tmp_path / 'board.gtl'), 'quit', 'missing.drl']

class TestBaseDir:
    """set_path and the Tcl cd move the process: the relative names follow it"""

    def test_in_the_application_folder_it_is_the_start_folder(self, in_app_folder):
        assert base_dir() == HOME

    def test_the_tcl_cd_changes_it(self, in_app_folder, tmp_path):
        tkinter = pytest.importorskip('tkinter')
        tkinter.Tcl().call('cd', str(tmp_path))   # the folder of a process is shared by every interpreter
        assert same_folder(base_dir(), tmp_path)

    def test_set_path_then_open_gerber(self, in_app_folder, tmp_path):
        # the pattern of many scripts: set_path <folder>, then the names relative to it
        tkinter = pytest.importorskip('tkinter')
        app = SimpleNamespace(shell=SimpleNamespace(tcl=tkinter.Tcl()), options={}, inform_shell=Mock())
        set_path = _command(TclCommandSetPath)
        set_path.app = app
        args, unnamed = set_path.check_args((str(tmp_path),))

        set_path.execute(args, unnamed)

        assert app.options['global_tcl_path'] == str(tmp_path).replace('\\', '/')
        args, _ = _command(TclCommandOpenGerber).check_args(('board.gtl',))
        assert same_folder(args['filename'], tmp_path / 'board.gtl')

    def test_a_relative_set_path_is_relative_to_the_start_folder_and_then_to_the_new_one(self, in_app_folder, tmp_path,
                                                                                         monkeypatch):
        tkinter = pytest.importorskip('tkinter')
        (tmp_path / 'one' / 'two').mkdir(parents=True)
        monkeypatch.setattr(StartDir, 'START_DIR', str(tmp_path))
        app = SimpleNamespace(shell=SimpleNamespace(tcl=tkinter.Tcl()), options={}, inform_shell=Mock())
        set_path = _command(TclCommandSetPath)
        set_path.app = app

        for name, want in (('one', tmp_path / 'one'), ('two', tmp_path / 'one' / 'two')):
            args, unnamed = set_path.check_args((name,))
            set_path.execute(args, unnamed)
            assert same_folder(os.getcwd(), want)


class TestTclPathArguments:
    def test_no_command_has_an_unlisted_file_like_argument(self):
        # a new command with a file argument under another name would write into the application folder again
        flag_arguments = {('TclCommandNew', 'keep_scripts')}
        missed = []
        for name, cls in _all_commands().items():
            for key in list(cls.arg_names) + list(cls.option_types):
                if re.search(r'file|path|dir|folder', key, re.I) and key not in cls.path_args \
                        and (name, key) not in flag_arguments:
                    missed.append((name, key))
        assert missed == []

    @pytest.mark.parametrize('command_name,key', _path_commands()[:2])
    def test_relative_name_is_resolved_against_the_start_folder(self, command_name, key, in_app_folder):
        cls = _all_commands()[command_name]
        command = _command(cls)

        if key in cls.arg_names:
            before = list(cls.arg_names)[:list(cls.arg_names).index(key)]
            assert all(cls.arg_names[k] is str for k in before)
            args = ['obj'] * len(before) + ['out.dat']
        else:
            args = ['-%s' % key, 'out.dat']
        named_args, _ = command.check_args(tuple(args))

        assert named_args[key] == os.path.join(HOME, 'out.dat')

    def test_missing_name_is_still_reported(self, in_app_folder):
        command = _command(_all_commands()['TclCommandWriteGCode'])
        command.raise_tcl_error = Mock()

        named_args, _ = command.check_args(('obj',))

        assert 'filename' not in named_args
        command.raise_tcl_error.assert_called_once_with("Missing required argument 'filename'.")

class TestShellfileOption:
    """appMain parses the command line when the class is defined: run it in a new interpreter."""

    CODE = textwrap.dedent("""
        import sys
        sys.path.insert(0, %r)
        import appMain
        print('SHELLFILE=' + appMain.App.cmd_line_shellfile)
        print('ARGS=' + repr(appMain.App.args))
    """) % REPO

    def _run(self, cwd, *options):
        # appMain takes about 10 s to import on Windows
        return subprocess.run([sys.executable, '-c', self.CODE, *options], cwd=cwd, capture_output=True, text=True,
                              timeout=300)

    def test_relative_name_becomes_absolute(self, tmp_path):
        (tmp_path / 'job.FlatScript').write_text('# nothing\n')
        run = self._run(str(tmp_path), '--shellfile=job.FlatScript')
        assert run.returncode == 0, run.stderr
        shellfile = [line for line in run.stdout.splitlines() if line.startswith('SHELLFILE=')][0]
        assert os.path.realpath(shellfile[len('SHELLFILE='):]) == os.path.realpath(str(tmp_path / 'job.FlatScript'))
        assert os.path.isabs(shellfile[len('SHELLFILE='):])

    def test_missing_file_ends_the_program_before_anything_starts(self, tmp_path):
        run = self._run(str(tmp_path), '--shellfile=missing.FlatScript')
        assert run.returncode == 2
        assert 'missing.FlatScript' in run.stderr
        assert 'SHELLFILE=' not in run.stdout

class TestFileArguments:
    """The files to open that are given as arguments on the command line."""

    def test_relative_file_becomes_absolute_and_keywords_stay(self, tmp_path):
        (tmp_path / 'board.gtl').write_text('M02*\n')
        run = TestShellfileOption()._run(str(tmp_path), 'board.gtl', 'quit', 'missing.drl')
        assert run.returncode == 0, run.stderr
        line = [line for line in run.stdout.splitlines() if line.startswith('ARGS=')][0]
        args = eval(line[len('ARGS='):])
        assert os.path.realpath(args[0]) == os.path.realpath(str(tmp_path / 'board.gtl'))
        assert os.path.isabs(args[0])
        assert args[1:] == ['quit', 'missing.drl']
