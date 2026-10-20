"""flatcam.py --headless in a new process, without a display setting (QT_QPA_PLATFORM not set)."""

import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_headless(args, cwd, stdin=None, timeout=300):
    env = dict(os.environ)
    env.pop('QT_QPA_PLATFORM', None)
    return subprocess.run([sys.executable, os.path.join(REPO, 'flatcam.py'), '--headless'] + args, cwd=str(cwd),
                          input=stdin, capture_output=True, text=True, timeout=timeout, env=env)


def test_a_command_writes_a_project(tmp_path):
    result = run_headless(['--command=new_geometry g; save_project out.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'out.FlatPrj').is_file()


EXAMPLE_GERBER = os.path.join(REPO, 'assets', 'examples', 'files', 'test.gbr')


def test_nothing_from_the_shell_banner_or_the_log_debug_reaches_stdout(tmp_path):
    result = run_headless(['--command=puts hello'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'hello\n'


def test_a_failed_command_gives_exit_code_1(tmp_path):
    result = run_headless(['--command=no_such_command'], tmp_path)
    assert result.returncode == 1
    assert 'invalid command name "no_such_command"' in result.stderr


def test_exit_n(tmp_path):
    result = run_headless(['--command=exit 3'], tmp_path)
    assert result.returncode == 3, result.stderr


def test_quit_app_stops_the_script(tmp_path):
    result = run_headless(['--command=quit_app; new_geometry g; save_project after.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / 'after.FlatPrj').exists()


def test_shellfile_with_a_relative_name_and_shellvar(tmp_path):
    (tmp_path / 'job.FlatScript').write_text('new_geometry g\nsave_project $shellvar_0\n')
    result = run_headless(['--shellfile=job.FlatScript', '--shellvar=var.FlatPrj'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'var.FlatPrj').is_file()


def test_the_prompt_reads_stdin(tmp_path):
    result = run_headless([], tmp_path, stdin='puts hello\nnew_geometry g\nsave_project r.FlatPrj\n')
    assert result.returncode == 0, result.stderr
    assert 'hello' in result.stdout
    assert (tmp_path / 'r.FlatPrj').is_file()


def test_gerber_to_gcode(tmp_path):
    shutil.copy(EXAMPLE_GERBER, tmp_path / 'test.gbr')
    script = (
        'open_gerber test.gbr -outname board\n'
        'isolate board -dia 0.2 -outname iso\n'
        'cncjob iso -dia 0.2 -z_cut -0.1 -z_move 2 -feedrate 100 -outname cnc\n'
        'write_gcode cnc out.nc\n'
    )
    (tmp_path / 'job.FlatScript').write_text(script)
    result = run_headless(['--shellfile=job.FlatScript'], tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
    gcode = (tmp_path / 'out.nc').read_text()
    moves = [line for line in gcode.splitlines() if line.startswith(('G01', 'G1 ')) and 'X' in line]
    assert len(moves) > 10
