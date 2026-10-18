"""Calibrated dispensing: real geometry, volume arithmetic, controller output and UI."""
import copy
import math
import re
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

from shapely import LineString, Point, Polygon, box
from shapely.ops import unary_union

from tests.test_solderpaste import make_app, make_job, make_tool
from appPlugins.ToolSolderPaste import SolderPaste
from appCommon.solderpaste import parse_numbers, extract_pads, pad_paths, parameters, generate_program


def settings(**kwargs):
    data = copy.deepcopy(make_app().options)
    data.update({
        'tools_solderpaste_volume_mode': 'Thickness',
        'tools_solderpaste_placement': 'Auto',
        'tools_solderpaste_controller': 'Mach3',
        'tools_solderpaste_drive': 'Motor',
        'tools_solderpaste_thickness': 0.1,
        'tools_solderpaste_flow_rate': 0.01,
        'tools_solderpaste_overlap': 30.0,
        'tools_solderpaste_dot_dia': 0.2,
        'tools_solderpaste_z_travel': 2.0,
        'tools_solderpaste_z_toolchange': 5.0,
        'tools_solderpaste_z_rise': False,
        'tools_solderpaste_prime': 0.0,
        'tools_solderpaste_dwellrev': 0.1,
    })
    data.update({'tools_solderpaste_' + name: value for name, value in kwargs.items()})
    return data


def program(data, paths=None, volumes=None, units='MM'):
    job = make_job()
    job.units = units
    tool = {'data': data, 'tooldia': 0.3,
            'solid_geometry': paths or [LineString([(1, 1), (2, 1)])],
            'dispense_volumes': volumes or [0.1]}
    return generate_program(job, tool, is_first=True)


class CalibratedPasteTests(unittest.TestCase):
    def test_plugin_ui_and_preferences_round_trip(self):
        from PyQt6 import QtWidgets, QtGui
        from appPlugins.ToolSolderPaste import SolderUI
        from appGUI.preferences.tools.ToolsSolderpastePrefGroupUI import ToolsSolderpastePrefGroupUI
        from appGUI.preferences.PreferencesUIManager import PreferencesUIManager
        self.__class__.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        app = make_app()
        app.resource_location = 'assets/resources'
        app.collection = QtGui.QStandardItemModel()
        parent = QtWidgets.QWidget()
        ui = SolderUI(QtWidgets.QVBoxLayout(parent), app, SimpleNamespace(on_rmb_combo=Mock()))
        fields = ui.calibration.fields
        fields['tools_solderpaste_volume_mode'].set_value('Thickness')
        self.assertFalse(ui.dwellfwd_entry.isEnabled())
        self.assertFalse(ui.frz_dispense_entry.isEnabled())
        self.assertFalse(ui.pp_combo.isEnabled())
        fields['tools_solderpaste_z_rise'].set_value(True)
        self.assertTrue(ui.frz_dispense_entry.isEnabled())
        fields['tools_solderpaste_drive'].set_value('Stepper')
        self.assertFalse(ui.speedfwd_entry.isEnabled())
        prefs = ToolsSolderpastePrefGroupUI(app)
        prefs.pp_combo.set_value(app.options['tools_solderpaste_pp'])
        self.assertEqual(prefs.pp_combo.get_value(), 'Paste_1')
        shell = MagicMock()
        shell.app = app
        shell.plugin_pref_form.tools_solderpaste_group = prefs
        defaults = copy.deepcopy(app.options)
        manager = PreferencesUIManager(defaults, '', shell, Mock(), app.options)
        keys = prefs.calibration.fields.keys()
        self.assertTrue(set(keys).issubset(manager.defaults_form_fields))
        manager.defaults_form_fields = {key: manager.defaults_form_fields[key] for key in keys}
        prefs.calibration.fields['tools_solderpaste_controller'].set_value('LinuxCNC')
        prefs.calibration.fields['tools_solderpaste_thickness'].set_value(0.18)
        manager.defaults_read_form()
        restored = ToolsSolderpastePrefGroupUI(app)
        self.assertEqual(restored.calibration.fields['tools_solderpaste_controller'].get_value(), 'LinuxCNC')
        self.assertAlmostEqual(restored.calibration.fields['tools_solderpaste_thickness'].get_value(), 0.18)

    def test_shared_ui_selection_and_enabled_fields(self):
        from PyQt6 import QtWidgets
        from appGUI.SolderPasteSettings import SolderPasteSettings
        self.__class__.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        ui = SolderPasteSettings(make_app())
        fields = ui.fields
        self.assertEqual([fields['tools_solderpaste_controller'].itemText(i) for i in range(5)],
                         ['Mach3', 'Mach4', 'LinuxCNC', 'GRBL', 'Marlin'])
        fields['tools_solderpaste_volume_mode'].set_value('Thickness')
        self.assertTrue(fields['tools_solderpaste_flow_rate'].isEnabled())
        self.assertFalse(fields['tools_solderpaste_syringe_dia'].isEnabled())
        fields['tools_solderpaste_drive'].set_value('Stepper')
        self.assertFalse(fields['tools_solderpaste_flow_rate'].isEnabled())
        self.assertTrue(fields['tools_solderpaste_syringe_dia'].isEnabled())
        fields['tools_solderpaste_controller'].set_value('Marlin')
        self.assertTrue(fields['tools_solderpaste_marlin_cold'].isEnabled())
        self.assertFalse(fields['tools_solderpaste_mach3_dwell'].isEnabled())
        changed = Mock()
        ui.changed.connect(changed)
        fields['tools_solderpaste_z_rise'].set_value(True)
        changed.assert_called_once_with()

    def test_old_geometry_does_not_inherit_previous_controller_settings(self):
        from PyQt6 import QtWidgets
        from appGUI.SolderPasteSettings import SolderPasteSettings
        self.__class__.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        ui = SolderPasteSettings(make_app())
        ui.fields['tools_solderpaste_mach3_dwell'].set_value('Milliseconds')
        ui.fields['tools_solderpaste_controller'].set_value('Marlin')
        tool = SimpleNamespace(form_fields=ui.fields, app=make_app())
        SolderPaste.set_form(tool, {'tools_solderpaste_volume_mode': 'Legacy'})
        self.assertEqual(ui.fields['tools_solderpaste_mach3_dwell'].get_value(), 'Seconds')
        self.assertEqual(ui.fields['tools_solderpaste_controller'].get_value(), 'Mach3')

    def test_preprocessor_errors_are_not_suppressed_for_paste(self):
        job = make_job()
        job.pp_solderpaste_name = 'Paste_1'

        def broken(p):
            raise ValueError('bad preprocessor')

        with self.assertLogs('solderpaste-test', level='ERROR'), self.assertRaises(ValueError):
            job.doformat(broken)

    def test_legacy_parenthesized_coordinates_are_literal_values(self):
        job = make_job()
        data = settings(volume_mode='Legacy', xy_toolchange='(1, 2)')
        tool = {'tooldia': 0.3, 'data': data, 'solid_geometry': [LineString([(1, 1), (2, 1)])]}
        job.tools = {1: tool}
        code = job.generate_gcode_from_solder_paste_geo(is_first=True, **tool)
        self.assertIn('G01 X1.0000 Y2.0000', code)

    def test_literal_coordinates_and_rejection(self):
        self.assertEqual(parse_numbers('(1.5, -2)', count=2), [1.5, -2.0])
        self.assertEqual(parse_numbers([1, 2], count=2), [1.0, 2.0])
        self.assertEqual(parse_numbers('', count=2, allow_empty=True), [])
        for value in ('1+2, 3', '__import__("os").getcwd()', '[1, float("inf")]',
                      '1, 2, 3', [True, 2], [1, math.nan]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_numbers(value, count=2)

    def test_regions_clear_areas_and_overlaps(self):
        source = SimpleNamespace(tools={
            0: {'geometry': [{'solid': box(0, 0, 4, 4), 'follow': box(0, 0, 4, 4).exterior}]},
            1: {'geometry': [{'solid': box(3, 0, 5, 4), 'follow': Point(4, 2)},
                             {'clear': box(1, 1, 2, 2), 'follow': Point(1.5, 1.5)}]},
            2: {'geometry': [{'solid': box(20, 20, 21, 21), 'follow': LineString([(20, 20), (21, 21)])}]}
        })
        pads = extract_pads(source)
        self.assertEqual(len(pads), 1)
        self.assertAlmostEqual(pads[0].area, 19.0)
        self.assertFalse(pads[0].covers(Point(1.5, 1.5)))

    def test_raster_is_inside_pad_and_preserves_total_volume(self):
        pad = Polygon(box(0, 0, 5, 4).exterior.coords, [box(2, 1, 3, 3).exterior.coords])
        paths, volumes = pad_paths(pad, 0.3, settings(placement='Raster'))
        self.assertGreater(len(paths), 5)
        self.assertAlmostEqual(sum(volumes), pad.area * 0.1)
        for path in paths:
            self.assertTrue(pad.buffer(-0.15).buffer(1e-9).covers(path))
        coverage = unary_union([path.buffer(0.15) for path in paths])
        self.assertLess(pad.buffer(-0.3).difference(coverage).area, 0.01)

    def test_dot_fallback_and_oversized_footprint(self):
        paths, volumes = pad_paths(box(0, 0, 0.25, 0.25), 0.3, settings())
        self.assertEqual(len(paths), 1)
        self.assertIsInstance(paths[0], Point)
        self.assertAlmostEqual(volumes[0], 0.00625)
        self.assertEqual(pad_paths(box(0, 0, 0.1, 0.1), 0.3, settings()), ([], []))

    def test_fixed_volume_and_inches_use_physical_units(self):
        paths, volumes = pad_paths(box(0, 0, 1, 1), 0.1, settings(), units='IN')
        self.assertAlmostEqual(sum(volumes), 25.4 ** 2 * 0.1)
        paths, volumes = pad_paths(box(0, 0, 2, 2), 0.3,
                                  settings(volume_mode='Fixed volume', volume=0.75))
        self.assertAlmostEqual(sum(volumes), 0.75)

    def test_all_motor_controllers_and_dwell_units(self):
        for controller in ('Mach3', 'Mach4', 'LinuxCNC', 'GRBL', 'Marlin'):
            with self.subTest(controller=controller):
                code = program(settings(controller=controller))
                self.assertIn('G90', code)
                self.assertIn('S300', code)
                self.assertNotIn('F1.0000\nG1 Z0.1000', code)
                self.assertIn('PASTE_ON', code)
                self.assertIn('PASTE_OFF', code)
                self.assertIn('G1 X2.0000 Y1.0000 F6.0000', code)
        self.assertIn('G4 P100.0000', program(settings(mach3_dwell='Milliseconds')))
        self.assertIn('G4 S0.1000', program(settings(controller='Marlin')))

    def test_dot_motor_duration_and_no_motion_while_dispensing(self):
        code = program(settings(), paths=[Point(1, 1)], volumes=[0.005])
        self.assertIn('G4 P0.5000', code)
        self.assertIn('PASTE_DOT', code)
        dose = code.split('PASTE_ON')[1].split('PASTE_OFF')[0]
        self.assertNotRegex(dose, r'G1 X')

    def test_stepper_displacement_and_inverse_time(self):
        data = settings(drive='Stepper', axis='A', axis_mode='Rotary', syringe_dia=10,
                        pitch=2, gear_ratio=3, retract=0)
        code = program(data)
        expected = 0.1 / (math.pi * 5 ** 2) / 2 * 3 * 360
        self.assertRegex(code, r'G1 X2\.0000 Y1\.0000 A' + re.escape(f'{expected:.8f}'))
        self.assertIn('G93', code)
        self.assertIn('G94', code)
        self.assertNotRegex(code, r'M0?[34] S')

    def test_marlin_stepper_and_retraction_recovery(self):
        data = settings(controller='Marlin', drive='Stepper', axis='E', axis_mode='Linear',
                        syringe_dia=10, retract=0.02, marlin_cold=True)
        code = program(data, paths=[Point(1, 1), Point(2, 1)], volumes=[0.01, 0.01])
        self.assertIn('M82', code)
        self.assertIn('G92 E0', code)
        self.assertIn('E-', code)
        self.assertNotIn('G93', code)
        self.assertEqual(code.count('PASTE_ON'), 2)

    def test_invalid_settings_fail_before_output(self):
        invalid = [dict(flow_rate=0), dict(calibration=math.nan), dict(overlap=100),
                   dict(drive='Stepper', controller='GRBL'), dict(axis='X', drive='Stepper'),
                   dict(controller='Marlin', drive='Stepper', axis='E', marlin_cold=False),
                   dict(controller='GRBL', grbl_mode='Laser'), dict(z_travel=0.01),
                   dict(controller='Unsupported'), dict(drive='Stepper', syringe_dia=0)]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                program(settings(**changes))

    def test_excess_flow_does_not_silently_overdose(self):
        with self.assertRaisesRegex(ValueError, 'flow|feed'):
            program(settings(flow_rate=100))

    def test_plugin_stores_volume_metadata(self):
        tool = make_tool([box(0, 0, 4, 3)])
        tool.tooltable_tools[1]['data'].update(settings())
        result = SolderPaste.on_create_geo(tool, 'pads', tool.source, use_thread=False)
        self.assertNotEqual(result, 'fail')
        data = tool.objects[0].tools[1]
        self.assertGreater(len(data['solid_geometry']), 1)
        self.assertEqual(len(data['dispense_volumes']), len(data['solid_geometry']))
        self.assertAlmostEqual(sum(data['dispense_volumes']), 1.2)

    def test_core_entry_uses_calibrated_volume(self):
        job = make_job()
        tool = {'tooldia': 0.3, 'data': settings(),
                'solid_geometry': [Point(1, 1)], 'dispense_volumes': [0.005]}
        job.tools = {1: tool}
        code = job.generate_gcode_from_solder_paste_geo(is_first=True, **tool)
        self.assertIn('G4 P0.5000', code)
        parsed = job.gcode_parse(tool_data=tool['data'])
        self.assertTrue(any(item['kind'][0] == 'C' for item in parsed))

    def test_current_controller_and_calibration_apply_without_replanning(self):
        tool = make_tool([box(0, 0, 2, 1)])
        tool.tooltable_tools[1]['data'].update(settings())
        SolderPaste.on_create_geo(tool, 'pads', tool.source, use_thread=False)
        source = tool.objects[0]
        source.obj_options.update(xmin=0, ymin=0, xmax=2, ymax=1)
        original = copy.deepcopy(source.tools)
        tool.tooltable_tools[1]['data'].update(settings(controller='Marlin', flow_rate=0.005))
        jobs = []

        def create(kind, name, initialize, **kwargs):
            job = make_job(tool.app)
            job.kind = 'cncjob'
            result = initialize(job, tool.app)
            if result != 'fail':
                jobs.append(job)
            return result

        tool.new_object = create
        SolderPaste.on_create_gcode(tool, 'paste', source, use_thread=False)
        self.assertTrue(jobs)
        self.assertIn(';Calibrated solder paste: Marlin', jobs[0].gcode)
        self.assertEqual(jobs[0].tools[1]['data']['tools_solderpaste_flow_rate'], 0.005)
        self.assertEqual(source.tools, original)

    def test_motor_volume_from_actual_commands_includes_prime(self):
        data = settings(prime=0.01, calibration=1.2)
        job = make_job()
        job._bed_skew_x = 5.0
        path = LineString([(1, 1), (2, 2), (3, 2)])
        code = generate_program(job, {'tooldia': 0.3, 'data': data,
                                      'solid_geometry': [path], 'dispense_volumes': [0.1]}, True)
        x, y = 0.0, 0.0
        dispensing = False
        elapsed = 0.0
        for line in code.splitlines():
            if line == '(PASTE_ON)':
                dispensing = True
            elif line == '(PASTE_OFF)':
                dispensing = False
            move = re.match(r'G1 X([-\d.]+) Y([-\d.]+) F([\d.]+)', line)
            if move:
                nx, ny, feed = map(float, move.groups())
                if dispensing:
                    elapsed += math.hypot(nx - x, ny - y) * 60 / feed
                x, y = nx, ny
            dwell = re.match(r'G4 P([\d.]+)', line)
            if dwell and dispensing:
                elapsed += float(dwell[1])
        self.assertAlmostEqual(elapsed * 0.01, 0.12, places=5)

    def test_stepper_net_delivery_accounts_for_retract_recovery(self):
        data = settings(drive='Stepper', axis='A', axis_mode='Rotary', syringe_dia=10,
                        pitch=2, gear_ratio=3, retract=0.02, calibration=1.1)
        code = program(data, paths=[Point(1, 1), Point(2, 1)], volumes=[0.05, 0.1])
        final = float(re.findall(r'G1 A([-\d.]+)', code)[-1])
        plunger = final / (360 * 3 / 2) + 0.02
        self.assertAlmostEqual(plunger * math.pi * 25, 0.15 * 1.1, places=7)

    def test_saved_cncjob_restores_paste_role_and_dialect(self):
        job = make_job()
        job.special_group = 'solder_paste_tool'
        job.pp_solderpaste_name = 'Paste_Marlin'
        job.tools = {1: {'tooldia': 0.3, 'type': 'SolderPaste',
                         'data': settings(controller='Marlin'),
                         'solid_geometry': [Point(1, 1)], 'dispense_volumes': [0.01]}}
        saved = job.to_dict()
        restored = make_job()
        restored.from_dict(saved)
        self.assertEqual(getattr(restored, 'special_group', None), 'solder_paste_tool')
        self.assertEqual(restored.pp_solderpaste_name, 'Paste_Marlin')
        self.assertEqual(restored.tools[1]['dispense_volumes'], [0.01])

    def test_old_paste_job_restores_role_from_tool_metadata(self):
        job = make_job()
        job.tools = {1: {'tooldia': 0.3, 'type': 'SolderPaste',
                         'data': {'tools_solderpaste_pp': 'Paste_GRBL'}, 'solid_geometry': []}}
        restored = make_job()
        restored.from_dict(job.to_dict())
        self.assertEqual(getattr(restored, 'special_group', None), 'solder_paste_tool')
        self.assertEqual(restored.pp_solderpaste_name, 'Paste_GRBL')

    def test_application_objects_restore_paste_metadata_through_actual_mro(self):
        from PyQt6 import QtCore
        from camlib import Geometry, CNCjob
        from appObjects.GeometryObject import GeometryObject
        from appObjects.CNCJobObject import CNCJobObject
        saved = {'tools': {1: {'type': 'SolderPaste', 'data': settings(controller='Marlin')}},
                 'special_group': 'solder_paste_tool', 'pp_solderpaste_name': 'Paste_Marlin'}
        for cls in (GeometryObject, CNCJobObject):
            with self.subTest(cls=cls):
                restored = cls.__new__(cls)
                with patch.object(Geometry, '__init__', return_value=None), \
                        patch.object(CNCjob, '__init__', return_value=None):
                    QtCore.QObject.__init__(restored)
                restored.ser_attrs = ['tools']
                restored.special_group = None
                restored.app = make_app()
                if cls is CNCJobObject:
                    restored.pp_solderpaste_name = None
                restored.from_dict(copy.deepcopy(saved))
                self.assertEqual(restored.special_group, 'solder_paste_tool')
                if cls is CNCJobObject:
                    self.assertEqual(restored.pp_solderpaste_name, 'Paste_Marlin')


if __name__ == '__main__':
    unittest.main()
