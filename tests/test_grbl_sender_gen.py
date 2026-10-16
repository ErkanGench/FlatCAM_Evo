#!/usr/bin/env python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

from appPlugins.ToolGrblSender import SenderGen


class TestCleanLines(unittest.TestCase):
    def test_removes_comments(self):
        self.assertEqual(SenderGen.clean_lines('G1 X1 (cut)\n; note\nG0 Z5 ;up\n%\n\n'), ['G1 X1', 'G0 Z5'])

    def test_keeps_order(self):
        self.assertEqual(SenderGen.clean_lines('G0 X1\nG1 X2\nG1 X3\n'), ['G0 X1', 'G1 X2', 'G1 X3'])

    def test_numbered_keeps_source_line(self):
        self.assertEqual(SenderGen.clean_lines_numbered('(a)\nG0 X1\n\n; c\nG1 X2\n'), [(2, 'G0 X1'), (5, 'G1 X2')])


if __name__ == '__main__':
    unittest.main()
