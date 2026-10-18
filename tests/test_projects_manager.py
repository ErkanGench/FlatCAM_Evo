"""Tests for the multiple projects feature: ProjectManager and the handlers that read app.collection."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtWidgets


class FakeCollection:
    def __init__(self, objects=None):
        self.view = QtWidgets.QWidget()
        self.objects = list(objects or [])

    def get_list(self):
        return list(self.objects)

    def has_promises(self):
        return False

    def has_plot_promises(self):
        return False


class TestHandlersReadLiveCollection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_plot_manager_reads_app_collection(self):
        from appHandlers.appPlotManager import AppPlotManager
        app = SimpleNamespace(log=Mock(), inform=Mock(), options={}, collection=FakeCollection(),
                              worker_task=Mock(), plotcanvas=Mock(), clear_pool=Mock(), app_obj=Mock(),
                              defaults={}, proc_container=Mock())
        manager = AppPlotManager(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(manager.collection, second)

    def test_edit_handler_reads_app_collection(self):
        from appHandlers.appEdit import appEditor
        app = SimpleNamespace(log=Mock(), inform=Mock(), splash=Mock(), worker_task=Mock(), options={},
                              app_units='MM', defaults={}, collection=FakeCollection(), app_obj=Mock(),
                              decimals=4)
        handler = appEditor(app)
        second = FakeCollection()
        app.collection = second
        self.assertIs(handler.collection, second)


if __name__ == '__main__':
    unittest.main()
