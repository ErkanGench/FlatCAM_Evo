import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestQtPlatformSetup(unittest.TestCase):
    def test_platform_default_and_explicit_override(self):
        conftest = Path(__file__).with_name('conftest.py')
        # One interpreter for both cases: the conftest imports appMain, which is slow and cached after the first run.
        script = """
import os
import runpy
import sys

for setting in (None, 'offscreen'):
    os.environ.pop('QT_QPA_PLATFORM', None)
    if setting is not None:
        os.environ['QT_QPA_PLATFORM'] = setting
    runpy.run_path(sys.argv[1])
    expected = setting or ('windows' if sys.platform == 'win32' else '')
    assert os.environ.get('QT_QPA_PLATFORM') == (expected or None), os.environ.get('QT_QPA_PLATFORM')
    if sys.platform == 'win32' and setting is None:
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        assert app.platformName() == expected, app.platformName()
"""
        env = os.environ.copy()
        env.pop('QT_QPA_PLATFORM', None)
        result = subprocess.run([sys.executable, '-c', script, str(conftest)],
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
