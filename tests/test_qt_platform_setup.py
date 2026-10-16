import os
import subprocess
import sys
import unittest
from pathlib import Path


class TestQtPlatformSetup(unittest.TestCase):
    def test_platform_default_and_explicit_override(self):
        conftest = Path(__file__).with_name('conftest.py')
        script = """
import os
import runpy
import sys

runpy.run_path(sys.argv[1])
expected = sys.argv[2]
assert os.environ.get('QT_QPA_PLATFORM') == (expected or None), os.environ.get('QT_QPA_PLATFORM')
if sys.platform == 'win32':
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    assert app.platformName() == expected, app.platformName()
"""
        for setting in (None, 'offscreen'):
            with self.subTest(setting=setting):
                env = os.environ.copy()
                env.pop('QT_QPA_PLATFORM', None)
                if setting is not None:
                    env['QT_QPA_PLATFORM'] = setting
                expected = setting or ('windows' if sys.platform == 'win32' else '')
                result = subprocess.run(
                    [sys.executable, '-c', script, str(conftest), expected],
                    env=env, capture_output=True, text=True, timeout=60
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
