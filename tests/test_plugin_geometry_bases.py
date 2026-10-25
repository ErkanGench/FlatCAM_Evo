"""Shared helper of the plugin tests (the Isolation tests build their tool app with it)."""

from unittest.mock import MagicMock

from PyQt6.QtCore import QStringListModel


def make_tool_app():
    app = MagicMock()
    app.decimals = 4
    app.app_units = "MM"
    app.collection = QStringListModel()
    app.resource_location = "assets/resources"
    app.options = {}
    app.defaults = {}
    app.abort_flag = False
    return app
