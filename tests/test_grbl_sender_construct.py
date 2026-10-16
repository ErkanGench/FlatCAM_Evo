#!/usr/bin/env python
"""
The GRBL Sender plugin must construct with the real __init__ and fill its UI.

Run: .venv/Scripts/python.exe -m pytest tests/test_grbl_sender_construct.py -q
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import MagicMock, patch

from PyQt6 import QtWidgets, QtGui

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from defaults import AppDefaults
from appPlugins.ToolGrblSender.Sender import ToolGrblSender


class FakeCollection(QtGui.QStandardItemModel):
    """The object combo needs a real item model; the sender asks it for objects by name."""

    def __init__(self):
        super().__init__()
        self.insertRows(0, 5)

    def get_by_name(self, name):
        return None

    def get_active(self):
        return None


def make_app():
    app = MagicMock()
    app.collection = FakeCollection()
    app.decimals = 4
    app.options = dict(AppDefaults.factory_defaults)
    app.defaults = app.options
    app.resource_location = 'assets/resources'
    app.app_units = 'MM'
    return app


class TestGrblSenderConstruct(unittest.TestCase):

    def test_construct(self):
        tool = ToolGrblSender(make_app())
        self.assertEqual(tool.pluginName, 'GRBL Sender')

    def test_populate(self):
        tool = ToolGrblSender(make_app())
        # no GL canvas in the test: the probing shapes are a mock
        with patch('appPlugins.Common.levelling_core.ShapeCollection'):
            tool._populate_tool_ui()


class TestBaudratePersists(unittest.TestCase):

    def populate(self, app):
        tool = ToolGrblSender(app)
        with patch('appPlugins.Common.levelling_core.ShapeCollection'):
            tool._populate_tool_ui()
        return tool

    def test_saved_rate_is_selected(self):
        app = make_app()
        app.options["tools_grbl_baudrate"] = '57600'
        tool = self.populate(app)
        self.assertEqual(tool.ui.baudrates_list_combo.currentText(), '57600')

    def test_custom_rate_is_added_and_selected(self):
        app = make_app()
        app.options["tools_grbl_baudrate"] = '256000'
        tool = self.populate(app)
        combo = tool.ui.baudrates_list_combo
        self.assertEqual(combo.currentText(), '256000')
        self.assertEqual([combo.itemText(i) for i in range(combo.count())].count('256000'), 1)

    def test_selection_is_saved(self):
        app = make_app()
        tool = self.populate(app)
        tool.ui.baudrates_list_combo.setCurrentText('9600')
        self.assertEqual(app.options["tools_grbl_baudrate"], '9600')

    def test_added_rate_is_saved(self):
        app = make_app()
        tool = self.populate(app)
        # 250000 is not in the default list, so the button adds it
        tool.ui.new_baudrate_entry.set_value(250000)
        tool.on_grbl_add_baudrate()
        self.assertEqual(app.options["tools_grbl_baudrate"], '250000')


if __name__ == '__main__':
    unittest.main()
