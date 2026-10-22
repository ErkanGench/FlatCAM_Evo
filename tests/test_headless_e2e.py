"""flatcam.py --headless in a new process, without a display setting (QT_QPA_PLATFORM not set).

A start of the program takes about 3 seconds. The 2 tests of a shell file share 1 process
(a module fixture). Each other test that checks an exit code has its own process.
"""

import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_headless(args, cwd, stdin=None, timeout=300):
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)
    return subprocess.run([sys.executable, os.path.join(REPO, 'flatcam.py'), '--headless'] + args, cwd=str(cwd),
                          input=stdin, capture_output=True, text=True, timeout=timeout, env=env)


EXAMPLE_GERBER = os.path.join(REPO, 'assets', 'examples', 'files', 'test.gbr')


@pytest.fixture(scope='module')
def shellfile_run(tmp_path_factory):
    """1 run with --shellfile and --shellvar: it saves a project and makes G-code from a Gerber. Used by 2 tests."""
    folder = tmp_path_factory.mktemp('shellfile_run')
    shutil.copy(EXAMPLE_GERBER, folder / 'test.gbr')
    script = (
        'new_geometry g\n'
        'save_project $shellvar_0\n'
        'open_gerber test.gbr -outname board\n'
        'isolate board -dia 0.2 -outname iso\n'
        'cncjob iso -dia 0.2 -z_cut -0.1 -z_move 2 -feedrate 100 -outname cnc\n'
        'write_gcode cnc out.nc\n'
    )
    (folder / 'job.FlatScript').write_text(script)
    result = run_headless(['--shellfile=job.FlatScript', '--shellvar=var.FlatPrj'], folder)
    return folder, result


def test_a_command_writes_a_project(tmp_path):
    result = run_headless(['--command=new_geometry g; save_project out.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'out.FlatPrj').is_file()


def test_a_failed_command_gives_exit_code_1(tmp_path):
    result = run_headless(['--command=no_such_command'], tmp_path)
    assert result.returncode == 1
    assert 'invalid command name "no_such_command"' in result.stderr


def test_shellfile_with_a_relative_name_and_shellvar(shellfile_run):
    folder, result = shellfile_run
    assert result.returncode == 0, result.stderr
    assert (folder / 'var.FlatPrj').is_file()


def test_the_prompt_reads_stdin(tmp_path):
    result = run_headless([], tmp_path, stdin='puts hello\nnew_geometry g\nsave_project r.FlatPrj\n')
    assert result.returncode == 0, result.stderr
    assert 'hello' in result.stdout
    assert (tmp_path / 'r.FlatPrj').is_file()


def test_gerber_to_gcode(shellfile_run):
    folder, result = shellfile_run
    assert result.returncode == 0, result.stderr + result.stdout
    gcode = (folder / 'out.nc').read_text()
    moves = [line for line in gcode.splitlines() if line.startswith(('G01', 'G1 ')) and 'X' in line]
    assert len(moves) > 10
