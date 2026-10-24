from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCComboBox2, RadioSet, FCDoubleSpinner, NumericalEvalTupleEntry

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class MarkersUI:

    pluginName = _("Markers")

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
            _(
                "Beginner Mode - many parameters are hidden.\n"
                "Advanced Mode - full control.\n"
                "Permanent change is done in 'Preferences' menu."
            )
        )
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)
        self.title_box = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.title_box)

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # Gerber Source Object
        self.object_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.object_label.setToolTip(_("The Gerber object to which will be added corner markers."))
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = False
        self.object_combo.obj_type = "Gerber"
        self.tools_box.addWidget(self.object_label)
        self.tools_box.addWidget(self.object_combo)

        # Parameters Frame
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters used for this tool."))
        self.tools_box.addWidget(self.param_label)
        par_frame = FCFrame()
        self.tools_box.addWidget(par_frame)
        param_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(param_grid)

        self.type_label = FCLabel('%s:' % _("Type"))
        self.type_label.setToolTip(
            _("Shape of the marker.")
        )
        self.type_radio = RadioSet([
            {"label": _("Semi-Cross"), "value": "s"},
            {"label": _("Cross"), "value": "c"},
        ])
        param_grid.addWidget(self.type_label, 2, 0)
        param_grid.addWidget(self.type_radio, 2, 1)

        self.thick_label = FCLabel('%s:' % _("Thickness"))
        self.thick_label.setToolTip(
            _("The thickness of the line that makes the corner marker.")
        )
        self.thick_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.thick_entry.set_range(10 ** -self.decimals, 10.0000)
        self.thick_entry.set_precision(self.decimals)
        self.thick_entry.setWrapping(True)
        self.thick_entry.setSingleStep(10 ** -self.decimals)
        param_grid.addWidget(self.thick_label, 4, 0)
        param_grid.addWidget(self.thick_entry, 4, 1)
        param_grid.addWidget(FCLabel("%s" % self.units), 4, 2)

        self.l_label = FCLabel('%s:' % _("Length"))
        self.l_label.setToolTip(
            _("The length of the line that makes the corner marker.")
        )
        self.l_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.l_entry.set_range(10 ** -self.decimals, 10000.0000)
        self.l_entry.set_precision(self.decimals)
        self.l_entry.setSingleStep(10 ** -self.decimals)
        param_grid.addWidget(self.l_label, 6, 0)
        param_grid.addWidget(self.l_entry, 6, 1)
        param_grid.addWidget(FCLabel("%s" % self.units), 6, 2)

        # Offset Frame
        self.offset_title_label = FCLabel('%s' % _("Offset"), color='magenta', bold=True)
        self.offset_title_label.setToolTip(_("Offset locations from the set reference."))
        self.tools_box.addWidget(self.offset_title_label)
        self.off_frame = FCFrame()
        self.tools_box.addWidget(self.off_frame)
        off_grid = GLay(v_spacing=5, h_spacing=3)
        self.off_frame.setLayout(off_grid)

        self.ref_label = FCLabel('%s:' % _("Reference"))
        self.ref_label.setToolTip(
            _("Reference for offseting the marker locations.\n"
              "- Edge - referenced from the bounding box edge\n"
              "- Center - referenced from the bounding box center")
        )
        self.ref_radio = RadioSet([
            {"label": _("Edge"), "value": "e"},
            {"label": _("Center"), "value": "c"},
        ])
        off_grid.addWidget(self.ref_label, 0, 0)
        off_grid.addWidget(self.ref_radio, 0, 1, 1, 2)

        self.offset_x_label = FCLabel('%s X:' % _("Offset"))
        self.offset_x_label.setToolTip(
            _("Offset on the X axis.")
        )
        self.offset_x_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.offset_x_entry.set_range(-10000.0000, 10000.0000)
        self.offset_x_entry.set_precision(self.decimals)
        self.offset_x_entry.setSingleStep(0.1)
        off_grid.addWidget(self.offset_x_label, 2, 0)
        off_grid.addWidget(self.offset_x_entry, 2, 1)
        off_grid.addWidget(FCLabel("%s" % self.units), 2, 2)

        self.offset_y_label = FCLabel('%s Y:' % _("Offset"))
        self.offset_y_label.setToolTip(
            _("Offset on the Y axis.")
        )
        self.offset_y_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.offset_y_entry.set_range(-10000.0000, 10000.0000)
        self.offset_y_entry.set_precision(self.decimals)
        self.offset_y_entry.setSingleStep(0.1)
        off_grid.addWidget(self.offset_y_label, 3, 0)
        off_grid.addWidget(self.offset_y_entry, 3, 1)
        off_grid.addWidget(FCLabel("%s" % self.units), 3, 2)

        self.offset_link_button = QtWidgets.QToolButton()
        self.offset_link_button.setIcon(QtGui.QIcon(self.app.resource_location + '/link32.png'))
        self.offset_link_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                                              QtWidgets.QSizePolicy.Policy.Expanding)
        self.offset_link_button.setCheckable(True)
        off_grid.addWidget(self.offset_link_button, 2, 3, 2, 1)

        # Locations Frame
        self.locs_label = FCLabel('%s' % _("Locations"), color='red', bold=True)
        self.locs_label.setToolTip(_("Locations where to place corner markers."))
        self.tools_box.addWidget(self.locs_label)
        self.loc_frame = FCFrame()
        self.tools_box.addWidget(self.loc_frame)
        grid_loc = GLay(v_spacing=5, h_spacing=3)
        self.loc_frame.setLayout(grid_loc)

        self.tl_cb = FCCheckBox(_("Top Left"))
        grid_loc.addWidget(self.tl_cb, 0, 0)
        self.tr_cb = FCCheckBox(_("Top Right"))
        grid_loc.addWidget(self.tr_cb, 0, 1)
        self.bl_cb = FCCheckBox(_("Bottom Left"))
        grid_loc.addWidget(self.bl_cb, 2, 0)
        self.br_cb = FCCheckBox(_("Bottom Right"))
        grid_loc.addWidget(self.br_cb, 2, 1)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid_loc.addWidget(separator_line, 4, 0, 1, 2)
        self.toggle_all_cb = FCCheckBox(_("Toggle ALL"))
        grid_loc.addWidget(self.toggle_all_cb, 6, 0, 1, 2)

        # Selection Frame
        self.sel_label = FCLabel('%s' % _("Selection"), color='green', bold=True)
        self.tools_box.addWidget(self.sel_label)
        self.s_frame = FCFrame()
        self.tools_box.addWidget(self.s_frame)
        grid_sel = GLay(v_spacing=5, h_spacing=3)
        self.s_frame.setLayout(grid_sel)
        self.mode_label = FCLabel('%s: ' % _("Mode"))
        self.mode_label.setToolTip(
            _("When the manual type is chosen, the markers\n"
              "are manually placed on canvas.")
        )
        self.mode_combo = FCComboBox2()
        self.mode_combo.addItems([_("Auto"), _("Manual"), _("Numeric")])
        grid_sel.addWidget(self.mode_label, 0, 0)
        grid_sel.addWidget(self.mode_combo, 0, 1)

        self.big_cursor_cb = FCCheckBox('%s' % _("Big cursor"))
        self.big_cursor_cb.setToolTip(
            _("Use a big cursor."))
        grid_sel.addWidget(self.big_cursor_cb, 2, 0, 1, 2)
        self.marker_coords_lbl = FCLabel('%s:' % _("Coordinates"))
        self.marker_coords_lbl.setToolTip(
            _("Tuple of marker coordinates.")
        )
        self.marker_coords_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.marker_coords_entry.setPlaceholderText(_("Comma separated values"))
        grid_sel.addWidget(self.marker_coords_lbl, 4, 0)
        grid_sel.addWidget(self.marker_coords_entry, 4, 1)

        self.add_marker_button = FCButton(_("Add Marker"), bold=True)
        self.add_marker_button.setIcon(QtGui.QIcon(self.app.resource_location + '/corners_32.png'))
        self.add_marker_button.setToolTip(
            _("Will add corner markers to the selected object.")
        )
        self.tools_box.addWidget(self.add_marker_button,)

        # Drill in markers Frame
        self.drills_label = FCLabel('%s' % _("Drills in Locations"), color='brown', bold=True)
        self.tools_box.addWidget(self.drills_label)
        self.drill_frame = FCFrame()
        self.tools_box.addWidget(self.drill_frame)
        grid_drill = GLay(v_spacing=5, h_spacing=3)
        self.drill_frame.setLayout(grid_drill)
        self.drill_dia_label = FCLabel('%s:' % _("Drill Dia"))
        self.drill_dia_label.setToolTip(
            '%s.' % _("Drill Diameter")
        )
        self.drill_dia_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.drill_dia_entry.set_range(0.0000, 100.0000)
        self.drill_dia_entry.set_precision(self.decimals)
        self.drill_dia_entry.setWrapping(True)
        grid_drill.addWidget(self.drill_dia_label, 0, 0)
        grid_drill.addWidget(self.drill_dia_entry, 0, 1)
        grid_drill.addWidget(FCLabel("%s" % self.units), 0, 2)
        self.drill_button = FCButton(_("Create Excellon Object"), bold=True)
        self.drill_button.setIcon(QtGui.QIcon(self.app.resource_location + '/drill32.png'))
        self.drill_button.setToolTip(
            _("Will add drill holes in the center of the markers.")
        )
        self.tools_box.addWidget(self.drill_button)

        # Check in Locations Frame
        self.check_label = FCLabel('%s' % _("Check in Locations"), color='indigo', bold=True)
        self.tools_box.addWidget(self.check_label)
        self.check_button = FCButton(_("Create Excellon Object"), bold=True)
        self.check_button.setIcon(QtGui.QIcon(self.app.resource_location + '/drill32.png'))
        self.check_button.setToolTip(
            _("Will create an Excellon object using a special preprocessor.\n"
              "The spindle will not start and the mounted probe will move to\n"
              "the corner locations, wait for the user interaction and then\n"
              "move to the next location until the last one.")
        )
        self.tools_box.addWidget(self.check_button)

        # Insert Markers Frame
        self.insert_label = FCLabel('%s' % _("Insert Markers"), color='teal', bold=True)
        self.insert_label.setToolTip(
            _("Enabled only if markers are available (added to an object).\n"
              "Those markers will be inserted in yet another object.")
        )
        self.tools_box.addWidget(self.insert_label)
        self.insert_frame = FCFrame()
        self.tools_box.addWidget(self.insert_frame)
        insert_grid = GLay(v_spacing=5, h_spacing=3)
        self.insert_frame.setLayout(insert_grid)
        self.insert_type_label = FCLabel('%s:' % _("Type"))
        self.insert_type_label.setToolTip(
            _("Specify the type of object where the markers are inserted.")
        )
        self.insert_type_radio = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                           {'label': _('Geometry'), 'value': 'geo'}])
        insert_grid.addWidget(self.insert_type_label, 0, 0)
        insert_grid.addWidget(self.insert_type_radio, 0, 1)
        self.obj_insert_combo = FCComboBox()
        self.obj_insert_combo.setModel(self.app.collection)
        self.obj_insert_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.obj_insert_combo.is_last = False
        insert_grid.addWidget(self.obj_insert_combo, 2, 0, 1, 2)
        self.insert_markers_button = FCButton(_("Insert Marker"), bold=True)
        self.insert_markers_button.setIcon(QtGui.QIcon(self.app.resource_location + '/corners_32.png'))
        self.insert_markers_button.setToolTip(
            _("Will add corner markers to the selected object.")
        )
        self.tools_box.addWidget(self.insert_markers_button)
        GLay.set_common_column_size([grid_sel, param_grid, off_grid, grid_loc, grid_drill, insert_grid], 0)
        self.layout.addStretch(1)

        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.layout.addWidget(self.reset_button)
        self.offset_link_button.clicked.connect(self.on_link_checked)
        self.offset_x_entry.returnPressed.connect(self.on_marginx_edited)

    @staticmethod
    def draw_utility_geometry(shapes, geometry):
        outline = '#0000FFAF'
        for shp in geometry:
            shapes.add(shp, color=outline, update=True, layer=0, tolerance=None)
        shapes.redraw()

    def on_level_changed(self, checked):
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)
            self.drills_label.hide()
            self.drill_frame.hide()
            self.drill_button.hide()
            self.check_label.hide()
            self.check_button.hide()
            self.insert_label.hide()
            self.insert_frame.hide()
            self.insert_markers_button.hide()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)
            self.drills_label.show()
            self.drill_frame.show()
            self.drill_button.show()
            self.check_label.show()
            self.check_button.show()
            self.insert_label.show()
            self.insert_frame.show()
            self.insert_markers_button.show()

    def on_toggle_all(self, val):
        self.bl_cb.set_value(val)
        self.br_cb.set_value(val)
        self.tl_cb.set_value(val)
        self.tr_cb.set_value(val)

    def on_selection_changed(self, val):
        if val == 0:    # 'auto'
            self.locs_label.setDisabled(False)
            self.loc_frame.setDisabled(False)
            self.type_label.setDisabled(False)
            self.type_radio.setDisabled(False)
            self.off_frame.setDisabled(False)
            self.marker_coords_lbl.setVisible(False)
            self.marker_coords_entry.setVisible(False)
            self.big_cursor_cb.hide()
        elif val == 1:  # 'manual'
            self.locs_label.setDisabled(True)
            self.loc_frame.setDisabled(True)
            self.type_label.setDisabled(True)
            self.type_radio.setDisabled(True)
            self.off_frame.setDisabled(True)
            self.type_radio.set_value('c')
            self.marker_coords_lbl.setVisible(False)
            self.marker_coords_entry.setVisible(False)
            self.big_cursor_cb.show()
        else:   # 'numeric'
            self.locs_label.setDisabled(True)
            self.loc_frame.setDisabled(True)
            self.type_radio.set_value('c')
            self.type_label.setDisabled(True)
            self.type_radio.setDisabled(True)
            self.off_frame.setDisabled(True)
            self.marker_coords_lbl.setVisible(True)
            self.marker_coords_entry.setVisible(True)
            self.big_cursor_cb.hide()

    def on_points_changed(self, points):
        if points:
            self.insert_frame.setDisabled(False)
            self.insert_markers_button.setDisabled(False)
        else:
            self.insert_frame.setDisabled(True)
            self.insert_markers_button.setDisabled(True)

    def on_link_checked(self, checked):
        if checked:
            self.offset_x_label.set_value('%s:' % _("Offset"))
            self.offset_y_label.setDisabled(True)
            self.offset_y_entry.setDisabled(True)
            self.offset_y_entry.set_value(self.offset_x_entry.get_value())
        else:
            self.offset_x_label.set_value('%s X:' % _("Offset"))
            self.offset_y_label.setDisabled(False)
            self.offset_y_entry.setDisabled(False)

    def on_marginx_edited(self):
        if self.offset_link_button.isChecked():
            self.offset_y_entry.set_value(self.offset_x_entry.get_value())

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
