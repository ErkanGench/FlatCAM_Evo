"""
The context menu of the Project tab shows the entries that apply to the selected objects, and View Source does not
open an empty Source Editor for an object without a source (a Geometry made by a tool).

    python tests/test_project_context_menu.py
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtWidgets                        # noqa: E402

from appObjects.ObjectCollection import ObjectCollection   # noqa: E402

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_ui():
    """The entries of the Project tab context menu, as MainGUI builds them."""
    menu = QtWidgets.QMenu()
    ui = SimpleNamespace(menuproject=menu)
    ui.menuprojectenable = menu.addAction('Enable Plot')
    ui.menuprojectdisable = menu.addAction('Disable Plot')
    ui.menuprojectcolor = menu.addMenu('Set Color')
    ui.menuprojectcolor.addAction('Red')
    ui.menuprojectviewsource = menu.addAction('View Source')
    ui.menuprojectedit = menu.addAction('Edit')
    ui.menuprojectcopy = menu.addAction('Copy')
    ui.menuprojectdelete = menu.addAction('Delete')
    ui.menuprojectsave = menu.addAction('Save')
    ui.menuprojectproperties = menu.addAction('Properties')
    return ui


def make_collection():
    app = mock.MagicMock()
    app.resource_location = "."
    app.options = {
        "global_allow_edit_in_project_tab": False,
        "global_proj_item_color_dark": "#FFFFFFFF",
        "global_proj_item_dis_color_dark": "#808080FF",
        "global_proj_item_color_light": "#000000FF",
        "global_proj_item_dis_color_light": "#808080FF",
    }
    col = ObjectCollection(app)
    app.ui = make_ui()
    return col


def obj(kind, name='obj', plot=True, **attrs):
    return SimpleNamespace(kind=kind, obj_options={'name': name, 'plot': plot}, **attrs)


class TestHasSource(unittest.TestCase):

    def test_kinds(self):
        self.assertTrue(ObjectCollection.has_source(obj('cncjob')))
        self.assertTrue(ObjectCollection.has_source(obj('gerber', source_file='G04 test*\nM02*\n')))
        self.assertTrue(ObjectCollection.has_source(obj('excellon', source_file='M48\nM30\n')))
        self.assertTrue(ObjectCollection.has_source(obj('geometry', source_file='0\nSECTION\n')))

    def test_objects_without_a_source(self):
        # a Geometry made by a tool has no source_file
        self.assertFalse(ObjectCollection.has_source(obj('geometry')))
        self.assertFalse(ObjectCollection.has_source(obj('gerber', source_file='')))
        # (Copper Thieving sets a list)
        self.assertFalse(ObjectCollection.has_source(obj('gerber', source_file=[])))


class TestMenuRequest(unittest.TestCase):

    def setUp(self):
        self.col = make_collection()
        self.ui = self.col.app.ui
        self.ui.menuproject.popup = mock.Mock()

    def tearDown(self):
        self.ui.menuproject.deleteLater()

    def request(self, *selected):
        self.col.get_selected = lambda: list(selected)
        self.col.on_menu_request(QtCore.QPoint(0, 0))
        self.ui.menuproject.popup.assert_called()

    def shown(self):
        ui = self.ui
        names = {
            'enable': ui.menuprojectenable, 'disable': ui.menuprojectdisable,
            'color': ui.menuprojectcolor.menuAction(), 'view_source': ui.menuprojectviewsource,
            'edit': ui.menuprojectedit, 'copy': ui.menuprojectcopy, 'delete': ui.menuprojectdelete,
            'save': ui.menuprojectsave, 'properties': ui.menuprojectproperties
        }
        return {name for name, action in names.items() if action.isVisible()}

    def test_geometry_made_by_a_tool_has_no_view_source(self):
        self.request(obj('geometry'))
        self.assertEqual(self.shown(), {'disable', 'edit', 'copy', 'delete', 'save', 'properties'})

    def test_gerber_with_a_source(self):
        self.request(obj('gerber', source_file='G04 test*\nM02*\n'))
        self.assertEqual(self.shown(), {'disable', 'color', 'view_source', 'edit', 'copy', 'delete', 'save',
                                        'properties'})

    def test_cncjob(self):
        self.request(obj('cncjob', plot=False))
        self.assertEqual(self.shown(), {'enable', 'view_source', 'edit', 'copy', 'delete', 'save', 'properties'})

    def test_entries_hidden_for_a_script_come_back_for_the_next_object(self):
        self.request(obj('script', source_file='puts 1'))
        self.assertEqual(self.shown(), {'copy', 'delete', 'save'})

        self.request(obj('excellon', source_file='M48\nM30\n'))
        self.assertEqual(self.shown(), {'disable', 'color', 'view_source', 'edit', 'copy', 'delete', 'save',
                                        'properties'})

    def test_enable_and_disable_follow_the_plot_state(self):
        self.request(obj('gerber', 'a', plot=True), obj('gerber', 'b', plot=False))
        self.assertTrue({'enable', 'disable'} <= self.shown())
        self.request(obj('gerber', 'a', plot=False), obj('gerber', 'b', plot=False))
        self.assertIn('enable', self.shown())
        self.assertNotIn('disable', self.shown())

    def test_several_objects(self):
        # View Source, Edit and Save work on 1 object
        self.request(obj('gerber', 'a', source_file='G04*'), obj('geometry', 'b'))
        self.assertEqual(self.shown(), {'disable', 'copy', 'delete', 'properties'})
        self.assertEqual(self.ui.menuprojectsave.text(), 'Save')

        # several CNCJob objects: Batch Save
        self.request(obj('cncjob', 'a'), obj('cncjob', 'b'))
        self.assertEqual(self.shown(), {'disable', 'copy', 'delete', 'save', 'properties'})
        self.assertEqual(self.ui.menuprojectsave.text(), 'Batch Save')

    def test_no_selection(self):
        self.request(obj('script'))
        self.request()
        ui = self.ui
        for action in (ui.menuprojectenable, ui.menuprojectdisable, ui.menuprojectcolor.menuAction(),
                       ui.menuprojectviewsource, ui.menuprojectedit, ui.menuprojectcopy, ui.menuprojectdelete,
                       ui.menuprojectsave, ui.menuprojectproperties):
            self.assertTrue(action.isVisible())
            self.assertFalse(action.isEnabled())


class TestViewSource(unittest.TestCase):

    def view_source(self, selected):
        from appMain import App

        col = make_collection()
        col.get_active = lambda: selected
        app = mock.MagicMock()
        app.collection = col
        with mock.patch('appMain.AppTextEditor'):
            result = App.on_view_source(app)
        return app, result

    def test_object_without_a_source_does_not_open_an_empty_editor(self):
        app, result = self.view_source(obj('geometry', 'iso_geo'))
        self.assertEqual(result, 'fail')
        app.ui.plot_tab_area.addTab.assert_not_called()
        app.proc_container.view.set_busy.assert_not_called()
        message = app.inform.emit.call_args[0][0]
        self.assertTrue(message.startswith('[WARNING_NOTCL]'))
        self.assertIn('iso_geo', message)

    def test_object_with_a_source_opens_the_editor(self):
        app, __ = self.view_source(obj('gerber', 'top', source_file='G04 test*\nM02*\n'))
        app.ui.plot_tab_area.addTab.assert_called_once()
        app.source_editor_tab.load_text.assert_called_once_with('G04 test*\nM02*\n', clear_text=True,
                                                                move_to_start=True)


if __name__ == '__main__':
    unittest.main()
