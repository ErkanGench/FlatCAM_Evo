"""Paint output tolerance is stored in mm and converted once for inch geometry."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from test_paint_performance import rest_worker
from test_paint_geometry import PaintGen, storage_of
from defaults import AppDefaults, AppOptions
from shapely import LineString, box


class TestPaintSimplification(unittest.TestCase):
    def test_preference_widget_mapping_and_roundtrip(self):
        from PyQt6 import QtWidgets
        from appGUI.preferences.tools.ToolsPaintPrefGroupUI import ToolsPaintPrefGroupUI
        from appGUI.preferences.PreferencesUIManager import PreferencesUIManager

        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        defaults = AppDefaults()
        group = ToolsPaintPrefGroupUI(SimpleNamespace(decimals=4, options=defaults))
        ui = Mock()
        ui.app.options = AppOptions(version=1, baseline=defaults, defaults=defaults)
        ui.plugin_pref_form.tools_solderpaste_group.calibration.fields = {}
        ui.plugin_eng_pref_form.tools_paint_group = group
        manager = PreferencesUIManager(defaults, '', ui, Mock(), {})
        self.assertIs(manager.defaults_form_fields['tools_paint_final_cleanup'], group.final_cleanup_cb)
        manager.defaults_write_form_field('tools_paint_final_cleanup')
        self.assertFalse(group.final_cleanup_cb.get_value())
        entry = manager.defaults_form_fields['tools_paint_simplification']
        self.assertIs(entry, group.simplification_entry)
        manager.defaults_write_form_field('tools_paint_simplification')
        self.assertEqual(entry.get_value(), 0.01)
        self.assertGreaterEqual(entry.decimals(), 6)
        entry.set_value(0)
        self.assertEqual(entry.get_value(), 0)
        group.deleteLater()

    def test_legacy_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'defaults.json'
            filename.write_text(json.dumps({'units': 'IN'}))
            defaults = AppDefaults()
            defaults.load(str(filename), Mock())
            self.assertEqual(defaults['tools_paint_simplification'], 0.01)
            self.assertIs(defaults['tools_paint_final_cleanup'], False)
            defaults['tools_paint_final_cleanup'] = True
            defaults['tools_paint_simplification'] = 0
            defaults.write(str(filename))
            defaults.load(str(filename), Mock())
            options = AppOptions(version=1, baseline=defaults, defaults=defaults)
            self.assertEqual(options['tools_paint_simplification'], 0)
            self.assertIs(options['tools_paint_final_cleanup'], True)

    def test_normal_and_rest_use_configured_tolerance_in_geometry_units(self):
        for units, scale in (('MM', 1), ('IN', 1 / 25.4)):
            for tolerance in (0, 0.001, 0.02):
                for rest in (False, True):
                    with self.subTest(units=units, tolerance=tolerance, rest=rest):
                        app = SimpleNamespace(abort_flag=False, log=Mock(), inform=Mock(),
                                              proc_container=Mock(), units=units,
                                              options={'tools_paint_simplification': tolerance})
                        worker, initial = rest_worker(SimpleNamespace(app=app), [scale])
                        worker.obj_name = 'paint'
                        worker.paint_tools = initial.tools_storage
                        params = worker._create_params(0, 2, rest, 'paint', None, False)
                        self.assertAlmostEqual(params.simplification_value, tolerance * scale)
                        path = LineString([(scale, scale), (2 * scale, 1.01 * scale),
                                           (3 * scale, scale)])
                        worker._process_polygon = Mock(side_effect=lambda *args: storage_of([path]))
                        output = SimpleNamespace(tools={}, obj_options={})
                        generate = worker._generate_rest_paint_worker if rest else worker._generate_paint_worker
                        result = generate(output, app, params, [scale], [box(0, 0, 6 * scale, 6 * scale)],
                                          None, False)
                        self.assertNotEqual(result, 'fail')
                        actual = output.tools[1]['solid_geometry'][0]
                        expected = path.simplify(tolerance * scale) if tolerance else path
                        self.assertEqual(actual.wkb, expected.wkb)
                        self.assertEqual(len(actual.coords), 2 if tolerance == 0.02 else 3)

    def test_missing_option_uses_factory_tolerance(self):
        worker = PaintGen.__new__(PaintGen)
        worker.obj_name = 'paint'
        worker.paint_tools = {}
        for units, expected in (('MM', 0.01), ('IN', 0.01 / 25.4)):
            worker.app = SimpleNamespace(units=units, options={})
            params = worker._create_params(0, 2, False, 'paint', {}, False)
            self.assertAlmostEqual(params.simplification_value, expected)


if __name__ == '__main__':
    unittest.main()
