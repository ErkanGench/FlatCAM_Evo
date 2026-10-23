"""Optional live GRBL precision probing regressions."""
import unittest
from unittest.mock import ANY
import test_levelling_audit as audit
from test_levelling_audit import FakeGrbl, emitted, run_worker


class PrecisionGrbl(FakeGrbl):
    def __init__(self, offset=(0.0, 0.0, 0.0), coarse=-0.1, fine=-0.12, **kwargs):
        super().__init__(**kwargs)
        self.offset = offset
        self.coarse = coarse
        self.fine = fine

    def _answer(self, cmd):
        if cmd == '$#':
            self._send('[G54:%.4f,%.4f,%.4f]' % tuple(self._report(v) for v in self.offset),
                       '[G92:0,0,0]', '[TLO:0]', 'ok')
        elif cmd.startswith('G38.2') and self.fail_probe_at != self.probe_count + 1:
            self.probe_count += 1
            z = self.coarse if self.probe_count % 2 else self.fine
            self._send('[PRB:%.4f,%.4f,%.4f:1]' % (
                self._report(self.x + self.offset[0]), self._report(self.y + self.offset[1]),
                self._report(z + self.offset[2])), 'ok')
        else:
            super()._answer(cmd)


class TestPrecisionProbing(unittest.TestCase):
    def tool(self, fake=None, units='MM'):
        fake = fake or PrecisionGrbl()
        tool, target = audit.TestGrblProbeRun()._tool(fake, units=units)
        tool.ui.precision_probe_cb.get_value.return_value = True
        tool.ui.precision_feed_entry.get_value.return_value = 10.0
        tool.ui.precision_retract_entry.get_value.return_value = 0.5
        return tool, target, fake

    def run_probe(self, tool):
        tool.on_grbl_autolevel()
        run_worker(tool)

    def test_sequence_publishes_only_fine_after_final_retract(self):
        tool, target, fake = self.tool()
        self.run_probe(tool)
        commands = fake.commands()
        self.assertEqual(fake.probe_count, 4)
        probes = [c for c in commands if c.startswith('G38.2')]
        self.assertEqual(probes, ['G38.2 Z-1.0000 F600.0000', 'G38.2 Z-1.0000 F10.0000'] * 2)
        first = commands.index(probes[0])
        fine = commands.index(probes[1])
        self.assertIn('G0 Z0.4000', commands[first + 1:fine])
        self.assertEqual(commands[fine - 1], 'G4 P0')
        lateral = commands.index('G0 X10.0000 Y0.0000')
        self.assertIn('G0 Z2.0000', commands[fine + 1:lateral])
        self.assertNotIn('G91', commands)
        self.assertTrue(tool.al_heights_valid)
        self.assertEqual([v['height'] for v in tool.al_voronoi_geo_storage.values()], [-0.12, -0.12])
        tool._al_on_height_map_ready.assert_called_once_with(target, ANY)
        self.assertEqual(sum(c.args[0]['kind'] == 'probe'
                             for c in tool.al_result_ready_sig.emit.call_args_list), 1)
        self.assertEqual(commands[-2:], ['G0 Z2.0000', 'G4 P0'])

    def test_work_offset_is_removed_before_contact_relative_retract(self):
        tool, target, fake = self.tool(PrecisionGrbl(offset=(10, 20, 30)))
        self.run_probe(tool)
        self.assertIn('G0 Z0.4000', fake.commands())
        self.assertNotIn('G0 Z30.4000', fake.commands())
        self.assertTrue(tool.al_heights_valid)
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['height'], -0.12)

    def test_g55_g92_and_tool_length_offset_are_respected(self):
        tool, target, fake = self.tool(PrecisionGrbl(offset=(6, 9, 16)))
        original = fake._answer

        def answer(cmd):
            if cmd == '$G':
                fake._send('[GC:G0 G55 G17 G21 G90 G94]', 'ok')
            elif cmd == '$#':
                fake._send('[G54:100,100,100]', '[G55:5,7,9]', '[G92:1,2,3]', '[TLO:4]', 'ok')
            else:
                original(cmd)

        fake._answer = answer
        self.run_probe(tool)
        self.assertTrue(tool.al_heights_valid)
        self.assertIn('G0 Z0.4000', fake.commands())
        self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['height'], -0.12)

    def test_unknown_report_unit_value_sends_no_motion(self):
        tool, target, fake = self.tool(PrecisionGrbl(replies={'$$': ['$13=2', 'ok']}))
        self.run_probe(tool)
        self.assertFalse(any(c.startswith('G0') or c.startswith('G38') for c in fake.commands()))
        self.assertFalse(tool.al_heights_valid)

    def test_retract_below_report_resolution_sends_no_motion(self):
        tool, target, fake = self.tool(PrecisionGrbl(report_inches=True))
        tool.ui.precision_retract_entry.get_value.return_value = 0.001
        self.run_probe(tool)
        self.assertFalse(any(c.startswith('G0') or c.startswith('G38') for c in fake.commands()))
        self.assertTrue(any('resolution' in text for text in emitted(tool)))

    def test_inch_units_and_inch_reports(self):
        for units, report_inches in (('MM', True), ('IN', False), ('IN', True)):
            with self.subTest(units=units, report_inches=report_inches):
                tool, target, fake = self.tool(PrecisionGrbl(report_inches=report_inches), units)
                self.run_probe(tool)
                self.assertTrue(tool.al_heights_valid)
                # GRBL's four-place inch report is quantized to 0.00254 mm.
                resolution = 0.00254 if report_inches and units == 'MM' else 0.0001
                self.assertAlmostEqual(tool.al_voronoi_geo_storage[1]['height'], -0.12, delta=resolution / 2)

    def test_fast_or_fine_failure_never_publishes_or_moves_laterally(self):
        for stage in (1, 2):
            with self.subTest(stage=stage):
                tool, target, fake = self.tool(PrecisionGrbl(fail_probe_at=stage))
                self.run_probe(tool)
                self.assertFalse(tool.al_heights_valid)
                self.assertEqual(fake.probe_count, stage)
                self.assertNotIn('G0 X10.0000 Y0.0000', fake.commands())
                self.assertEqual(tool._grbl_recovery, 'needs_reset')
                tool._al_on_height_map_ready.assert_not_called()

    def test_cancel_between_stages_has_no_subsequent_motion(self):
        tool, target, fake = self.tool()

        def stop():
            if fake.commands()[-1:] == ['G0 Z0.4000']:
                tool.on_grbl_stop()

        fake.read_hook = stop
        self.run_probe(tool)
        self.assertEqual(fake.probe_count, 1)
        self.assertEqual(fake.commands()[-1], '!')
        self.assertFalse(tool.al_heights_valid)
        tool._al_on_height_map_ready.assert_not_called()

    def test_invalid_precision_settings_schedule_no_motion(self):
        for field, value in (
                ('precision_feed_entry', 0), ('precision_feed_entry', -1),
                ('precision_feed_entry', 601), ('precision_feed_entry', float('nan')),
                ('precision_feed_entry', 'bad'), ('precision_feed_entry', 0.00001),
                ('precision_retract_entry', 0), ('precision_retract_entry', -1),
                ('precision_retract_entry', float('inf')), ('precision_retract_entry', 4),
                ('precision_retract_entry', 0.00001)):
            with self.subTest(field=field, value=value):
                tool, target, fake = self.tool()
                getattr(tool.ui, field).get_value.return_value = value
                tool.on_grbl_autolevel()
                tool.app.worker_task.emit.assert_not_called()
                self.assertEqual(fake.commands(), [])

    def test_contact_bounds_prevent_unsafe_intermediate_retract(self):
        for coarse in (-1.1, 1.8, 2.1):
            with self.subTest(coarse=coarse):
                tool, target, fake = self.tool(PrecisionGrbl(coarse=coarse))
                self.run_probe(tool)
                self.assertEqual(fake.probe_count, 1)
                self.assertFalse(tool.al_heights_valid)
                self.assertNotIn('G0 X10.0000 Y0.0000', fake.commands())
                self.assertTrue(any('clearance' in text.lower() or 'probe_invalid' in text
                                    for text in emitted(tool)))

    def test_changed_frame_between_touches_holds_without_guessed_retract(self):
        tool, target, fake = self.tool()
        original = fake._answer

        def answer(cmd):
            if cmd == '$G' and fake.probe_count:
                fake._send('[GC:G0 G55 G17 G21 G90 G94]', 'ok')
            else:
                original(cmd)

        fake._answer = answer
        self.run_probe(tool)
        self.assertEqual(fake.probe_count, 1)
        self.assertNotIn('G0 Z0.4000', fake.commands())
        self.assertEqual(tool._grbl_recovery, 'needs_reset')
        self.assertFalse(tool.al_heights_valid)

    def test_off_path_ignores_precision_values(self):
        tool, target, fake = self.tool()
        tool.ui.precision_probe_cb.get_value.return_value = False
        tool.ui.precision_feed_entry.get_value.return_value = 'bad'
        self.run_probe(tool)
        self.assertEqual(fake.probe_count, 2)
        self.assertNotIn('G0 Z0.4000', fake.commands())
        self.assertTrue(tool.al_heights_valid)


    def test_settings_convert_units_without_losing_calibration(self):
        tool, target, fake = self.tool(units='IN')
        target.obj_options.update(tools_al_precision_probe=True, tools_al_precision_feed=12.7,
                                  tools_al_precision_retract=0.762, tools_al_precision_units='MM')
        before = dict(target.obj_options)
        tool._restore_al_precision(target)
        self.assertAlmostEqual(tool.ui.precision_feed_entry.set_value.call_args.args[0], 0.5)
        self.assertAlmostEqual(tool.ui.precision_retract_entry.set_value.call_args.args[0], 0.03)
        self.assertEqual(target.obj_options, before)

    def test_real_controls_restore_a_b_a_without_signals_or_calibration_writes(self):
        from appGUI.GUIElements import FCCheckBox, FCDoubleSpinner

        tool, target, fake = self.tool()
        target.is_segmented_gcode = True
        target.obj_options.update(type='Geometry', tools_al_precision_probe=True,
                                  tools_al_precision_feed=7.25, tools_al_precision_retract=0.35,
                                  tools_al_precision_units='MM')
        tool.ui.precision_probe_cb = FCCheckBox('Precision')
        tool.ui.precision_feed_entry = FCDoubleSpinner()
        tool.ui.precision_retract_entry = FCDoubleSpinner()
        for widget in (tool.ui.precision_feed_entry, tool.ui.precision_retract_entry):
            widget.set_precision(4)
            widget.set_range(0.0001, 910000)
            widget.valueChanged.connect(tool.on_precision_probe_changed)
        tool.ui.precision_probe_cb.toggled.connect(tool.on_precision_probe_changed)
        other = audit.TestTargetOwnership.target('other')
        originals = [dict(obj.obj_options) for obj in (target, other)]
        for obj, enabled, feed, retract in ((target, True, 7.25, 0.35),
                                            (other, False, 10.0, 0.5),
                                            (target, True, 7.25, 0.35)):
            tool.app.collection.get_by_name.return_value = obj
            tool._restore_al_precision(obj)
            self.assertEqual(tool.ui.precision_probe_cb.get_value(), enabled)
            self.assertEqual(tool.ui.precision_feed_entry.get_value(), feed)
            self.assertEqual(tool.ui.precision_retract_entry.get_value(), retract)
            self.assertEqual(tool.ui.precision_feed_entry.isEnabled(), enabled)
        self.assertEqual([obj.obj_options for obj in (target, other)], originals)

    def test_worker_uses_captured_settings_not_changed_widgets(self):
        tool, target, fake = self.tool()
        tool.on_grbl_autolevel()
        tool.ui.precision_feed_entry.get_value.side_effect = AssertionError('worker read UI')
        tool.ui.precision_retract_entry.get_value.side_effect = AssertionError('worker read UI')
        run_worker(tool)
        self.assertTrue(tool.al_heights_valid)
        self.assertIn('G38.2 Z-1.0000 F10.0000', fake.commands())

    def test_invalid_fine_measurements_never_publish(self):
        for record in ('[PRB:0,0,-0.12:0]', '[PRB:nan,0,0:1]', '[PRB:0,0,-2:1]',
                       '[PRB:0,0,0.8:1]', '[PRB:10,0,-0.12:1]', '',
                       '[PRB:0,0,-0.12:1]\n[PRB:0,0,-0.12:1]'):
            with self.subTest(record=record):
                tool, target, fake = self.tool()
                original = fake._answer

                def answer(cmd):
                    if cmd.startswith('G38.2') and fake.probe_count == 1:
                        fake.probe_count += 1
                        fake._send(record, 'ok')
                    else:
                        original(cmd)

                fake._answer = answer
                self.run_probe(tool)
                self.assertFalse(tool.al_heights_valid)
                self.assertEqual(fake.probe_count, 2)
                self.assertNotIn('G0 X10.0000 Y0.0000', fake.commands())
                tool._al_on_height_map_ready.assert_not_called()

    def test_malformed_offset_after_contact_fails_closed(self):
        for record in ('[G54:0]', '[G54:0,0,0,0]', '[G54:0,0,nan]',
                       '[G92:0]', '[G92:]', '[G92:0,0,0,0]', '[G92:0,inf,0]',
                       '[TLO:]', '[TLO:0,0]', '[TLO:nan]', '[TLO:0'):
            with self.subTest(record=record):
                tool, target, fake = self.tool()
                for value in tool.al_voronoi_geo_storage.values():
                    value['height'] = 0.5
                original = fake._answer

                def answer(cmd):
                    if cmd == '$#' and fake.probe_count:
                        prefix = [] if record.startswith('[G54:') else ['[G54:0,0,0]']
                        fake._send(*prefix, record, 'ok')
                    else:
                        original(cmd)

                fake._answer = answer
                self.run_probe(tool)
                coarse = fake.commands().index('G38.2 Z-1.0000 F600.0000')
                self.assertFalse(any(c.startswith(('G0', 'G38')) for c in fake.commands()[coarse + 1:]))
                self.assertEqual(fake.probe_count, 1)
                self.assertIn('!', fake.commands())
                self.assertEqual(tool._grbl_recovery, 'needs_reset')
                self.assertIsNone(tool._grbl_op)
                self.assertFalse(tool.al_heights_valid)
                self.assertEqual([v['height'] for v in tool.al_voronoi_geo_storage.values()], [0.5, 0.5])
                tool._al_on_height_map_ready.assert_not_called()
                results = [call.args[0]['kind'] for call in tool.al_result_ready_sig.emit.call_args_list]
                self.assertEqual(results, ['failed'])
                self.assertTrue(any('probe_invalid' in text for text in emitted(tool)))

    def test_unknown_modes_or_offset_after_touch_require_recovery(self):
        for command, reply in (('$G', ['error:9']), ('$G', ['[GC:G0 G54 G17 G21 G91 G94]', 'ok']),
                               ('$#', ['ok']), ('$#', ['[G54:0,0,1]', '[G92:0,0,0]', '[TLO:0]', 'ok'])):
            with self.subTest(command=command, reply=reply):
                tool, target, fake = self.tool()
                original = fake._answer

                def answer(cmd):
                    if cmd == command and fake.probe_count:
                        fake._send(*reply)
                    else:
                        original(cmd)

                fake._answer = answer
                self.run_probe(tool)
                coarse = fake.commands().index('G38.2 Z-1.0000 F600.0000')
                self.assertFalse(any(c.startswith('G0') for c in fake.commands()[coarse + 1:]))
                self.assertEqual(tool._grbl_recovery, 'needs_reset')
                self.assertFalse(tool.al_heights_valid)


if __name__ == '__main__':
    unittest.main()
