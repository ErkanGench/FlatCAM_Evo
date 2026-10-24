from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCComboBox2, RadioSet, FCDoubleSpinner, EvalEntry, FCTable

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class FidoUI:

    pluginName = _("Fiducials")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        self.units = self.app.app_units.lower()
        self.title_box = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.title_box)
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.title_box.addWidget(title_label)
        self.level = QtWidgets.QToolButton()
        self.level.setToolTip(
            _("Beginner Mode - many parameters are hidden.\n"
              "Advanced Mode - full control.\n"
              "Permanent change is done in 'Preferences' menu.")
        )
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)
        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)
        self.title_box = QtWidgets.QHBoxLayout()
        self.tools_box.addLayout(self.title_box)

        # Gerber source
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(_("Gerber object for adding fiducials and soldermask openings."))
        self.grb_object_combo = FCComboBox()
        self.grb_object_combo.setModel(self.app.collection)
        self.grb_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.grb_object_combo.is_last = True
        self.grb_object_combo.obj_type = "Gerber"
        self.tools_box.addWidget(self.obj_combo_label)
        self.tools_box.addWidget(self.grb_object_combo)

        # Coordinates
        self.points_label = FCLabel('%s' % _("Coordinates"), color='green', bold=True)
        self.points_label.setToolTip(
            _("A table with the fiducial points coordinates,\n"
              "in the format (x, y).")
        )
        self.tools_box.addWidget(self.points_label)
        self.points_table = FCTable()
        self.points_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tools_box.addWidget(self.points_table)
        self.points_table.setColumnCount(3)
        self.points_table.setHorizontalHeaderLabels(['#', _("Name"), _("Coordinates")])
        self.points_table.setRowCount(3)
        row = 0
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled
        id_item_1 = QtWidgets.QTableWidgetItem('%d' % 1)
        id_item_1.setFlags(flags)
        self.points_table.setItem(row, 0, id_item_1)
        self.bottom_left_coords_lbl = QtWidgets.QTableWidgetItem('%s' % _('Bottom Left'))
        self.bottom_left_coords_lbl.setFlags(flags)
        self.points_table.setItem(row, 1, self.bottom_left_coords_lbl)
        self.bottom_left_coords_entry = EvalEntry()
        self.bottom_left_coords_entry.setReadOnly(True)
        self.points_table.setCellWidget(row, 2, self.bottom_left_coords_entry)
        row += 1
        id_item_2 = QtWidgets.QTableWidgetItem('%d' % 2)
        id_item_2.setFlags(flags)
        self.points_table.setItem(row, 0, id_item_2)
        self.top_right_coords_lbl = QtWidgets.QTableWidgetItem('%s' % _('Top Right'))
        self.top_right_coords_lbl.setFlags(flags)
        self.points_table.setItem(row, 1, self.top_right_coords_lbl)
        self.top_right_coords_entry = EvalEntry()
        self.top_right_coords_entry.setReadOnly(True)
        self.points_table.setCellWidget(row, 2, self.top_right_coords_entry)
        row += 1
        self.id_item_3 = QtWidgets.QTableWidgetItem('%d' % 3)
        self.id_item_3.setFlags(flags)
        self.points_table.setItem(row, 0, self.id_item_3)
        self.sec_point_coords_lbl = QtWidgets.QTableWidgetItem('%s' % _('Second Point'))
        self.sec_point_coords_lbl.setFlags(flags)
        self.points_table.setItem(row, 1, self.sec_point_coords_lbl)
        self.sec_points_coords_entry = EvalEntry()
        self.sec_points_coords_entry.setReadOnly(True)
        self.points_table.setCellWidget(row, 2, self.sec_points_coords_entry)
        vertical_header = self.points_table.verticalHeader()
        vertical_header.hide()
        self.points_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        horizontal_header = self.points_table.horizontalHeader()
        horizontal_header.setMinimumSectionSize(10)
        horizontal_header.setDefaultSectionSize(70)
        self.points_table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.points_table.resizeColumnsToContents()
        self.points_table.resizeRowsToContents()
        horizontal_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(0, 20)
        horizontal_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.points_table.setMinimumHeight(self.points_table.getHeight() + 2)
        self.points_table.setMaximumHeight(self.points_table.getHeight() + 2)
        for row in range(self.points_table.rowCount()):
            wdg = self.points_table.cellWidget(row, 2)
            assert isinstance(wdg, QtWidgets.QLineEdit)
            wdg.setFrame(False)

        # Parameters
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters used for this tool."))
        self.tools_box.addWidget(self.param_label)
        par_frame = FCFrame()
        self.tools_box.addWidget(par_frame)
        param_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(param_grid)
        self.size_label = FCLabel('%s:' % _("Size"))
        self.size_label.setToolTip(
            _("This set the fiducial diameter if fiducial type is circular,\n"
              "otherwise is the size of the fiducial.\n"
              "The soldermask opening is double than that.")
        )
        self.fid_size_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.fid_size_entry.set_range(10 ** -self.decimals, 10000.0000)
        self.fid_size_entry.set_precision(self.decimals)
        self.fid_size_entry.setSingleStep(0.1)
        param_grid.addWidget(self.size_label, 2, 0)
        param_grid.addWidget(self.fid_size_entry, 2, 1)
        param_grid.addWidget(FCLabel("%s" % self.units), 2, 2)
        self.margin_label = FCLabel('%s:' % _("Margin"))
        self.margin_label.setToolTip(_("Bounding box margin."))
        self.margin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.margin_entry.set_range(-10000.0000, 10000.0000)
        self.margin_entry.set_precision(self.decimals)
        self.margin_entry.setSingleStep(0.1)
        param_grid.addWidget(self.margin_label, 4, 0)
        param_grid.addWidget(self.margin_entry, 4, 1)
        param_grid.addWidget(FCLabel("%s" % self.units), 4, 2)
        self.pos_radio = RadioSet([
            {'label': _('Up'), 'value': 'up'}, {"label": _("Down"), "value": "down"},
            {"label": _("None"), "value": "no"}], compact=True)
        self.pos_label = FCLabel('%s:' % _("Second fiducial"))
        self.pos_label.setToolTip(
            _("The position for the second fiducial.\n"
              "- 'Up' - the order is: bottom-left, top-left, top-right.\n"
              "- 'Down' - the order is: bottom-left, bottom-right, top-right.\n"
              "- 'None' - there is no second fiducial. The order is: bottom-left, top-right.")
        )
        param_grid.addWidget(self.pos_label, 6, 0)
        param_grid.addWidget(self.pos_radio, 6, 1)
        self.separator_line = QtWidgets.QFrame()
        self.separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        param_grid.addWidget(self.separator_line, 8, 0, 1, 2)
        self.fid_type_label = FCLabel('%s:' % _("Fiducial Type"))
        self.fid_type_label.setToolTip(
            _("The type of fiducial.\n"
              "- 'Circular' - this is the regular fiducial.\n"
              "- 'Cross' - cross lines fiducial.\n"
              "- 'Chess' - chess pattern fiducial.")
        )
        self.fid_type_combo = FCComboBox2()
        self.fid_type_combo.addItems([_('Circular'), _("Cross"), _("Chess")])
        param_grid.addWidget(self.fid_type_label, 10, 0)
        param_grid.addWidget(self.fid_type_combo, 10, 1)
        self.line_thickness_label = FCLabel('%s:' % _("Line thickness"))
        self.line_thickness_label.setToolTip(_("Thickness of the line that makes the fiducial."))
        self.line_thickness_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.line_thickness_entry.set_range(0.00001, 10000.0000)
        self.line_thickness_entry.set_precision(self.decimals)
        self.line_thickness_entry.setSingleStep(0.1)
        param_grid.addWidget(self.line_thickness_label, 12, 0)
        param_grid.addWidget(self.line_thickness_entry, 12, 1)
        param_grid.addWidget(FCLabel("%s" % self.units), 12, 2)

        # Selection
        self.sel_label = FCLabel('%s' % _("Selection"), color='green', bold=True)
        self.tools_box.addWidget(self.sel_label)
        self.s_frame = FCFrame()
        self.tools_box.addWidget(self.s_frame)
        grid_sel = GLay(v_spacing=5, h_spacing=3)
        self.s_frame.setLayout(grid_sel)
        self.mode_radio = RadioSet([
            {'label': _('Auto'), 'value': 'auto'}, {"label": _("Manual"), "value": "manual"}], compact=True)
        self.mode_label = FCLabel(_("Mode:"))
        self.mode_label.setToolTip(
            _("- 'Auto' - automatic placement of fiducials in the corners of the bounding box.\n"
              "- 'Manual' - manual placement of fiducials.")
        )
        grid_sel.addWidget(self.mode_label, 0, 0)
        grid_sel.addWidget(self.mode_radio, 0, 1)
        self.big_cursor_cb = FCCheckBox('%s' % _("Big cursor"))
        self.big_cursor_cb.setToolTip(_("Use a big cursor."))
        grid_sel.addWidget(self.big_cursor_cb, 2, 0, 1, 2)
        GLay.set_common_column_size([grid_sel, param_grid, param_grid], 0)
        self.add_cfid_button = FCButton(_("Add Fiducial"), bold=True)
        self.add_cfid_button.setIcon(QtGui.QIcon(self.app.resource_location + '/fiducials_32.png'))
        self.add_cfid_button.setToolTip(_("Will add a polygon on the copper layer to serve as fiducial."))
        self.tools_box.addWidget(self.add_cfid_button)
        self.add_sm_opening_button = FCButton(_("Add Soldermask Opening"), bold=True)
        self.add_sm_opening_button.setToolTip(
            _("Will add a polygon on the soldermask layer\n"
              "to serve as fiducial opening.\n"
              "The diameter is always double of the diameter\n"
              "for the copper fiducial.")
        )
        self.tools_box.addWidget(self.add_sm_opening_button)
        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)

    def set_fiducial_type(self, val):
        if val == 1:    # 'cross'
            self.line_thickness_label.setDisabled(False)
            self.line_thickness_entry.setDisabled(False)
        else:
            self.line_thickness_label.setDisabled(True)
            self.line_thickness_entry.setDisabled(True)

    def set_second_point(self, val):
        if val == 'no':
            self.id_item_3.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.sec_point_coords_lbl.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.sec_points_coords_entry.setDisabled(True)
        else:
            self.id_item_3.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.sec_point_coords_lbl.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.sec_points_coords_entry.setDisabled(False)

    def set_level(self, checked):
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)
            self.separator_line.hide()
            self.fid_type_label.hide()
            self.fid_type_combo.hide()
            self.line_thickness_label.hide()
            self.line_thickness_entry.hide()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)
            self.separator_line.show()
            self.fid_type_label.show()
            self.fid_type_combo.show()
            self.line_thickness_label.show()
            self.line_thickness_entry.show()

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals,
                                                                                  minval,
                                                                                  self.decimals,
                                                                                  maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
