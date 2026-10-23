from PyQt6 import QtWidgets, QtGui, QtCore
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, RadioSet, \
    FCDoubleSpinner, FCComboBox2, FCEntry, FCCheckBox

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ThievingUI:

    pluginName = _("Copper Thieving")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.units = self.app.app_units
        self.layout = layout

        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)
        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)
        self.grbobj_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.grbobj_label.setToolTip(_("Gerber Object to which will be added a copper thieving."))
        self.tools_box.addWidget(self.grbobj_label)
        i_grid_lay = GLay(v_spacing=5, h_spacing=3)
        self.tools_box.addLayout(i_grid_lay)
        self.grb_object_combo = FCComboBox()
        self.grb_object_combo.setModel(self.app.collection)
        self.grb_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.grb_object_combo.is_last = False
        self.grb_object_combo.obj_type = 'Gerber'
        i_grid_lay.addWidget(self.grb_object_combo, 0, 0, 1, 2)
        self.copper_fill_label = FCLabel('%s %s' % (_("Thieving"), _("Parameters")), color='blue', bold=True)
        self.copper_fill_label.setToolTip(_("Parameters used for this tool."))
        self.tools_box.addWidget(self.copper_fill_label)
        tp_frame = FCFrame()
        self.tools_box.addWidget(tp_frame)
        grid_lay = GLay(v_spacing=5, h_spacing=3)
        tp_frame.setLayout(grid_lay)
        self.clearance_label = FCLabel('%s:' % _("Clearance"))
        self.clearance_label.setToolTip(
            _("This set the distance between the copper thieving components\n"
              "(the polygon fill may be split in multiple polygons)\n"
              "and the copper traces in the Gerber file."))
        self.clearance_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_entry.set_range(0.00001, 10000.0000)
        self.clearance_entry.set_precision(self.decimals)
        self.clearance_entry.setSingleStep(0.1)
        grid_lay.addWidget(self.clearance_label, 2, 0)
        grid_lay.addWidget(self.clearance_entry, 2, 1)
        self.margin_label = FCLabel('%s:' % _("Margin"))
        self.margin_label.setToolTip(_("Bounding box margin."))
        self.margin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.margin_entry.set_range(0.0, 10000.0000)
        self.margin_entry.set_precision(self.decimals)
        self.margin_entry.setSingleStep(0.1)
        grid_lay.addWidget(self.margin_label, 4, 0)
        grid_lay.addWidget(self.margin_entry, 4, 1)
        area_hlay = QtWidgets.QHBoxLayout()
        self.area_label = FCLabel('%s:' % _("Area"))
        self.area_label.setToolTip(_("Thieving areas with area less then this value will not be added."))
        self.area_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.area_entry.set_range(0.0, 10000.0000)
        self.area_entry.set_precision(self.decimals)
        self.area_entry.setSingleStep(0.1)
        self.area_entry.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                                      QtWidgets.QSizePolicy.Policy.Preferred)
        if self.units.upper() == 'MM':
            units_area_label = FCLabel('%s<sup>2</sup>' % _("mm"))
        else:
            units_area_label = FCLabel('%s<sup>2</sup>' % _("in"))
        area_hlay.addWidget(self.area_entry)
        area_hlay.addWidget(units_area_label)
        grid_lay.addWidget(self.area_label, 6, 0)
        grid_lay.addLayout(area_hlay, 6, 1)
        self.reference_label = FCLabel(_("Reference:"))
        self.reference_label.setToolTip(
            _("- 'Itself' - the copper thieving extent is based on the object extent.\n"
              "- 'Area Selection' - left mouse click to start selection of the area to be filled.\n"
              "- 'Reference Object' - will do copper thieving within the area specified by another object."))
        self.reference_combo = FCComboBox2()
        self.reference_combo.addItems([_('Itself'), _("Area Selection"), _("Reference Object")])
        grid_lay.addWidget(self.reference_label, 8, 0)
        grid_lay.addWidget(self.reference_combo, 8, 1)
        self.ref_combo_type_label = FCLabel('%s:' % _("Type"))
        self.ref_combo_type_label.setToolTip(
            _("The type of FlatCAM object to be used as copper thieving reference.\n"
              "It can be Gerber, Excellon or Geometry."))
        self.ref_combo_type = FCComboBox()
        self.ref_combo_type.addItems([_("Gerber"), _("Excellon"), _("Geometry")])
        grid_lay.addWidget(self.ref_combo_type_label, 10, 0)
        grid_lay.addWidget(self.ref_combo_type, 10, 1)
        self.ref_combo = FCComboBox()
        self.ref_combo.setModel(self.app.collection)
        self.ref_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ref_combo.is_last = True
        self.ref_combo.obj_type = {
            _("Gerber"): "Gerber", _("Excellon"): "Excellon", _("Geometry"): "Geometry"
        }[self.ref_combo_type.get_value()]
        grid_lay.addWidget(self.ref_combo, 12, 0, 1, 2)
        self.ref_combo.hide()
        self.ref_combo_type.hide()
        self.ref_combo_type_label.hide()
        self.bbox_type_label = FCLabel('%s:' % _("Box Type"))
        self.bbox_type_label.setToolTip(
            _("- 'Rectangular' - the bounding box will be of rectangular shape.\n"
              "- 'Minimal' - the bounding box will be the convex hull shape."))
        self.bbox_type_radio = RadioSet([
            {'label': _('Rectangular'), 'value': 'rect'},
            {"label": _("Minimal"), "value": "min"}
        ], compact=True)
        grid_lay.addWidget(self.bbox_type_label, 14, 0)
        grid_lay.addWidget(self.bbox_type_radio, 14, 1)
        self.bbox_type_label.hide()
        self.bbox_type_radio.hide()
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        grid_lay.addWidget(separator_line, 16, 0, 1, 2)
        self.fill_type_label = FCLabel('%s:' % _("Fill"))
        self.fill_type_label.setToolTip(
            _("- 'Solid' - copper thieving will be a solid polygon.\n"
              "- 'Dots Grid' - the empty area will be filled with a pattern of dots.\n"
              "- 'Squares Grid' - the empty area will be filled with a pattern of squares.\n"
              "- 'Lines Grid' - the empty area will be filled with a pattern of lines."))
        self.fill_type_combo = FCComboBox2()
        self.fill_type_combo.addItems([_('Solid'), _("Dots Grid"), _("Squares Grid"), _("Lines Grid")])
        grid_lay.addWidget(self.fill_type_label, 18, 0)
        grid_lay.addWidget(self.fill_type_combo, 18, 1)
        self.dots_frame = QtWidgets.QFrame()
        self.dots_frame.setContentsMargins(0, 0, 0, 0)
        grid_lay.addWidget(self.dots_frame, 20, 0, 1, 2)
        dots_grid = GLay(v_spacing=5, h_spacing=3)
        dots_grid.setContentsMargins(0, 0, 0, 0)
        self.dots_frame.setLayout(dots_grid)
        self.dots_frame.hide()
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        dots_grid.addWidget(separator_line, 0, 0, 1, 2)
        self.dots_label = FCLabel('%s' % _("Dots Grid Parameters"), bold=True)
        dots_grid.addWidget(self.dots_label, 2, 0, 1, 2)
        self.dotdia_label = FCLabel('%s:' % _("Dia"))
        self.dotdia_label.setToolTip(_("Dot diameter in Dots Grid."))
        self.dot_dia_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.dot_dia_entry.set_range(0.0, 10000.0000)
        self.dot_dia_entry.set_precision(self.decimals)
        self.dot_dia_entry.setSingleStep(0.1)
        dots_grid.addWidget(self.dotdia_label, 4, 0)
        dots_grid.addWidget(self.dot_dia_entry, 4, 1)
        self.dotspacing_label = FCLabel('%s:' % _("Spacing"))
        self.dotspacing_label.setToolTip(_("Distance between each two dots in Dots Grid."))
        self.dot_spacing_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.dot_spacing_entry.set_range(0.0, 10000.0000)
        self.dot_spacing_entry.set_precision(self.decimals)
        self.dot_spacing_entry.setSingleStep(0.1)
        dots_grid.addWidget(self.dotspacing_label, 6, 0)
        dots_grid.addWidget(self.dot_spacing_entry, 6, 1)
        self.squares_frame = QtWidgets.QFrame()
        self.squares_frame.setContentsMargins(0, 0, 0, 0)
        grid_lay.addWidget(self.squares_frame, 22, 0, 1, 2)
        squares_grid = GLay(v_spacing=5, h_spacing=3)
        squares_grid.setContentsMargins(0, 0, 0, 0)
        self.squares_frame.setLayout(squares_grid)
        self.squares_frame.hide()
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        squares_grid.addWidget(separator_line, 0, 0, 1, 2)
        self.squares_label = FCLabel('%s' % _("Squares Grid Parameters"), bold=True)
        squares_grid.addWidget(self.squares_label, 2, 0, 1, 2)
        self.square_size_label = FCLabel('%s:' % _("Size"))
        self.square_size_label.setToolTip(_("Square side size in Squares Grid."))
        self.square_size_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.square_size_entry.set_range(0.0, 10000.0000)
        self.square_size_entry.set_precision(self.decimals)
        self.square_size_entry.setSingleStep(0.1)
        squares_grid.addWidget(self.square_size_label, 4, 0)
        squares_grid.addWidget(self.square_size_entry, 4, 1)
        self.squares_spacing_label = FCLabel('%s:' % _("Spacing"))
        self.squares_spacing_label.setToolTip(_("Distance between each two squares in Squares Grid."))
        self.squares_spacing_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.squares_spacing_entry.set_range(0.0, 10000.0000)
        self.squares_spacing_entry.set_precision(self.decimals)
        self.squares_spacing_entry.setSingleStep(0.1)
        squares_grid.addWidget(self.squares_spacing_label, 6, 0)
        squares_grid.addWidget(self.squares_spacing_entry, 6, 1)
        self.lines_frame = QtWidgets.QFrame()
        self.lines_frame.setContentsMargins(0, 0, 0, 0)
        grid_lay.addWidget(self.lines_frame, 24, 0, 1, 2)
        lines_grid = GLay(v_spacing=5, h_spacing=3)
        lines_grid.setContentsMargins(0, 0, 0, 0)
        self.lines_frame.setLayout(lines_grid)
        self.lines_frame.hide()
        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        lines_grid.addWidget(separator_line, 0, 0, 1, 2)
        self.lines_label = FCLabel('%s' % _("Lines Grid Parameters"), bold=True)
        lines_grid.addWidget(self.lines_label, 2, 0, 1, 2)
        self.line_size_label = FCLabel('%s:' % _("Size"))
        self.line_size_label.setToolTip(_("Line thickness size in Lines Grid."))
        self.line_size_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.line_size_entry.set_range(0.0, 10000.0000)
        self.line_size_entry.set_precision(self.decimals)
        self.line_size_entry.setSingleStep(0.1)
        lines_grid.addWidget(self.line_size_label, 4, 0)
        lines_grid.addWidget(self.line_size_entry, 4, 1)
        self.lines_spacing_label = FCLabel('%s:' % _("Spacing"))
        self.lines_spacing_label.setToolTip(_("Distance between each two lines in Lines Grid."))
        self.lines_spacing_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.lines_spacing_entry.set_range(0.0, 10000.0000)
        self.lines_spacing_entry.set_precision(self.decimals)
        self.lines_spacing_entry.setSingleStep(0.1)
        lines_grid.addWidget(self.lines_spacing_label, 6, 0)
        lines_grid.addWidget(self.lines_spacing_entry, 6, 1)
        self.fill_button = FCButton(_("Insert Copper thieving"), bold=True)
        self.fill_button.setIcon(QtGui.QIcon(self.app.resource_location + '/copperfill32.png'))
        self.fill_button.setToolTip(
            _("Will add a polygon (may be split in multiple parts)\n"
              "that will surround the actual Gerber traces at a certain distance."))
        self.tools_box.addWidget(self.fill_button)
        self.robber_bar_label = FCLabel('%s' % _("Robber Bar Parameters"), color='brown', bold=True)
        self.robber_bar_label.setToolTip(
            _("Parameters used for the robber bar.\n"
              "Robber bar = copper border to help in pattern hole plating."))
        self.tools_box.addWidget(self.robber_bar_label)
        rob_frame = FCFrame()
        self.tools_box.addWidget(rob_frame)
        grid_lay_1 = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1, 0])
        rob_frame.setLayout(grid_lay_1)
        self.rb_margin_label = FCLabel('%s:' % _("Margin"))
        self.rb_margin_label.setToolTip(_("Bounding box margin for robber bar."))
        self.rb_margin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.rb_margin_entry.set_range(-10000.0000, 10000.0000)
        self.rb_margin_entry.set_precision(self.decimals)
        self.rb_margin_entry.setSingleStep(0.1)
        grid_lay_1.addWidget(self.rb_margin_label, 4, 0)
        grid_lay_1.addWidget(self.rb_margin_entry, 4, 1, 1, 2)
        self.rb_thickness_label = FCLabel('%s:' % _("Thickness"))
        self.rb_thickness_label.setToolTip(_("The robber bar thickness."))
        self.rb_thickness_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.rb_thickness_entry.set_range(0.0000, 10000.0000)
        self.rb_thickness_entry.set_precision(self.decimals)
        self.rb_thickness_entry.setSingleStep(0.1)
        grid_lay_1.addWidget(self.rb_thickness_label, 6, 0)
        grid_lay_1.addWidget(self.rb_thickness_entry, 6, 1, 1, 2)
        self.rb_button = FCButton(_("Insert Robber Bar"), bold=True)
        self.rb_button.setIcon(QtGui.QIcon(self.app.resource_location + '/robber32.png'))
        self.rb_button.setToolTip(
            _("Will add a polygon with a defined thickness\n"
              "that will surround the actual Gerber object\n"
              "at a certain distance.\n"
              "Required when doing holes pattern plating."))
        self.tools_box.addWidget(self.rb_button)
        self.patern_mask_label = FCLabel('%s' % _("Pattern Plating Mask"), color='purple', bold=True)
        self.patern_mask_label.setToolTip(_("Generate a mask for pattern plating."))
        self.tools_box.addWidget(self.patern_mask_label)
        self.sm_obj_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.sm_obj_label.setToolTip(
            _("Gerber Object with the soldermask.\n"
              "It will be used as a base for\n"
              "the pattern plating mask."))
        self.sm_object_combo = FCComboBox()
        self.sm_object_combo.setModel(self.app.collection)
        self.sm_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.sm_object_combo.is_last = True
        self.sm_object_combo.obj_type = 'Gerber'
        self.tools_box.addWidget(self.sm_obj_label)
        self.tools_box.addWidget(self.sm_object_combo)
        pp_frame = FCFrame()
        self.tools_box.addWidget(pp_frame)
        grid_lay_2 = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1, 0])
        pp_frame.setLayout(grid_lay_2)
        self.only_pads_cb = FCCheckBox(_("Only Pads"))
        self.only_pads_cb.setToolTip(_("Select only pads in case the selected object is a copper Gerber."))
        grid_lay_2.addWidget(self.only_pads_cb, 0, 0, 1, 3)
        self.clearance_ppm_label = FCLabel('%s:' % _("Clearance"))
        self.clearance_ppm_label.setToolTip(
            _("The distance between the possible copper thieving elements\n"
              "and/or robber bar and the actual openings in the mask."))
        self.clearance_ppm_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.clearance_ppm_entry.set_range(-10000.0000, 10000.0000)
        self.clearance_ppm_entry.set_precision(self.decimals)
        self.clearance_ppm_entry.setSingleStep(0.1)
        grid_lay_2.addWidget(self.clearance_ppm_label, 2, 0)
        grid_lay_2.addWidget(self.clearance_ppm_entry, 2, 1, 1, 2)
        self.plated_area_label = FCLabel('%s:' % _("Plated area"))
        self.plated_area_label.setToolTip(
            _("The area to be plated by pattern plating.\n"
              "Basically is made from the openings in the plating mask.\n\n"
              "<<WARNING>> - the calculated area is actually a bit larger\n"
              "due of the fact that the soldermask openings are by design\n"
              "a bit larger than the copper pads, and this area is\n"
              "calculated from the soldermask openings."))
        self.plated_area_entry = FCEntry()
        self.plated_area_entry.setReadOnly(True)
        if self.units.upper() == 'MM':
            self.units_area_label = FCLabel('%s<sup>2</sup>' % _("cm"))
        else:
            self.units_area_label = FCLabel('%s<sup>2</sup>' % _("in"))
        grid_lay_2.addWidget(self.plated_area_label, 4, 0)
        grid_lay_2.addWidget(self.plated_area_entry, 4, 1)
        grid_lay_2.addWidget(self.units_area_label, 4, 2)
        self.ppm_choice_label = FCLabel('%s:' % _("Add"))
        self.ppm_choice_label.setToolTip(_("Choose which additional geometry to include, if available."))
        self.ppm_choice_combo = FCComboBox2()
        self.ppm_choice_combo.addItems([_("Both"), _('Thieving'), _("Robber bar"), _("None")])
        grid_lay_2.addWidget(self.ppm_choice_label, 6, 0)
        grid_lay_2.addWidget(self.ppm_choice_combo, 6, 1, 1, 2)
        GLay.set_common_column_size(
            [i_grid_lay, grid_lay, grid_lay_1, grid_lay_2, dots_grid, squares_grid, lines_grid], 0)
        self.ppm_button = FCButton(_("Generate pattern plating mask"), bold=True)
        self.ppm_button.setIcon(QtGui.QIcon(self.app.resource_location + '/pattern32.png'))
        self.ppm_button.setToolTip(
            _("Will add to the soldermask gerber geometry\n"
              "the geometries of the copper thieving and/or\n"
              "the robber bar if those were generated."))
        self.tools_box.addWidget(self.ppm_button)
        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)

    def set_reference_visibility(self, reference):
        if reference in (0, 1):
            self.ref_combo.hide()
            self.ref_combo_type.hide()
            self.ref_combo_type_label.hide()
        else:
            self.ref_combo.show()
            self.ref_combo_type.show()
            self.ref_combo_type_label.show()

    def set_box_visibility(self, visible):
        self.bbox_type_label.setVisible(visible)
        self.bbox_type_radio.setVisible(visible)

    def set_fill_visibility(self, fill_type):
        self.dots_frame.setVisible(fill_type == 1)
        self.squares_frame.setVisible(fill_type == 2)
        self.lines_frame.setVisible(fill_type not in (0, 1, 2))

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
