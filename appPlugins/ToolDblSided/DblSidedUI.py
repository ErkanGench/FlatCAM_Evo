from PyQt6 import QtWidgets, QtGui, QtCore
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, RadioSet, \
    FCDoubleSpinner, FCComboBox2, NumericalEvalTupleEntry, FCCheckBox

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class DsidedUI:

    pluginName = _("2-Sided")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)
        self.title_box = QtWidgets.QHBoxLayout()
        self.tools_box.addLayout(self.title_box)

        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Mirror and align PCB layers and create alignment drills.")
        )
        self.title_box.addWidget(title_label)

        self.level = QtWidgets.QToolButton()
        self.level.setToolTip(
            _("Beginner Mode - many parameters are hidden.\n"
              "Advanced Mode - full control.\n"
              "Permanent change is done in 'Preferences' menu.")
        )
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)

        common_box = self.tools_box
        self.basic_frame = QtWidgets.QFrame()
        common_box.addWidget(self.basic_frame)
        self.build_basic()
        self.advanced_frame = QtWidgets.QFrame()
        common_box.addWidget(self.advanced_frame)
        self.tools_box = QtWidgets.QVBoxLayout(self.advanced_frame)
        self.tools_box.setContentsMargins(0, 0, 0, 0)

        # Source Object
        self.m_objects_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.m_objects_label.setToolTip('%s.' % _("Objects to be mirrored"))
        self.tools_box.addWidget(self.m_objects_label)
        source_frame = FCFrame()
        self.tools_box.addWidget(source_frame)
        obj_grid = GLay(v_spacing=5, h_spacing=3)
        source_frame.setLayout(obj_grid)

        self.type_obj_combo_label = FCLabel('%s:' % _("Target"))
        self.type_obj_combo_label.setToolTip(
            _("Select the type of application object to be processed in this tool.")
        )
        self.object_type_combo = FCComboBox2()
        self.object_type_combo.addItems([_("Gerber"), _("Excellon"), _("Geometry")])
        obj_grid.addWidget(self.type_obj_combo_label, 0, 0)
        obj_grid.addWidget(self.object_type_combo, 0, 1)
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = True
        obj_grid.addWidget(self.object_combo, 2, 0, 1, 2)

        # Bounds
        self.bv_label = FCLabel('%s' % _("Bounds Values"), color='purple', bold=True)
        self.bv_label.setToolTip(
            _("Select on canvas the object(s)\n"
              "for which to calculate bounds values.")
        )
        self.tools_box.addWidget(self.bv_label)
        self.bounds_frame = FCFrame()
        self.tools_box.addWidget(self.bounds_frame)
        grid_bounds = GLay(v_spacing=5, h_spacing=3)
        self.bounds_frame.setLayout(grid_bounds)

        self.xmin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.xmin_entry.set_precision(self.decimals)
        self.xmin_entry.set_range(-10000.0000, 10000.0000)
        self.xmin_btn = FCButton('%s:' % _("X min"))
        self.xmin_btn.setToolTip(_("Minimum location."))
        self.xmin_entry.setReadOnly(True)
        grid_bounds.addWidget(self.xmin_btn, 0, 0)
        grid_bounds.addWidget(self.xmin_entry, 0, 1)

        self.ymin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.ymin_entry.set_precision(self.decimals)
        self.ymin_entry.set_range(-10000.0000, 10000.0000)
        self.ymin_btn = FCButton('%s:' % _("Y min"))
        self.ymin_btn.setToolTip(_("Minimum location."))
        self.ymin_entry.setReadOnly(True)
        grid_bounds.addWidget(self.ymin_btn, 2, 0)
        grid_bounds.addWidget(self.ymin_entry, 2, 1)

        self.xmax_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.xmax_entry.set_precision(self.decimals)
        self.xmax_entry.set_range(-10000.0000, 10000.0000)
        self.xmax_btn = FCButton('%s:' % _("X max"))
        self.xmax_btn.setToolTip(_("Maximum location."))
        self.xmax_entry.setReadOnly(True)
        grid_bounds.addWidget(self.xmax_btn, 4, 0)
        grid_bounds.addWidget(self.xmax_entry, 4, 1)

        self.ymax_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.ymax_entry.set_precision(self.decimals)
        self.ymax_entry.set_range(-10000.0000, 10000.0000)
        self.ymax_btn = FCButton('%s:' % _("Y max"))
        self.ymax_btn.setToolTip(_("Maximum location."))
        self.ymax_entry.setReadOnly(True)
        grid_bounds.addWidget(self.ymax_btn, 6, 0)
        grid_bounds.addWidget(self.ymax_entry, 6, 1)

        self.center_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.center_entry.setPlaceholderText(_("Center point coordinates"))
        self.center_btn = FCButton('%s:' % _("Centroid"))
        self.center_btn.setToolTip(
            _("The center point location for the rectangular\n"
              "bounding shape. Centroid. Format is (x, y).")
        )
        self.center_entry.setReadOnly(True)
        grid_bounds.addWidget(self.center_btn, 8, 0)
        grid_bounds.addWidget(self.center_entry, 8, 1)

        self.calculate_bb_button = FCButton(_("Calculate Bounds Values"), bold=True)
        self.calculate_bb_button.setToolTip(
            _("Calculate the enveloping rectangular shape coordinates,\n"
              "for the selection of objects.\n"
              "The envelope shape is parallel with the X, Y axis.")
        )
        self.tools_box.addWidget(self.calculate_bb_button)

        # Mirror operation
        self.param_label = FCLabel('%s' % _("Mirror Operation"), color='blue', bold=True)
        self.param_label.setToolTip('%s.' % _("Parameters for the mirror operation"))
        self.tools_box.addWidget(self.param_label)
        mirror_frame = FCFrame()
        self.tools_box.addWidget(mirror_frame)
        grid_mirror = GLay(v_spacing=5, h_spacing=3)
        mirror_frame.setLayout(grid_mirror)
        self.mirax_label = FCLabel('%s:' % _("Axis"))
        self.mirax_label.setToolTip(_("Mirror vertically (X) or horizontally (Y)."))
        self.mirror_axis = RadioSet(
            [{'label': 'X', 'value': 'X'}, {'label': 'Y', 'value': 'Y'}], compact=True)
        grid_mirror.addWidget(self.mirax_label, 2, 0)
        grid_mirror.addWidget(self.mirror_axis, 2, 1, 1, 2)
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid_mirror.addWidget(separator_line, 3, 0, 1, 3)

        self.axloc_label = FCLabel('%s:' % _("Reference"), bold=True)
        self.axloc_label.setToolTip(
            _("The coordinates used as reference for the mirror operation.\n"
              "Can be:\n"
              "- Point -> a set of coordinates (x,y) around which the object is mirrored\n"
              "- Box -> a set of coordinates (x, y) obtained from the center of the\n"
              "bounding box of another object selected below\n"
              "- Snap -> a point defined by the center of a drill hole in a Excellon object")
        )
        self.axis_location = RadioSet(
            [{'label': _('Point'), 'value': 'point'}, {'label': _('Box'), 'value': 'box'},
             {'label': _('Snap'), 'value': 'hole'}], compact=True)
        grid_mirror.addWidget(self.axloc_label, 4, 0)
        grid_mirror.addWidget(self.axis_location, 4, 1, 1, 2)
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid_mirror.addWidget(separator_line, 7, 0, 1, 3)

        # Point reference
        self.pr_frame = QtWidgets.QFrame()
        self.pr_frame.setContentsMargins(0, 0, 0, 0)
        grid_mirror.addWidget(self.pr_frame, 9, 0, 1, 3)
        self.point_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.point_entry.setPlaceholderText(_("Point coordinates"))
        pr_hlay = QtWidgets.QHBoxLayout()
        pr_hlay.setContentsMargins(0, 0, 0, 0)
        self.pr_frame.setLayout(pr_hlay)
        self.add_point_button = QtWidgets.QToolButton()
        self.add_point_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_point_button.setIcon(QtGui.QIcon(self.app.resource_location + '/plus16.png'))
        self.add_point_button.setText(_("Add"))
        self.add_point_button.setToolTip(
            _("Add the coordinates in format <b>(x, y)</b> through which the mirroring axis\n "
              "selected in 'MIRROR AXIS' pass.\n"
              "The (x, y) coordinates are captured by pressing SHIFT key\n"
              "and left mouse button click on canvas or you can enter the coordinates manually.")
        )
        pr_hlay.addWidget(self.point_entry, stretch=1)
        pr_hlay.addWidget(self.add_point_button)

        # Box reference
        self.br_frame = QtWidgets.QFrame()
        self.br_frame.setContentsMargins(0, 0, 0, 0)
        grid_mirror.addWidget(self.br_frame, 11, 0, 1, 3)
        grid_box_ref = GLay(v_spacing=5, h_spacing=3)
        grid_box_ref.setContentsMargins(0, 0, 0, 0)
        self.br_frame.setLayout(grid_box_ref)
        self.box_type_radio = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                        {'label': _('Excellon'), 'value': 'exc'},
                                        {'label': _('Geometry'), 'value': 'geo'}])
        self.box_type_radio.setToolTip(
            _("It can be of type: Gerber or Excellon or Geometry.\n"
              "The coordinates of the center of the bounding box are used\n"
              "as reference for mirror operation.")
        )
        grid_box_ref.addWidget(self.box_type_radio, 0, 0, 1, 2)
        self.box_combo = FCComboBox()
        self.box_combo.setModel(self.app.collection)
        self.box_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.box_combo.is_last = True
        grid_box_ref.addWidget(self.box_combo, 2, 0, 1, 2)

        # Snap hole reference
        self.sr_frame = QtWidgets.QFrame()
        self.sr_frame.setContentsMargins(0, 0, 0, 0)
        grid_mirror.addWidget(self.sr_frame, 13, 0, 1, 3)
        grid_snap_ref = GLay(v_spacing=5, h_spacing=3)
        grid_snap_ref.setContentsMargins(0, 0, 0, 0)
        self.sr_frame.setLayout(grid_snap_ref)
        self.exc_hole_lbl = FCLabel('%s' % _("Excellon"), bold=True)
        self.exc_hole_lbl.setToolTip(_("Object that holds holes that can be picked as reference for mirroring."))
        self.exc_combo = FCComboBox()
        self.exc_combo.setModel(self.app.collection)
        self.exc_combo.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.exc_combo.is_last = True
        grid_snap_ref.addWidget(self.exc_hole_lbl, 0, 0, 1, 2)
        grid_snap_ref.addWidget(self.exc_combo, 2, 0, 1, 2)
        self.pick_hole_button = FCButton(_("Pick hole"))
        self.pick_hole_button.setToolTip(
            _("Click inside a drill hole that belong to the selected Excellon object,\n"
              "and the hole center coordinates will be copied to the Point field.")
        )
        grid_snap_ref.addWidget(self.pick_hole_button, 4, 0, 1, 2)

        self.mirror_button = FCButton(_("Mirror"), bold=True)
        self.mirror_button.setIcon(QtGui.QIcon(self.app.resource_location + '/doubleside16.png'))
        self.mirror_button.setToolTip(
            _("Mirrors (flips) the specified object around \n"
              "the specified axis. Does not create a new \n"
              "object, but modifies it.")
        )
        self.tools_box.addWidget(self.mirror_button)

        # Alignment operation
        self.alignment_label = FCLabel('%s' % _("PCB Alignment"), color='brown', bold=True)
        self.alignment_label.setToolTip(
            _("Creates an Excellon Object containing the\n"
              "specified alignment holes and their mirror\n"
              "images.")
        )
        self.tools_box.addWidget(self.alignment_label)
        align_frame = FCFrame()
        self.tools_box.addWidget(align_frame)
        grid4 = GLay(v_spacing=5, h_spacing=3)
        align_frame.setLayout(grid4)
        self.dt_label = FCLabel("%s:" % _('Drill Dia'))
        self.dt_label.setToolTip(_("Diameter of the drill for the alignment holes."))
        self.drill_dia = FCDoubleSpinner(callback=self.confirmation_message)
        self.drill_dia.setToolTip(_("Diameter of the drill for the alignment holes."))
        self.drill_dia.set_precision(self.decimals)
        self.drill_dia.set_range(0.0000, 10000.0000)
        grid4.addWidget(self.dt_label, 2, 0)
        grid4.addWidget(self.drill_dia, 2, 1)
        self.align_type_label = FCLabel('%s:' % _("Type"))
        self.align_type_label.setToolTip(
            _("The content of the Excellon file.\n"
              "X - Pairs of drill holes mirrored vertically from reference point\n"
              "Y - Pairs of drill holes mirrored horizontally from reference point\n"
              "Manual - no mirroring; drill holes in place")
        )
        self.align_type_radio = RadioSet(
            [{'label': 'X', 'value': 'X'}, {'label': 'Y', 'value': 'Y'},
             {'label': _("Manual"), 'value': 'manual'}], compact=True)
        grid4.addWidget(self.align_type_label, 4, 0)
        grid4.addWidget(self.align_type_radio, 4, 1)
        self.align_ref_label = FCLabel('%s:' % _("Reference"))
        self.align_ref_label.setToolTip(
            _("The reference point used to create the second alignment drill\n"
              "from the first alignment drill, by doing mirror.\n"
              "It can be modified in the Mirror Parameters -> Reference section")
        )
        self.align_ref_label_val = NumericalEvalTupleEntry(border_color='#0069A9')
        self.align_ref_label_val.setToolTip(
            _("The reference point used to create the second alignment drill\n"
              "from the first alignment drill, by doing mirror.\n"
              "It can be modified in the Mirror Parameters -> Reference section")
        )
        self.align_ref_label_val.setDisabled(True)
        grid4.addWidget(self.align_ref_label, 6, 0)
        grid4.addWidget(self.align_ref_label_val, 6, 1)
        self.ah_label = FCLabel("%s:" % _('Drill Coordinates'))
        self.ah_label.setToolTip(
            _("Alignment holes (x1, y1), (x2, y2), ... \n"
              "If the type is X or Y then for each pair of coordinates\n"
              "two drill points will be added: one with the given coordinates,\n"
              "and the other will be mirrored as set in the 'Mirror' section.\n"
              "If the type is 'Manual' then no mirror point is generated.\n"
              "\n"
              "Shift + mouse click will add one set of coordinates.\n"
              "Ctrl + Shift + mouse click will accumulate sets of coordinates. ")
        )
        grid4.addWidget(self.ah_label, 8, 0, 1, 2)
        self.alignment_holes = NumericalEvalTupleEntry(border_color='#0069A9')
        self.alignment_holes.setPlaceholderText(_("Drill coordinates"))
        self.delete_drill_point_button = QtWidgets.QToolButton()
        self.delete_drill_point_button.setIcon(QtGui.QIcon(self.app.resource_location + '/trash32.png'))
        self.delete_drill_point_button.setToolTip(_("Delete the last coordinates tuple in the list."))
        hlay = QtWidgets.QHBoxLayout()
        hlay.addWidget(self.alignment_holes)
        hlay.addWidget(self.delete_drill_point_button)
        grid4.addLayout(hlay, 9, 0, 1, 2)
        GLay.set_common_column_size([obj_grid, grid_bounds, grid_mirror, grid_box_ref, grid4], 0)

        self.gen_param_label = FCLabel(_("Common Parameters"), color='indigo', bold=True)
        self.tools_box.addWidget(self.gen_param_label)
        creation_frame = FCFrame()
        creation_frame.setLayout(GLay(v_spacing=5, h_spacing=3))
        self.tools_box.addWidget(creation_frame)

        self.create_excellon_button = FCButton(_("Create Excellon Object"), bold=True)
        self.create_excellon_button.setIcon(QtGui.QIcon(self.app.resource_location + '/drill32.png'))
        self.create_excellon_button.setToolTip(
            _("Creates an Excellon Object containing the\n"
              "specified alignment holes and their mirror\n"
              "images.")
        )
        self.tools_box.addWidget(self.create_excellon_button)
        self.tools_box = common_box
        self.tools_box.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.tools_box.addWidget(self.reset_button)
        self.align_type_radio.activated_custom.connect(self.on_align_type_changed)

    def build_basic(self):
        layout = QtWidgets.QVBoxLayout(self.basic_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(FCLabel(_("Source Objects"), color='darkorange', bold=True))
        source_frame = FCFrame()
        layout.addWidget(source_frame)
        grid = GLay(v_spacing=5, h_spacing=3)
        source_frame.setLayout(grid)
        self.top_combo, self.bottom_combo, self.drills_combo = FCComboBox(), FCComboBox(), FCComboBox()
        self.basic_combos = (self.top_combo, self.bottom_combo, self.drills_combo)
        tooltips = (_("The side that is milled first. It is never mirrored."),
                    _("The side that is milled after turning the board over left/right onto the pins.\n"
                      "It is mirrored in place about the vertical center line of all sources."),
                    _("The Excellon object with the drill holes. It is never mirrored."))
        for row, (label, combo, tooltip) in enumerate(zip((_('Top'), _('Bottom'), _('Drills')),
                                                          self.basic_combos, tooltips)):
            grid.addWidget(FCLabel('%s:' % label), row, 0)
            combo.addItem('')
            combo.setToolTip(tooltip)
            grid.addWidget(combo, row, 1)

        self.type_combo = FCComboBox2()
        self.type_combo.addItems([_('L-R'), _('T-B')])
        self.type_combo.setToolTip(_("L-R: the board is turned over left/right.\n"
                                     "T-B: the board is turned over top/bottom.\n"
                                     "The Bottom object is mirrored in that direction."))
        grid.addWidget(FCLabel('%s:' % _('Type')), 3, 0)
        grid.addWidget(self.type_combo, 3, 1)

        layout.addWidget(FCLabel(_("Alignment Drills"), color='brown', bold=True))
        align_frame = FCFrame()
        layout.addWidget(align_frame)
        params = GLay(v_spacing=5, h_spacing=3)
        align_frame.setLayout(params)
        self.generate_cb = FCCheckBox(_("Enable"))
        msg_2 = _("Enables the generation of alignment drill holes.")
        self.generate_cb.setToolTip(msg_2)
        params.addWidget(self.generate_cb, 0, 0, 1, 2)

        self.basic_drill_dia = FCDoubleSpinner()
        self.basic_drill_dia.set_precision(self.decimals)
        self.basic_drill_dia.set_range(10 ** -self.decimals, 10000)
        self.basic_drill_dia.set_value(self.app.options.get('tools_2sided_drilldia', 1.0))
        self.offset_entry = FCDoubleSpinner()
        self.offset_entry.set_precision(self.decimals)
        self.offset_entry.set_range(0, 10000)
        self.offset_entry.set_value(2.0)
        self.offset_entry.setToolTip(_("Distance from the source bounds to the hole center.\n"
                                      "It must be at least half the drill diameter."))

        wdg_tuple_list = (
            (_('Drill Dia'), _("Drill bit diameter for alignment holes."), self.basic_drill_dia),
            (_('Offset'), _("How far the alignment holes are from the objects."), self.offset_entry)
        )
        self.basic_drill_params = []
        for row, (label, tooltip, widget) in enumerate(wdg_tuple_list, start=1):
            label = FCLabel('%s:' % label)
            label.setToolTip(tooltip)
            params.addWidget(label, row, 0)
            params.addWidget(widget, row, 1)
            self.basic_drill_params += [label, widget]
        self.append_drills_cb = FCCheckBox(_("Add to selected Excellon"))
        self.append_drills_cb.setToolTip(
            _("If checked, the alignment holes will be added to the selected Excellon object.")
        )
        self.failsafe_cb = FCCheckBox(_("Failsafe"))
        self.failsafe_cb.set_value(True)
        self.failsafe_cb.setToolTip(_("Adds a 3rd keyed hole so that the board fits the pins only when it is turned "
                                      "in the Type direction.\nIf unchecked, the operator must turn the board in the "
                                      "Type direction."))
        params.addWidget(self.failsafe_cb, 3, 0, 1, 2)
        params.addWidget(self.append_drills_cb, 4, 0, 1, 2)
        self.basic_drill_params.append(self.failsafe_cb)
        self.auto_align_cb = FCCheckBox(_("AutoAlign"))
        self.auto_align_cb.set_value(True)
        auto_align_m1 = _("Align pads and drills using translation and rotation. Top stays fixed, else Bottom.")
        auto_align_m2 = _("Ambiguous or insufficient matches stop the operation; use Align Objects to inspect.")
        self.auto_align_cb.setToolTip(auto_align_m1 + "\n" + auto_align_m2)
        layout.addWidget(self.auto_align_cb)
        self.process_button = FCButton(_("Generate"), bold=True)
        process_m1 = _("Will register the bottom layer and drills to the top layer if auto align is selected.")
        process_m2 = _("Mirrors the Bottom object in place (left/right), so it can be milled after turning the board over.")
        process_m3 = _("Generates alignment holes, if selected. These can be included in the Excellon object, if any.")
        self.process_button.setToolTip(process_m1 + "\n" + process_m2 + "\n" + process_m3)
        layout.addWidget(self.process_button)
        self.generate_cb.toggled.connect(self.update_basic_state)
        self.drills_combo.currentIndexChanged.connect(self.update_basic_state)
        self.update_basic_state()

    def update_basic_state(self, *args):
        generate = self.generate_cb.isChecked()
        for widget in self.basic_drill_params:
            widget.setEnabled(generate)
        has_drills = self.drills_combo.currentData() is not None
        self.append_drills_cb.setEnabled(generate and has_drills)
        if not has_drills:
            self.append_drills_cb.set_value(False)

    def set_reference(self, val):
        if val == "point":
            self.pr_frame.show()
            self.br_frame.hide()
            self.sr_frame.hide()
            self.align_ref_label_val.set_value(self.point_entry.get_value())
        elif val == 'box':
            self.pr_frame.hide()
            self.br_frame.show()
            self.sr_frame.hide()
            self.align_ref_label_val.set_value("Box centroid")
        elif val == 'hole':
            self.pr_frame.hide()
            self.br_frame.hide()
            self.sr_frame.show()

    def set_level(self, checked):
        self.basic_frame.setVisible(not checked)
        self.advanced_frame.setVisible(checked)
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)
            self.bv_label.hide()
            self.bounds_frame.hide()
            self.center_entry.hide()
            self.center_btn.hide()
            self.calculate_bb_button.hide()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)
            self.bv_label.show()
            self.bounds_frame.show()
            self.center_entry.show()
            self.center_btn.show()
            self.calculate_bb_button.show()

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

    def on_align_type_changed(self, val):
        if val in ["X", "Y"]:
            self.align_ref_label.show()
            self.align_ref_label_val.show()
        else:
            self.align_ref_label.hide()
            self.align_ref_label_val.hide()
