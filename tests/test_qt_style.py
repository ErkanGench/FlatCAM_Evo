import ast
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from PyQt6 import QtCore, QtWidgets


ROOT = Path(__file__).resolve().parents[1]


class TestQtStyle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.native_style = cls.app.style().objectName()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(
            str(Path(self.directory.name) / 'style.ini'), QtCore.QSettings.Format.IniFormat)
        self.app.setStyleSheet('')
        self.app.setStyle(self.native_style)
        self.app.setProperty('flatcam_style', None)

    def tearDown(self):
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

    def test_preferences_keep_selection_under_stylesheet_and_save_name(self):
        self.settings.setValue('style', 'Fusion')
        self.startup()
        self.app.setStyleSheet('QWidget { color: white; }')
        self.assertEqual(self.app.style().objectName(), '')
        source = (ROOT / 'appGUI/preferences/general/GeneralGUIPrefGroupUI.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        group = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        block = 'self.style_combo = ' + source.split('        self.style_combo = ', 1)[1]
        block = block.split('        grid0.addWidget(self.style_label', 1)[0]
        style_nodes = ast.parse(textwrap.dedent('        ' + block)).body
        handler = next(node for node in group.body if getattr(node, 'name', '') == 'handle_style')
        handler.decorator_list = []
        ui = SimpleNamespace()
        namespace = {'self': ui, 'QtWidgets': QtWidgets, 'QtCore': QtCore,
                     'FCComboBox': QtWidgets.QComboBox, 'QSettings': lambda *args: self.settings}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(ROOT), 'exec'), namespace)
        ui.handle_style = namespace['handle_style']
        exec(compile(ast.Module(body=style_nodes, type_ignores=[]), str(ROOT), 'exec'), namespace)
        self.assertEqual(ui.style_combo.currentText(), 'Fusion')
        selected = ui.style_combo.itemText(0)
        ui.style_combo.textActivated.emit(selected)
        self.assertEqual(self.settings.value('style'), selected)
        self.assertEqual(self.app.property('flatcam_style'), selected)
        self.app.setStyleSheet('')
        self.app.setStyle(self.native_style)
        self.startup()
        self.assertEqual(self.app.style().objectName().lower(), selected.lower())


if __name__ == '__main__':
    unittest.main()
