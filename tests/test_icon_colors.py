import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtGui, QtWidgets


def write_icon(path, colors):
    image = QtGui.QImage(len(colors), 1, QtGui.QImage.Format.Format_RGBA8888)
    for x, color in enumerate(colors):
        image.setPixelColor(x, 0, QtGui.QColor(*color))
    assert image.save(str(path))


class TestIconColors(unittest.TestCase):
    def test_only_single_color_icons_change_and_remain_recolorable(self):
        from appCommon.IconColors import recolor_icons

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mono = [(102, 173, 199, 255), (51, 87, 100, 128), (0, 0, 0, 0)]
            for name in ('tool.png', 'tool.ico', 'drill16_project.png', 'axis18.png',
                         'settings18.png', 'hud18.png', 'graylight12.png', 'active_static.png', 'red32.png'):
                write_icon(root / name, mono)
            write_icon(root / 'neutral.png', [(227, 233, 237, 255), (110, 114, 116, 64)])
            write_icon(root / 'white.png', [(255, 255, 255, 255)])
            write_icon(root / 'mixed.png', [(255, 0, 0, 255), (0, 255, 0, 255)])
            write_icon(root / 'logo.png', [(255, 0, 0, 255), (255, 255, 255, 255)])
            (root / 'dark_resources').mkdir()
            write_icon(root / 'dark_resources' / 'tool.png', mono)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}

            self.assertEqual(recolor_icons(root, '#aabbcc'), 4)
            for name in ('tool.png', 'tool.ico', 'neutral.png', 'white.png'):
                image = QtGui.QImage(str(root / name))
                self.assertEqual(image.pixelColor(0, 0).name(), '#aabbcc')
            self.assertEqual(QtGui.QImage(str(root / 'tool.png')).pixelColor(1, 0).alpha(), 128)
            self.assertEqual(QtGui.QImage(str(root / 'tool.png')).pixelColor(2, 0).alpha(), 0)
            for path, original in before.items():
                if path.name not in ('tool.png', 'tool.ico', 'neutral.png', 'white.png') or path.parent != root:
                    self.assertEqual(path.read_bytes(), original, path.name)
            self.assertEqual(recolor_icons(root, '#223344'), 4)
            self.assertEqual(QtGui.QImage(str(root / 'tool.png')).pixelColor(0, 0).name(), '#223344')
            self.assertEqual(recolor_icons(root, '#223344'), 0)
            with self.assertRaises(ValueError):
                recolor_icons(root, '#123')

    def test_invalid_image_does_not_change_any_files(self):
        from appCommon.IconColors import recolor_icons

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_icon(root / 'a.png', [(255, 255, 255, 255)])
            (root / 'z.png').write_bytes(b'invalid image')
            original = (root / 'a.png').read_bytes()
            with self.assertRaises(OSError):
                recolor_icons(root, '#66adc7')
            self.assertEqual((root / 'a.png').read_bytes(), original)

    def test_black_and_white_are_supported_and_can_be_recolored_again(self):
        from appCommon.IconColors import recolor_icons

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tool.png'
            write_icon(path, [(255, 255, 255, 255), (128, 128, 128, 64)])
            for color in ('#000000', '#ffffff', '#1f0000', '#66adc7'):
                self.assertEqual(recolor_icons(directory, color), 1)
                image = QtGui.QImage(str(path))
                self.assertEqual(image.pixelColor(0, 0).name(), color)
                self.assertEqual(image.pixelColor(1, 0).alpha(), 64)

    def test_failed_write_restores_previously_changed_icons(self):
        from appCommon.IconColors import recolor_icons, _write_icon

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('a.png', 'b.png'):
                write_icon(root / name, [(255, 255, 255, 255)])
            before = {p: p.read_bytes() for p in root.iterdir()}

            def fail_second(path, data):
                if path.name == 'b.png':
                    raise OSError('Test write failure')
                _write_icon(path, data)

            with patch('appCommon.IconColors._write_icon', side_effect=fail_second):
                with self.assertRaisesRegex(OSError, 'Test write failure'):
                    recolor_icons(root, '#66adc7')
            for path, original in before.items():
                self.assertEqual(path.read_bytes(), original)

    def test_project_tree_uses_protected_copies(self):
        from appObjects.ObjectCollection import ObjectCollection

        root = Path(__file__).resolve().parents[1]
        for filename in ObjectCollection.icon_files.values():
            path = Path(filename)
            self.assertTrue(path.stem.endswith('_project'))
            for folder in (root / 'assets/resources', root / 'assets/resources/dark_resources'):
                self.assertTrue((folder / path.name).is_file(), folder / path.name)

    def test_project_and_status_icons_have_their_own_colors_in_both_themes(self):
        from appObjects.ObjectCollection import ObjectCollection
        from appCommon.IconColors import PROTECTED_ICONS

        expected = {
            'gerber': ('gerber16_project.png', '#66adc7'),
            'excellon': ('excellon16_project.png', '#c92e2e'),
            'cncjob': ('cnc16_project.png', '#4188d9'),
            'geometry': ('geometry16_project.png', '#fc2d2d'),
            'script': ('script16_project.png', '#763dfc'),
            'document': ('notes16_project.png', '#fc963d'),
        }
        files = {name: color for name, color in expected.values()}
        for name in ('axis18.png', 'settings18.png', 'hud18.png'):
            self.assertIn(name, PROTECTED_ICONS)
            files[name] = '#ff6347'
        for kind, (name, color) in expected.items():
            self.assertEqual(Path(ObjectCollection.icon_files[kind]).name, name)
        root = Path(__file__).resolve().parents[1] / 'assets/resources'
        for folder in (root, root / 'dark_resources'):
            for name, color in files.items():
                with self.subTest(folder=folder.name, icon=name):
                    image = QtGui.QImage(str(folder / name))
                    self.assertFalse(image.isNull())
                    colors = Counter(image.pixelColor(x, y).name()
                                     for x in range(image.width()) for y in range(image.height())
                                     if image.pixelColor(x, y).alpha() > 32)
                    self.assertEqual(colors.most_common(1)[0][0], color)


class TestIconColorPreferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_workspace_label_stays_tomato_when_workspace_changes_and_is_hidden(self):
        from appGUI.GUIElements import FCLabel
        from appGUI.PlotCanvas import PlotCanvas

        label = FCLabel('A4', color='tomato')
        app = SimpleNamespace(app_units='MM', options={'global_workspace_orientation': 'p'},
                              ui=SimpleNamespace(wplace_label=label))
        canvas = SimpleNamespace(fcapp=app, pagesize_dict={'A3': (297, 420)},
                                 view=SimpleNamespace(scene=object()), workspace_line=None)
        canvas.delete_workspace = lambda: PlotCanvas.delete_workspace(canvas)
        with patch('appGUI.PlotCanvas.Line', return_value=SimpleNamespace(parent=None)):
            PlotCanvas.draw_workspace(canvas, 'A3')
        self.assertIn('tomato', label.text())
        self.assertIn('A3', label.text())
        canvas.delete_workspace()
        self.assertIn('tomato', label.text())
        self.assertFalse(app.options['global_workspace'])

    def test_black_light_and_white_dark_preferences_round_trip(self):
        from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI
        from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
        from defaults import AppDefaults

        with tempfile.TemporaryDirectory() as directory:
            defaults = AppDefaults(beta=False)
            app = MagicMock(decimals=4, resource_location='assets/resources')
            app.options = dict(defaults.items())
            with patch.object(OptionsGroupUI, 'app', app):
                group = GeneralGUIPrefGroupUI(app)
            ui = MagicMock()
            ui.app = app
            ui.general_pref_form.general_gui_group = group
            manager = PreferencesUIManager(defaults, directory, ui, app.inform, app.options)
            manager.defaults_form_fields = {key: manager.defaults_form_fields[key] for key in
                                            ('global_icon_color_light', 'global_icon_color_dark')}
            group.icon_color_light_entry.set_value('#000000')
            group.icon_color_dark_entry.set_value('#ffffff')
            manager.defaults_read_form()
            manager.save_defaults(silent=True)
            restored = AppDefaults(beta=False)
            restored.load(str(Path(directory) / 'current_defaults.FlatConfig'), app.inform)
            self.assertEqual(restored['global_icon_color_light'], '#000000')
            self.assertEqual(restored['global_icon_color_dark'], '#ffffff')
            group.deleteLater()

    def test_apply_changes_only_selected_theme_saves_and_offers_restart(self):
        from appGUI.preferences.OptionsGroupUI import OptionsGroupUI
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI
        from defaults import AppDefaults

        module = 'appGUI.preferences.general.GeneralGUIPrefGroupUI'
        for restart in (False, True):
            with self.subTest(restart=restart), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'dark_resources').mkdir()
                for path in (root / 'tool.png', root / 'dark_resources/tool.png'):
                    write_icon(path, [(255, 255, 255, 255)])
                light_original = (root / 'tool.png').read_bytes()
                defaults = AppDefaults(beta=False)
                app = MagicMock(decimals=4, resource_location=str(root / 'dark_resources'))
                app.options = dict(defaults.items())
                app.defaults = defaults
                settings = QtCore.QSettings(str(root / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
                with patch.object(OptionsGroupUI, 'app', app), patch(module + '.QSettings', return_value=settings):
                    group = GeneralGUIPrefGroupUI(app)
                group.app = app
                group.icon_color_dark_entry.set_value('#66adc7FF')
                dialog = MagicMock()
                yes = object()
                dialog.addButton.side_effect = [yes, object()]
                dialog.clickedButton.return_value = yes if restart else None
                with patch(module + '.FCMessageBox', return_value=dialog):
                    group.icon_color_dark_apply_btn.click()
                self.assertEqual((root / 'tool.png').read_bytes(), light_original)
                self.assertEqual(QtGui.QImage(str(root / 'dark_resources/tool.png')).pixelColor(0, 0).name(), '#66adc7')
                self.assertEqual(app.options['global_icon_color_dark'], '#66adc7')
                self.assertEqual(defaults['global_icon_color_dark'], '#66adc7')
                app.preferencesUiManager.save_defaults.assert_called_once_with(silent=True)
                self.assertEqual(app.on_app_restart.call_count, int(restart))
                group.deleteLater()

    def test_invalid_color_does_not_save_or_offer_restart(self):
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI

        app = MagicMock()
        group = SimpleNamespace(app=app)
        with patch('appGUI.preferences.general.GeneralGUIPrefGroupUI.FCMessageBox') as dialog:
            GeneralGUIPrefGroupUI.on_icon_color_apply(group, 'light', '#123')
        app.preferencesUiManager.save_defaults.assert_not_called()
        dialog.assert_not_called()
        app.inform.emit.assert_called_once()

    def test_failed_recolor_does_not_save_or_offer_restart(self):
        from appGUI.preferences.general.GeneralGUIPrefGroupUI import GeneralGUIPrefGroupUI

        app = MagicMock(resource_location='assets/resources')
        group = SimpleNamespace(app=app)
        module = 'appGUI.preferences.general.GeneralGUIPrefGroupUI'
        with patch(module + '.recolor_icons', side_effect=OSError('Read-only files')), \
                patch(module + '.FCMessageBox') as dialog:
            GeneralGUIPrefGroupUI.on_icon_color_apply(group, 'light', '#000000')
        app.preferencesUiManager.save_defaults.assert_not_called()
        dialog.assert_not_called()
        app.inform.emit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
