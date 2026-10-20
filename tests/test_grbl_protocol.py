#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.Common.grbl.grbl_protocol import parse_grbl_status_report, work_position


class TestStatusReport(unittest.TestCase):
    def test_run_mpos_fs_ov(self):
        rep = parse_grbl_status_report(
            '<Run|MPos:1.000,2.000,-0.500|FS:500,10000|Ov:100,100,100|WCO:0.000,0.000,0.000>')
        self.assertEqual(rep['state'], 'Run')
        self.assertEqual(rep['mpos'], (1.0, 2.0, -0.5))
        self.assertEqual(rep['feed'], 500.0)
        self.assertEqual(rep['spindle'], 10000.0)
        self.assertEqual(rep['ov'], (100, 100, 100))

    def test_idle_wpos(self):
        rep = parse_grbl_status_report('<Idle|WPos:0.000,0.000,0.000|FS:0,0>')
        self.assertEqual(rep['state'], 'Idle')
        self.assertEqual(rep['wpos'], (0.0, 0.0, 0.0))

    def test_hold_substate(self):
        self.assertEqual(parse_grbl_status_report('<Hold:0|MPos:0,0,0>')['state'], 'Hold')

    def test_not_a_report(self):
        for text in ('ok', '', None, '<Idle|MPos:1,2>'):
            self.assertIsNone(parse_grbl_status_report(text))

    def test_work_position_from_wco(self):
        self.assertEqual(work_position({'mpos': (10.0, 10.0, 0.0)}, last_wco=(1.0, 2.0, 3.0)),
                         (9.0, 8.0, -3.0))

    def test_work_position_unknown(self):
        self.assertIsNone(work_position({'mpos': (1, 2, 3)}))


if __name__ == '__main__':
    unittest.main()
