import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from PyQt6 import QtCore, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qt_isolation  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class TestQtStyle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.native_style = cls.app.style().objectName()
        cls.subprocess_result = None
        # every test of this class changes the application style: 1 new process for the whole file
        if qt_isolation.crowded():
            cls.subprocess_result = qt_isolation.run_pytest(__file__)

    def run_in_subprocess(self):
        """True when the tests ran in a new process; then this test passes only if that run passed."""
        if self.subprocess_result is None:
            return False
        returncode, output = self.subprocess_result
        self.assertEqual(returncode, 0, output)
        return True

    def setUp(self):
        if self.subprocess_result is not None:
            return
        self.directory = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(
            str(Path(self.directory.name) / 'style.ini'), QtCore.QSettings.Format.IniFormat)
        self.app.setStyleSheet('')
        self.app.setStyle(self.native_style)
        self.app.setProperty('flatcam_style', None)

    def tearDown(self):
        if self.subprocess_result is not None:
            return
        self.app.setStyleSheet('')
        self.app.setStyle(self.native_style)
        self.app.setProperty('flatcam_style', None)
        self.settings.sync()
        del self.settings
        self.directory.cleanup()

    def startup(self):
        # Run the actual startup style block without launching the CAM application.
        source = (ROOT / 'flatcam.py').read_text(encoding='utf-8')
        block = source.split('    # apply style\n', 1)[1].split('    if settings.contains("font_size"):', 1)[0]
        exec(compile(textwrap.dedent(block), 'flatcam.py', 'exec'), {
            'app': self.app, 'QtWidgets': QtWidgets,
            'QSettings': lambda *args: self.settings})

    def test_startup_restores_names_and_handles_legacy_or_invalid_values(self):
        if self.run_in_subprocess():
            return
        keys = QtWidgets.QStyleFactory.keys()
        for saved, expected in [('Fusion', 'Fusion'), ('fUsIoN', 'Fusion'),
                                (str(keys.index('Fusion')), 'Fusion'),
                                ('999', self.native_style), ('-1', self.native_style),
                                ('missing-style', self.native_style), (None, self.native_style)]:
            with self.subTest(saved=saved):
                self.app.setStyle(self.native_style)
                self.settings.clear()
                if saved is not None:
                    self.settings.setValue('style', saved)
                self.startup()
                self.assertEqual(self.app.style().objectName().lower(), expected.lower())
                self.assertEqual(self.app.property('flatcam_style').lower(), expected.lower())
                if saved is not None:
                    self.assertEqual(self.settings.value('style').lower(), expected.lower())

if __name__ == '__main__':
    unittest.main()
