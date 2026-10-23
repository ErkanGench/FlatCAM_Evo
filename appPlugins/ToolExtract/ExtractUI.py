from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    RadioSet, FCDoubleSpinner, FCTable

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ExtractUI:

    pluginName = _("Extract")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)
        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # Source
        self.grb_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.grb_label.setToolTip('%s.' % _("Gerber object from which to extract drill holes or soldermask."))
        self.tools_box.addWidget(self.grb_label)
        self.gerber_object_combo = FCComboBox()
        self.gerber_object_combo.setModel(self.app.collection)
        self.gerber_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.gerber_object_combo.is_last = False
        self.gerber_object_combo.obj_type = "Gerber"
        self.tools_box.addWidget(self.gerber_object_combo)

        # Processed pads
        self.padt_label = FCLabel('%s' % _("Processed Pads Type"), color='green', bold=True)
        self.padt_label.setToolTip(
            _("The type of pads shape to be processed.\n"
              "If the PCB has many SMD pads with rectangular pads,\n"
              "disable the Rectangular aperture.")
        )
        self.tools_box.addWidget(self.padt_label)
        pads_frame = FCFrame()
        self.tools_box.addWidget(pads_frame)
        grid_lay = GLay(v_spacing=5, h_spacing=3)
        grid_lay.setColumnStretch(0, 1)
        grid_lay.setColumnStretch(1, 0)
        pads_frame.setLayout(grid_lay)
        pad_all_grid = GLay(v_spacing=5, h_spacing=3)
        grid_lay.addLayout(pad_all_grid, 5, 0, 1, 2)
        pad_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0])
        pad_all_grid.addLayout(pad_grid, 0, 0)
        self.all_cb = FCCheckBox('%s' % _("All"))
        self.all_cb.setToolTip(_("Process all Pads."))
        pad_grid.addWidget(self.all_cb, 0, 0)
        self.circular_cb = FCCheckBox('%s' % _("Circular"))
        self.circular_cb.setToolTip(_("Process Circular Pads."))
        pad_grid.addWidget(self.circular_cb, 1, 0)
        self.oblong_cb = FCCheckBox('%s' % _("Oblong"))
        self.oblong_cb.setToolTip(_("Process Oblong Pads."))
        pad_grid.addWidget(self.oblong_cb, 2, 0)
        self.square_cb = FCCheckBox('%s' % _("Square"))
        self.square_cb.setToolTip(_("Process Square Pads."))
        pad_grid.addWidget(self.square_cb, 3, 0)
        self.rectangular_cb = FCCheckBox('%s' % _("Rectangular"))
        self.rectangular_cb.setToolTip(_("Process Rectangular Pads."))
        pad_grid.addWidget(self.rectangular_cb, 4, 0)
        self.other_cb = FCCheckBox('%s' % _("Others"))
        self.other_cb.setToolTip(_("Process pads not in the categories above."))
        pad_grid.addWidget(self.other_cb, 5, 0)
        self.apertures_table = FCTable()
        pad_all_grid.addWidget(self.apertures_table, 0, 1)
        self.apertures_table.setColumnCount(4)
        self.apertures_table.setHorizontalHeaderLabels([_('Code'), _('Type'), _('Size'), 'M'])
        self.apertures_table.setSortingEnabled(False)
        self.apertures_table.setRowCount(0)
        self.apertures_table.resizeColumnsToContents()
        self.apertures_table.resizeRowsToContents()
        self.apertures_table.horizontalHeaderItem(0).setToolTip(_("Aperture Code"))
        self.apertures_table.horizontalHeaderItem(1).setToolTip(_("Type of aperture: circular, rectangle, macros etc"))
        self.apertures_table.horizontalHeaderItem(2).setToolTip(_("Aperture Size:"))
        self.apertures_table.horizontalHeaderItem(3).setToolTip(_("Mark the aperture instances on canvas."))
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                                           QtWidgets.QSizePolicy.Policy.Preferred)
        self.apertures_table.setSizePolicy(sizePolicy)
        self.apertures_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)

        # Drills
        self.extract_drills_label = FCLabel('%s' % _("Extract Drills"), color='brown', bold=True)
        self.extract_drills_label.setToolTip(_("Extract an Excellon object from the Gerber pads."))
        self.tools_box.addWidget(self.extract_drills_label)
        ed_frame = FCFrame()
        self.tools_box.addWidget(ed_frame)
        grid1 = GLay(v_spacing=5, h_spacing=3)
        ed_frame.setLayout(grid1)
        self.method_label = FCLabel('%s:' % _("Method"))
        self.method_label.setToolTip(
            _("The method for processing pads. Can be:\n"
              "- Fixed Diameter -> all holes will have a set size\n"
              "- Fixed Annular Ring -> all holes will have a set annular ring\n"
              "- Proportional -> each hole size will be a fraction of the pad size"))
        grid1.addWidget(self.method_label, 2, 0, 1, 2)
        self.method_radio = RadioSet(
            [{'label': _("Fixed Diameter"), 'value': 'fixed'},
             {'label': _("Proportional"), 'value': 'prop'},
             {'label': _("Fixed Annular Ring"), 'value': 'ring'}], orientation='vertical', compact=True)
        grid1.addWidget(self.method_radio, 4, 0, 1, 2)
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid1.addWidget(separator_line, 6, 0, 1, 2)

        # Annular ring
        self.ring_frame = QtWidgets.QFrame()
        self.ring_frame.setContentsMargins(0, 0, 0, 0)
        grid1.addWidget(self.ring_frame, 8, 0, 1, 2)
        self.ring_box = QtWidgets.QVBoxLayout()
        self.ring_box.setContentsMargins(0, 0, 0, 0)
        self.ring_frame.setLayout(self.ring_box)
        ring_grid = GLay(v_spacing=5, h_spacing=3)
        ring_grid.setContentsMargins(0, 0, 0, 0)
        self.ring_box.addLayout(ring_grid)
        self.ring_label = FCLabel('%s' % _("Fixed Annular Ring"), bold=True)
        self.ring_label.setToolTip(
            _("The size of annular ring.\n"
              "The copper sliver between the hole exterior\n"
              "and the margin of the copper pad.")
        )
        ring_grid.addWidget(self.ring_label, 0, 0, 1, 2)
        self.circular_ring_label = FCLabel('%s:' % _("Circular"))
        self.circular_ring_label.setToolTip(_("The size of annular ring for circular pads."))
        self.circular_ring_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.circular_ring_entry.set_precision(self.decimals)
        self.circular_ring_entry.set_range(0.0000, 10000.0000)
        ring_grid.addWidget(self.circular_ring_label, 2, 0)
        ring_grid.addWidget(self.circular_ring_entry, 2, 1)
        self.oblong_ring_label = FCLabel('%s:' % _("Oblong"))
        self.oblong_ring_label.setToolTip(_("The size of annular ring for oblong pads."))
        self.oblong_ring_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.oblong_ring_entry.set_precision(self.decimals)
        self.oblong_ring_entry.set_range(0.0000, 10000.0000)
        ring_grid.addWidget(self.oblong_ring_label, 4, 0)
        ring_grid.addWidget(self.oblong_ring_entry, 4, 1)
        self.square_ring_label = FCLabel('%s:' % _("Square"))
        self.square_ring_label.setToolTip(_("The size of annular ring for square pads."))
        self.square_ring_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.square_ring_entry.set_precision(self.decimals)
        self.square_ring_entry.set_range(0.0000, 10000.0000)
        ring_grid.addWidget(self.square_ring_label, 6, 0)
        ring_grid.addWidget(self.square_ring_entry, 6, 1)
        self.rectangular_ring_label = FCLabel('%s:' % _("Rectangular"))
        self.rectangular_ring_label.setToolTip(_("The size of annular ring for rectangular pads."))
        self.rectangular_ring_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.rectangular_ring_entry.set_precision(self.decimals)
        self.rectangular_ring_entry.set_range(0.0000, 10000.0000)
        ring_grid.addWidget(self.rectangular_ring_label, 8, 0)
        ring_grid.addWidget(self.rectangular_ring_entry, 8, 1)
        self.other_ring_label = FCLabel('%s:' % _("Others"))
        self.other_ring_label.setToolTip(_("The size of annular ring for other pads."))
        self.other_ring_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.other_ring_entry.set_precision(self.decimals)
        self.other_ring_entry.set_range(0.0000, 10000.0000)
        ring_grid.addWidget(self.other_ring_label, 10, 0)
        ring_grid.addWidget(self.other_ring_entry, 10, 1)

        # Fixed diameter
        self.fix_frame = QtWidgets.QFrame()
        self.fix_frame.setContentsMargins(0, 0, 0, 0)
        grid1.addWidget(self.fix_frame, 10, 0, 1, 2)
        fixed_grid = GLay(v_spacing=5, h_spacing=3)
        fixed_grid.setContentsMargins(0, 0, 0, 0)
        self.fix_frame.setLayout(fixed_grid)
        self.fixed_label = FCLabel('%s' % _("Fixed Diameter"), bold=True)
        fixed_grid.addWidget(self.fixed_label, 2, 0, 1, 2)
        self.dia_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.dia_entry.set_precision(self.decimals)
        self.dia_entry.set_range(0.0000, 10000.0000)
        self.dia_label = FCLabel('%s:' % _("Value"))
        self.dia_label.setToolTip(_("Fixed hole diameter."))
        fixed_grid.addWidget(self.dia_label, 4, 0)
        fixed_grid.addWidget(self.dia_entry, 4, 1)

        # Proportional diameter
        self.prop_frame = QtWidgets.QFrame()
        self.prop_frame.setContentsMargins(0, 0, 0, 0)
        grid1.addWidget(self.prop_frame, 12, 0, 1, 2)
        prop_grid = GLay(v_spacing=5, h_spacing=3)
        prop_grid.setContentsMargins(0, 0, 0, 0)
        self.prop_frame.setLayout(prop_grid)
        self.prop_label = FCLabel('%s' % _("Proportional Diameter"), bold=True)
        prop_grid.addWidget(self.prop_label, 0, 0, 1, 2)
        self.factor_entry = FCDoubleSpinner(callback=self.confirmation_message, suffix='%')
        self.factor_entry.set_precision(self.decimals)
        self.factor_entry.set_range(0.0000, 100.0000)
        self.factor_entry.setSingleStep(0.1)
        self.factor_label = FCLabel('%s:' % _("Value"))
        self.factor_label.setToolTip(
            _("Proportional Diameter.\n"
              "The hole diameter will be a fraction of the pad size.")
        )
        prop_grid.addWidget(self.factor_label, 2, 0)
        prop_grid.addWidget(self.factor_entry, 2, 1)
        self.e_drills_button = FCButton(_("Extract Drills"), bold=True)
        self.e_drills_button.setIcon(QtGui.QIcon(self.app.resource_location + '/drill16.png'))
        self.e_drills_button.setToolTip(_("Extract drills from a given Gerber file."))
        self.tools_box.addWidget(self.e_drills_button)

        # Soldermask
        self.extract_sm_label = FCLabel('%s' % _("Extract Soldermask"), color='purple', bold=True)
        self.extract_sm_label.setToolTip(_("Extract soldermask from a given Gerber file."))
        self.tools_box.addWidget(self.extract_sm_label)
        self.es_frame = FCFrame()
        self.tools_box.addWidget(self.es_frame)
        es_grid = GLay(v_spacing=5, h_spacing=3)
        self.es_frame.setLayout(es_grid)
        self.clearance_label = FCLabel('%s:' % _("Clearance"))
        self.clearance_label.setToolTip(
            _("This set how much the soldermask extends\n"
              "beyond the margin of the pads.")
        )
        self.clearance_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_entry.set_range(0.0000, 10000.0000)
        self.clearance_entry.set_precision(self.decimals)
        self.clearance_entry.setSingleStep(0.1)
        es_grid.addWidget(self.clearance_label, 0, 0)
        es_grid.addWidget(self.clearance_entry, 0, 1)
        self.e_sm_button = FCButton(_("Extract Soldermask"))
        self.e_sm_button.setIcon(QtGui.QIcon(self.app.resource_location + '/extract32.png'))
        self.e_sm_button.setToolTip(_("Extract soldermask from a given Gerber file."))
        self.e_sm_button.bold = True
        self.tools_box.addWidget(self.e_sm_button)

        # Cutout
        self.extract_cut_label = FCLabel('%s' % _("Extract Cutout"), color='blue', bold=True)
        self.extract_cut_label.setToolTip(_("Extract a cutout from a given Gerber file."))
        self.tools_box.addWidget(self.extract_cut_label)
        self.ec_frame = FCFrame()
        self.tools_box.addWidget(self.ec_frame)
        ec_grid = GLay(v_spacing=5, h_spacing=3)
        self.ec_frame.setLayout(ec_grid)
        self.margin_cut_label = FCLabel('%s:' % _("Margin"))
        self.margin_cut_label.setToolTip(
            _("Margin over bounds. A positive value here\n"
              "will make the cutout of the PCB further from\n"
              "the actual PCB border")
        )
        self.margin_cut_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.margin_cut_entry.set_range(-10000.0000, 10000.0000)
        self.margin_cut_entry.set_precision(self.decimals)
        self.margin_cut_entry.setSingleStep(0.1)
        ec_grid.addWidget(self.margin_cut_label, 0, 0)
        ec_grid.addWidget(self.margin_cut_entry, 0, 1)
        self.thick_cut_label = FCLabel('%s:' % _("Thickness"))
        self.thick_cut_label.setToolTip(_("The thickness of the line that makes the cutout geometry."))
        self.thick_cut_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.thick_cut_entry.set_range(0.0000, 10000.0000)
        self.thick_cut_entry.set_precision(self.decimals)
        self.thick_cut_entry.setSingleStep(0.1)
        ec_grid.addWidget(self.thick_cut_label, 2, 0)
        ec_grid.addWidget(self.thick_cut_entry, 2, 1)
        GLay.set_common_column_size(
            [grid1, grid_lay, ring_grid, ec_grid, prop_grid, fixed_grid, ring_grid, es_grid, pad_all_grid, pad_grid], 0)
        self.e_cut_button = FCButton(_("Extract Cutout"))
        self.e_cut_button.setIcon(QtGui.QIcon(self.app.resource_location + '/extract32.png'))
        self.e_cut_button.setToolTip(_("Extract a cutout from a given Gerber file."))
        self.e_cut_button.bold = True
        self.tools_box.addWidget(self.e_cut_button)
        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)
        self.ring_frame.hide()
        self.fix_frame.hide()
        self.prop_frame.hide()

    def set_drill_method(self, val):
        if val == "fixed":
            self.fixed_label.show()
            self.fix_frame.show()
            self.ring_label.hide()
            self.ring_frame.hide()
            self.prop_label.hide()
            self.prop_frame.hide()
        elif val == "ring":
            self.fixed_label.hide()
            self.fix_frame.hide()
            self.ring_label.show()
            self.ring_frame.show()
            self.circular_ring_entry.setEnabled(self.circular_cb.get_value())
            self.oblong_ring_entry.setEnabled(self.oblong_cb.get_value())
            self.square_ring_entry.setEnabled(self.square_cb.get_value())
            self.rectangular_ring_entry.setEnabled(self.rectangular_cb.get_value())
            self.other_ring_entry.setEnabled(self.other_cb.get_value())
            self.prop_label.hide()
            self.prop_frame.hide()
        elif val == "prop":
            self.fixed_label.hide()
            self.fix_frame.hide()
            self.ring_label.hide()
            self.ring_frame.hide()
            self.prop_label.show()
            self.prop_frame.show()

    def populate_apertures(self, tools, sorted_apertures):
        n = 0
        for ap_code in sorted_apertures:
            ap_type = tools[ap_code]['type']
            if ap_type == 'C' and self.circular_cb.get_value() is True:
                n += 1
            if ap_type == 'R':
                if self.square_cb.get_value() is True:
                    n += 1
                elif self.rectangular_cb.get_value() is True:
                    n += 1
            if ap_type == 'O' and self.oblong_cb.get_value() is True:
                n += 1
            if ap_type not in ['C', 'R', 'O'] and self.other_cb.get_value() is True:
                n += 1
        self.apertures_table.setRowCount(n)

        row = 0
        for ap_code in sorted_apertures:
            ap_type = tools[ap_code]['type']
            if ap_type == 'C':
                if self.circular_cb.get_value() is False:
                    continue
            elif ap_type == 'R':
                if self.square_cb.get_value() is True:
                    pass
                elif self.rectangular_cb.get_value() is True:
                    pass
                else:
                    continue
            elif ap_type == 'O':
                if self.oblong_cb.get_value() is False:
                    continue
            elif self.other_cb.get_value() is True:
                pass
            else:
                continue

            ap_code_item = QtWidgets.QTableWidgetItem(str(ap_code))
            ap_code_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            ap_type_item = QtWidgets.QTableWidgetItem(str(ap_type))
            ap_type_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            try:
                if tools[ap_code]['size'] is not None:
                    size_val = self.app.dec_format(float(tools[ap_code]['size']), self.decimals)
                    ap_size_item = QtWidgets.QTableWidgetItem(str(size_val))
                else:
                    ap_size_item = QtWidgets.QTableWidgetItem('')
            except KeyError:
                ap_size_item = QtWidgets.QTableWidgetItem('')
            ap_size_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

            mark_item = FCCheckBox()
            mark_item.setLayoutDirection(QtCore.Qt.LayoutDirection.RightToLeft)
            empty_plot_item = QtWidgets.QTableWidgetItem('')
            empty_plot_item.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            empty_plot_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.apertures_table.setItem(row, 0, ap_code_item)
            self.apertures_table.setItem(row, 1, ap_type_item)
            self.apertures_table.setItem(row, 2, ap_size_item)
            self.apertures_table.setItem(row, 3, empty_plot_item)
            self.apertures_table.setCellWidget(row, 3, mark_item)
            row += 1

        self.apertures_table.selectColumn(0)
        self.apertures_table.resizeColumnsToContents()
        self.apertures_table.resizeRowsToContents()
        vertical_header = self.apertures_table.verticalHeader()
        vertical_header.hide()
        horizontal_header = self.apertures_table.horizontalHeader()
        horizontal_header.setMinimumSectionSize(10)
        horizontal_header.setDefaultSectionSize(70)
        horizontal_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(3, 17)
        self.apertures_table.setColumnWidth(3, 17)
        self.apertures_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.apertures_table.setSortingEnabled(False)

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
