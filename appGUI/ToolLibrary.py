"""Qt model/view presentation for the tool library."""

from PyQt6 import QtCore, QtGui
import builtins
import gettext
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def operation_names():
    return [_('General'), _('Milling'), _('Drilling'), _('Isolation'), _('Paint'), _('NCC'), _('Cutout')]


class ToolLibraryModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = {}
        self.ids = []
        self.rows = {}
        self.operations = operation_names()
        self.search_texts = {}
        # Tool ID -> reason; these records stay in the file but cannot be edited or used.
        self.skipped = {}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.ids)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.DisplayRole:
            return [_('ID'), _('Name'), _('Operation'), _('Diameter'), _('Shape')][section]
        return None

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.ids):
            return None
        key = self.ids[index.row()]
        tool = self.records[key]
        target = tool['data']['tool_target']
        shape = tool['data'].get('tools_mill_tool_shape', 0)
        values = (int(key), tool['name'], target, tool['tooldia'], shape)
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return values[index.column()]
        if key in self.skipped:
            if role == QtCore.Qt.ItemDataRole.ToolTipRole:
                return _('Skipped: %s') % self.skipped[key]
            if role == QtCore.Qt.ItemDataRole.ForegroundRole:
                return QtGui.QBrush(QtGui.QColor('#c0392b'))
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            if index.column() == 2:
                return self.operations[target]
            if index.column() == 4:
                return ('C1', 'C2', 'C3', 'C4', 'B', 'V', 'L')[shape]
            return values[index.column()]
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole and index.column() == 3:
            return QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        return None

    def sync(self, records):
        ids = list(records)
        old_count = len(self.ids)
        if ids[:old_count] == self.ids and len(ids) > old_count:
            self.beginInsertRows(QtCore.QModelIndex(), old_count, len(ids) - 1)
            self.records = records
            self.ids = ids
            self.endInsertRows()
        elif ids != self.ids:
            self.beginResetModel()
            self.records = records
            self.ids = ids
            self.endResetModel()
        else:
            self.records = records
        self.rows = {key: row for row, key in enumerate(ids)}
        self.search_texts = {key: self.search_text(key) for key in ids}

    def search_text(self, key):
        tool = self.records[key]
        shape = tool['data'].get('tools_mill_tool_shape', 0)
        return ('%s %s %s %s' % (tool['name'], tool['tooldia'],
                                 self.operations[tool['data']['tool_target']],
                                 ('C1', 'C2', 'C3', 'C4', 'B', 'V', 'L')[shape])).casefold()

    def update_tool(self, key):
        row = self.rows.get(str(key))
        if row is not None:
            self.search_texts[str(key)] = self.search_text(str(key))
            self.dataChanged.emit(self.index(row, 0), self.index(row, 4))


class ToolLibraryFilter(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.target = None
        self.query = ''
        self.words = []
        self.setSortRole(QtCore.Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(True)

    def set_filters(self, query, target):
        if hasattr(self, 'endFilterChange'):
            self.beginFilterChange()
        self.query = query.casefold().strip()
        self.words = self.query.split()
        self.target = target
        if hasattr(self, 'endFilterChange'):
            self.endFilterChange(QtCore.QSortFilterProxyModel.Direction.Rows)
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if not isinstance(model, ToolLibraryModel):
            return False
        tool = model.records[model.ids[source_row]]
        target = tool['data']['tool_target']
        if self.target is not None and target not in (0, self.target):
            return False
        if self.words:
            return all(word in model.search_texts.get(model.ids[source_row], '') for word in self.words)
        return True
