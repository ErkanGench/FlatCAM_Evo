"""ObjectCollection.update_view refreshes rows with dataChanged and keeps selection and persistent indexes."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtTest import QSignalSpy

from appObjects.ObjectCollection import ObjectCollection, TreeItem

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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
    return col


def add_item(col, kind, name):
    """Add a stand-in object to a group the way the model does it (rows inserted with begin/end)."""
    group = col.group_items[kind]
    group_index = col.index(col.root_item.child_items.index(group), 0, QtCore.QModelIndex())
    row = group.child_count()
    obj = SimpleNamespace(kind=kind, obj_options={"name": name, "plot": True})
    col.beginInsertRows(group_index, row, row)
    item = TreeItem([name], col.icons[kind], obj=obj, parent_item=group)
    col.endInsertRows()
    return obj, item


class TestUpdateView(unittest.TestCase):
    def setUp(self):
        self.col = make_collection()
        self.g1, _ = add_item(self.col, "gerber", "g1")
        self.g2, self.g2_item = add_item(self.col, "gerber", "g2")
        self.g3, _ = add_item(self.col, "gerber", "g3")
        self.e1, _ = add_item(self.col, "excellon", "e1")
        self.spy = QSignalSpy(self.col.dataChanged)
        self.layout_spy = QSignalSpy(self.col.layoutChanged)

    def _ranges(self):
        res = []
        for args in self.spy:
            top, bottom = args[0], args[1]
            self.assertEqual(top.parent(), bottom.parent())
            res.append((top.parent().row(), top.row(), bottom.row(), top.internalPointer()))
        return res

    def test_object_emits_single_data_changed_for_its_row(self):
        self.col.update_view(self.g2)
        self.assertEqual(len(self.spy), 1)
        self.assertEqual(len(self.layout_spy), 0)
        top, bottom = self.spy[0][0], self.spy[0][1]
        self.assertEqual(top.row(), 1)
        self.assertEqual(bottom.row(), 1)
        self.assertIs(top.internalPointer(), self.g2_item)
        self.assertEqual(top.parent(), bottom.parent())
        self.assertTrue(top.parent().isValid())
        # no roles list: every role is refreshed
        self.assertEqual(len(self.spy[0][2]), 0)

    def test_no_arg_covers_all_non_empty_groups(self):
        self.col.update_view()
        self.assertEqual(len(self.layout_spy), 0)
        ranges = self._ranges()
        self.assertEqual(len(ranges), 2)
        by_group = {self.col.root_item.child_items[r[0]]: r for r in ranges}
        gerber = by_group[self.col.group_items["gerber"]]
        excellon = by_group[self.col.group_items["excellon"]]
        self.assertEqual((gerber[1], gerber[2]), (0, 2))
        self.assertEqual((excellon[1], excellon[2]), (0, 0))

    def test_selection_and_persistent_index_survive(self):
        view = self.col.view
        gerber_group = self.col.group_items["gerber"]
        parent = self.col.index(self.col.root_item.child_items.index(gerber_group), 0, QtCore.QModelIndex())
        idx = self.col.index(1, 0, parent)
        view.selectionModel().select(idx, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        persistent = QtCore.QPersistentModelIndex(idx)

        self.col.update_view(self.g2)
        self.col.update_view()

        self.assertTrue(persistent.isValid())
        self.assertEqual(persistent.row(), 1)
        self.assertIs(QtCore.QModelIndex(persistent).internalPointer(), self.g2_item)
        selected = view.selectionModel().selectedIndexes()
        self.assertEqual([s.internalPointer() for s in selected], [self.g2_item])


if __name__ == "__main__":
    unittest.main()
