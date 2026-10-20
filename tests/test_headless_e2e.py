"""flatcam.py --headless in a new process, without a display setting (QT_QPA_PLATFORM not set)."""

import os
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
