"""Tests for the split of application settings and project options."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from defaults import AppDefaults, APP_TOOL_KEYS, PROJECT_KEYS, is_project_key


class TestIsProjectKey(unittest.TestCase):
    def test_named_project_keys(self):
        for key in ('units', 'gerber_noncoppermargin', 'gerber_noncopperrounded', 'gerber_bboxmargin',
                    'gerber_bboxrounded', 'gerber_follow', 'excellon_drill_tooldia', 'excellon_slot_tooldia',
                    'geometry_seg_x', 'geometry_seg_y'):
            self.assertTrue(is_project_key(key), key)

    def test_tools_keys_are_project_keys(self):
        for key in ('tools_iso_tooldia', 'tools_drill_ppname_e', 'tools_mill_ppname_g', 'tools_ncc_operation'):
            self.assertTrue(is_project_key(key), key)

    def test_tools_application_exceptions(self):
        for key in ('tools_grbl_travelz', 'tools_calc_vshape_tip_dia', 'tools_iso_plotting',
                    'tools_dist_big_cursor', 'tools_drill_preprocessor_list', 'tools_al_controller',
                    'tools_gcode_fit_view', 'tools_dist_snap_center', 'tools_opt_precision',
                    'tools_qrcode_sel_limit'):
            self.assertFalse(is_project_key(key), key)

    def test_other_keys_are_application_keys(self):
        for key in ('global_gridx', 'global_workspace', 'global_appearance', 'cncjob_tooldia',
                    'excellon_optimization_type', 'gerber_plot', 'units_precision', 'first_run',
                    'root_folder_path', None, 5):
            self.assertFalse(is_project_key(key), key)

    def test_listed_keys_exist_in_factory_defaults(self):
        for key in PROJECT_KEYS | APP_TOOL_KEYS:
            self.assertIn(key, AppDefaults.factory_defaults, key)


if __name__ == '__main__':
    unittest.main()
