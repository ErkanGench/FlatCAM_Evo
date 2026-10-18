"""
Run a Qt test in a new process when the test process holds many widgets.

A style or stylesheet change on the QApplication restyles every widget of the process. In the full suite the
earlier test modules leave many widgets alive, so such a test took 26 s to 28 s instead of 0.2 s alone. A test that
changes the application style calls run_in_clean_process() first: in a crowded process it runs itself in a new
process (about 2 s) and passes only if that run passes.
"""

import os
import subprocess
import sys
from pathlib import Path

from PyQt6 import QtWidgets

ROOT = Path(__file__).resolve().parents[1]
CROWDED_WIDGETS = 100
SUBPROCESS_ENV = 'FLATCAM_QT_CLEAN_PROCESS'


def crowded():
    """True when the process holds many widgets and is not already a clean process started for a test."""
    app = QtWidgets.QApplication.instance()
    return (app is not None and len(app.allWidgets()) > CROWDED_WIDGETS
            and not os.environ.get(SUBPROCESS_ENV))


def run_pytest(node_id):
    """Run a pytest node in a new process; return (return code, output)."""
    done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:warnings', node_id],
                          cwd=ROOT, env=dict(os.environ, **{SUBPROCESS_ENV: '1'}),
                          capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout + done.stderr


def run_in_clean_process(test):
    """
    In a crowded process, run this unittest test in a new process and check that it passes.

    :param test:    the unittest.TestCase instance of the running test
    :return:        True when the test ran in a new process (the caller returns), False when it must run here
    """
    if not crowded():
        return False
    module = sys.modules[type(test).__module__]
    node_id = '%s::%s::%s' % (Path(module.__file__).resolve(), type(test).__name__, test._testMethodName)
    returncode, output = run_pytest(node_id)
    test.assertEqual(returncode, 0, output)
    return True
