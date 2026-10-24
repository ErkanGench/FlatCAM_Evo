"""Widgets and presentation for the QRCode plugin."""

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    RadioSet, FCTextArea, FCSpinner, FCDoubleSpinner, FCEntry

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class QRcodeUI:

    pluginName = _("QRCode")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        units = str(self.app.app_units).lower()
        self.title_box = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.title_box)
        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)
        self.title_box = QtWidgets.QHBoxLayout()
        self.tools_box.addLayout(self.title_box)
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.title_box.addWidget(title_label)
        self.level = QtWidgets.QToolButton()
        self.level.setToolTip(_(
            "Beginner Mode - many parameters are hidden.\n"
            "Advanced Mode - full control.\n"
            "Permanent change is done in 'Preferences' menu."))
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)
        i_grid_lay = GLay(v_spacing=5, h_spacing=3)
        self.tools_box.addLayout(i_grid_lay)
        self.grb_object_combo = FCComboBox()
        self.grb_object_combo.setModel(self.app.collection)
        self.grb_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.grb_object_combo.is_last = True
        self.grb_object_combo.obj_type = "Gerber"
        self.grbobj_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.grbobj_label.setToolTip(_("Gerber Object to which the QRCode will be added."))
        i_grid_lay.addWidget(self.grbobj_label, 0, 0)
        i_grid_lay.addWidget(self.grb_object_combo, 1, 0, 1, 2)

        # QRCode text
        self.text_label = FCLabel('%s' % _("QRCode Data"), color='red', bold=True)
        self.text_label.setToolTip(_("QRCode Data. Alphanumeric text to be encoded in the QRCode."))
        self.tools_box.addWidget(self.text_label)
        tq_frame = FCFrame()
        self.tools_box.addWidget(tq_frame)
        grid0 = GLay(v_spacing=5, h_spacing=3)
        tq_frame.setLayout(grid0)
        self.text_data = FCTextArea()
        self.text_data.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        self.text_data.setPlaceholderText(_("Add here the text to be included in the QRCode..."))
        grid0.addWidget(self.text_data, 0, 0, 1, 3)

        # Parameters
        self.qrcode_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.qrcode_label.setToolTip(_("The parameters used to shape the QRCode."))
        self.tools_box.addWidget(self.qrcode_label)
        p_frame = FCFrame()
        self.tools_box.addWidget(p_frame)
        grid1 = GLay(v_spacing=5, h_spacing=3)
        p_frame.setLayout(grid1)

        self.version_label = FCLabel('%s:' % _("Version"))
        self.version_label.setToolTip(
            _("QRCode version can have values from 1 (21x21 boxes)\n"
              "to 40 (177x177 boxes).\n"
              "The version is fixed unless Auto is checked: the data must fit in it."))
        self.version_entry = FCSpinner(callback=self.confirmation_message_int)
        self.version_entry.set_range(1, 40)
        self.version_entry.setWrapping(True)
        self.version_auto_cb = FCCheckBox(_("Auto"))
        self.version_auto_cb.setToolTip(_("Use the smallest version that fits the data."))
        grid1.addWidget(self.version_label, 0, 0)
        grid1.addWidget(self.version_entry, 0, 1)
        grid1.addWidget(self.version_auto_cb, 0, 2)

        self.info_label = FCLabel('')
        self.info_label.setToolTip(_("The version, the modules count and the total size of the QRCode."))
        self.info_label.setWordWrap(True)
        grid1.addWidget(self.info_label, 1, 0, 1, 3)

        error_tip = _("Parameter that controls the error correction used for the QR Code.\n"
                      "L = maximum 7%% errors can be corrected\n"
                      "M = maximum 15%% errors can be corrected\n"
                      "Q = maximum 25%% errors can be corrected\n"
                      "H = maximum 30%% errors can be corrected.")
        self.error_label = FCLabel('%s:' % _("Error correction"))
        self.error_label.setToolTip(error_tip)
        self.error_radio = RadioSet([{'label': 'L', 'value': 'L'},
                                     {'label': 'M', 'value': 'M'},
                                     {'label': 'Q', 'value': 'Q'},
                                     {'label': 'H', 'value': 'H'}])
        self.error_radio.setToolTip(error_tip)
        grid1.addWidget(self.error_label, 2, 0)
        grid1.addWidget(self.error_radio, 2, 1, 1, 2)

        self.mask_pattern_label = FCLabel('%s:' % _("Mask pattern"))
        self.mask_pattern_label.setToolTip(_("The QR mask pattern. Auto lets the encoder choose the best one."))
        self.mask_pattern_combo = FCComboBox()
        self.mask_pattern_combo.addItems([_('Auto')] + [str(i) for i in range(8)])
        grid1.addWidget(self.mask_pattern_label, 3, 0)
        grid1.addWidget(self.mask_pattern_combo, 3, 1, 1, 2)

        self.bsize_label = FCLabel('%s:' % _("Box Size"))
        self.bsize_label.setToolTip(
            _("Box size control the overall size of the QRcode\n"
              "by adjusting the size of each box in the code.\n"
              "One box size unit is 0.1 mm."))
        self.bsize_entry = FCSpinner(callback=self.confirmation_message_int)
        self.bsize_entry.set_range(1, 9999)
        self.bsize_entry.setWrapping(True)
        self.module_size_label = FCLabel('')
        self.module_size_label.setToolTip(_("The size of one box in the app units."))
        grid1.addWidget(self.bsize_label, 4, 0)
        grid1.addWidget(self.bsize_entry, 4, 1)
        grid1.addWidget(self.module_size_label, 4, 2)

        self.border_size_label = FCLabel('%s:' % _("Border Size"))
        self.border_size_label.setToolTip(
            _("Size of the QRCode border. How many boxes thick is the border.\n"
              "Default value is 4. The width of the clearance around the QRCode.\n"
              "A border below 4 boxes breaks the quiet zone of the QR standard."))
        self.border_size_entry = FCSpinner(callback=self.confirmation_message_int)
        self.border_size_entry.set_range(0, 9999)
        self.border_size_entry.setWrapping(True)
        grid1.addWidget(self.border_size_label, 5, 0)
        grid1.addWidget(self.border_size_entry, 5, 1)

        self.warning_label = FCLabel('')
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("QLabel {color: red;}")
        self.warning_label.hide()
        grid1.addWidget(self.warning_label, 6, 0, 1, 3)

        self.pol_label = FCLabel('%s:' % _("Polarity"))
        self.pol_label.setToolTip(
            _("Choose the polarity of the QRCode.\n"
              "It can be drawn in a negative way (squares are clear)\n"
              "or in a positive way (squares are opaque)."))
        self.pol_radio = RadioSet([{'label': _('Negative'), 'value': 'neg'},
                                   {'label': _('Positive'), 'value': 'pos'}])
        self.pol_radio.setToolTip(
            _("Choose the type of QRCode to be created.\n"
              "If added on a Silkscreen Gerber file the QRCode may\n"
              "be added as positive. If it is added to a Copper Gerber\n"
              "file then perhaps the QRCode can be added as negative."))
        grid1.addWidget(self.pol_label, 7, 0)
        grid1.addWidget(self.pol_radio, 7, 1, 1, 2)

        bb_tip = _("The bounding box, meaning the empty space that surrounds\n"
                   "the QRCode geometry, can have a rounded or a square shape.")
        self.bb_label = FCLabel('%s:' % _("Bounding Box"))
        self.bb_label.setToolTip(bb_tip)
        self.bb_radio = RadioSet([{'label': _('Rounded'), 'value': 'r'},
                                  {'label': _('Square'), 'value': 's'}])
        self.bb_radio.setToolTip(bb_tip)
        grid1.addWidget(self.bb_label, 8, 0)
        grid1.addWidget(self.bb_radio, 8, 1, 1, 2)

        self.rotation_label = FCLabel('%s:' % _("Rotation"))
        self.rotation_label.setToolTip(_("Rotate the QRCode counter-clockwise, in degrees."))
        self.rotation_radio = RadioSet([{'label': '0', 'value': 0}, {'label': '90', 'value': 90},
                                        {'label': '180', 'value': 180}, {'label': '270', 'value': 270}])
        grid1.addWidget(self.rotation_label, 9, 0)
        grid1.addWidget(self.rotation_radio, 9, 1, 1, 2)

        self.mirror_cb = FCCheckBox(_("Mirror"))
        self.mirror_cb.setToolTip(_("Mirror the QRCode about the vertical axis (for the bottom layer)."))
        grid1.addWidget(self.mirror_cb, 10, 0, 1, 3)

        self.margin_label = FCLabel('%s:' % _("Clearance"))
        self.margin_label.setToolTip(
            _("The clearance around the QRCode, in app units.\n"
              "Zero means: the Border Size in boxes."))
        self.margin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.margin_entry.set_range(0.0, 10000.0)
        self.margin_entry.set_precision(self.decimals)
        self.margin_entry.setSingleStep(0.1)
        self.margin_units_label = FCLabel(units)
        grid1.addWidget(self.margin_label, 11, 0)
        grid1.addWidget(self.margin_entry, 11, 1)
        grid1.addWidget(self.margin_units_label, 11, 2)

        # Placement
        self.placement_title = FCLabel('%s' % _("Placement"), color='brown', bold=True)
        self.placement_title.setToolTip(_("Where the QRCode goes: a click on the canvas or given coordinates."))
        self.tools_box.addWidget(self.placement_title)
        self.placement_frame = FCFrame()
        self.tools_box.addWidget(self.placement_frame)
        grid2 = GLay(v_spacing=5, h_spacing=3)
        self.placement_frame.setLayout(grid2)
        self.placement_label = FCLabel('%s:' % _("Mode"))
        self.placement_radio = RadioSet([{'label': _('Click'), 'value': 'click'},
                                         {'label': _('Coordinates'), 'value': 'coords'}])
        self.placement_radio.setToolTip(_("Click: click the destination on the canvas.\n"
                                          "Coordinates: insert at the X, Y given below."))
        grid2.addWidget(self.placement_label, 0, 0)
        grid2.addWidget(self.placement_radio, 0, 1, 1, 2)
        self.x_label = FCLabel('%s:' % _("X"))
        self.x_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.x_entry.set_range(-10000.0, 10000.0)
        self.x_entry.set_precision(self.decimals)
        self.x_entry.setSingleStep(0.1)
        self.x_units_label = FCLabel(units)
        grid2.addWidget(self.x_label, 1, 0)
        grid2.addWidget(self.x_entry, 1, 1)
        grid2.addWidget(self.x_units_label, 1, 2)
        self.y_label = FCLabel('%s:' % _("Y"))
        self.y_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.y_entry.set_range(-10000.0, 10000.0)
        self.y_entry.set_precision(self.decimals)
        self.y_entry.setSingleStep(0.1)
        self.y_units_label = FCLabel(units)
        grid2.addWidget(self.y_label, 2, 0)
        grid2.addWidget(self.y_entry, 2, 1)
        grid2.addWidget(self.y_units_label, 2, 2)
        self.anchor_label = FCLabel('%s:' % _("Anchor"))
        self.anchor_label.setToolTip(_("The point of the QRCode (clearance included)\n"
                                       "that goes to the placement point."))
        self.anchor_radio = RadioSet([{'label': 'BL', 'value': 'bl'}, {'label': 'TL', 'value': 'tl'},
                                      {'label': 'BR', 'value': 'br'}, {'label': 'TR', 'value': 'tr'},
                                      {'label': 'C', 'value': 'c'}])
        grid2.addWidget(self.anchor_label, 3, 0)
        grid2.addWidget(self.anchor_radio, 3, 1, 1, 2)
        self.multi_cb = FCCheckBox(_("Keep placing"))
        self.multi_cb.setToolTip(_("Stay armed after each click and increment the serial number.\n"
                                   "Right click or Escape ends the placement."))
        grid2.addWidget(self.multi_cb, 4, 0, 1, 3)

        # Variables
        self.vars_title = FCLabel('%s' % _("Variables"), color='purple', bold=True)
        self.vars_title.setToolTip(_("Variables replaced in the QRCode Data at the insert time."))
        self.tools_box.addWidget(self.vars_title)
        self.vars_frame = FCFrame()
        self.tools_box.addWidget(self.vars_frame)
        grid3 = GLay(v_spacing=5, h_spacing=3)
        self.vars_frame.setLayout(grid3)
        self.tokens_label = FCLabel('{date} {time} {project} {object} {serial}')
        self.tokens_label.setToolTip(_("{date}: yyyy-mm-dd\n{time}: HH:MM\n{project}: the project name\n"
                                       "{object}: the name of the target Gerber\n{serial}: the serial number"))
        self.tokens_label.setWordWrap(True)
        grid3.addWidget(self.tokens_label, 0, 0, 1, 2)
        self.serial_start_label = FCLabel('%s:' % _("Serial start"))
        self.serial_start_entry = FCSpinner(callback=self.confirmation_message_int)
        self.serial_start_entry.set_range(0, 999999999)
        grid3.addWidget(self.serial_start_label, 1, 0)
        grid3.addWidget(self.serial_start_entry, 1, 1)
        self.serial_step_label = FCLabel('%s:' % _("Serial step"))
        self.serial_step_entry = FCSpinner(callback=self.confirmation_message_int)
        self.serial_step_entry.set_range(1, 999999)
        grid3.addWidget(self.serial_step_label, 2, 0)
        grid3.addWidget(self.serial_step_entry, 2, 1)
        self.serial_pad_label = FCLabel('%s:' % _("Serial width"))
        self.serial_pad_label.setToolTip(_("The serial number is padded with zeros to this width."))
        self.serial_pad_entry = FCSpinner(callback=self.confirmation_message_int)
        self.serial_pad_entry.set_range(0, 20)
        grid3.addWidget(self.serial_pad_label, 3, 0)
        grid3.addWidget(self.serial_pad_entry, 3, 1)

        # Output
        self.output_title = FCLabel('%s' % _("Output"), color='teal', bold=True)
        self.output_title.setToolTip(_("Where the QRCode is written."))
        self.tools_box.addWidget(self.output_title)
        self.output_frame = FCFrame()
        self.tools_box.addWidget(self.output_frame)
        grid4 = GLay(v_spacing=5, h_spacing=3)
        self.output_frame.setLayout(grid4)
        self.output_label = FCLabel('%s:' % _("Mode"))
        self.output_radio = RadioSet([{'label': _('Add to source'), 'value': 'source'},
                                      {'label': _('New object'), 'value': 'new'}])
        self.output_radio.setToolTip(_("Add the QRCode to the source Gerber or create a new Gerber object."))
        grid4.addWidget(self.output_label, 0, 0)
        grid4.addWidget(self.output_radio, 0, 1)
        self.mask_cb = FCCheckBox(_("Soldermask opening"))
        self.mask_cb.setToolTip(_("Also cut the clearance opening of the QRCode in the Gerber below\n"
                                  "(a soldermask companion)."))
        grid4.addWidget(self.mask_cb, 1, 0, 1, 2)
        self.mask_object_label = FCLabel('%s:' % _("Mask Gerber"))
        self.mask_object_combo = FCComboBox()
        self.mask_object_combo.setModel(self.app.collection)
        self.mask_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.mask_object_combo.obj_type = "Gerber"
        grid4.addWidget(self.mask_object_label, 2, 0)
        grid4.addWidget(self.mask_object_combo, 2, 1)

        # Rendered preview
        self.preview_title = FCLabel('%s' % _("Preview"), color='green', bold=True)
        self.tools_box.addWidget(self.preview_title)
        self.preview_frame = FCFrame()
        self.tools_box.addWidget(self.preview_frame)
        grid5 = GLay(v_spacing=5, h_spacing=3)
        self.preview_frame.setLayout(grid5)
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setWordWrap(True)
        self.preview_label.setMinimumHeight(100)
        grid5.addWidget(self.preview_label, 0, 0)

        # Export
        self.export_label = FCLabel('%s' % _("Export QRCode"), color='darkgreen', bold=True)
        self.export_label.setToolTip(
            _("Show a set of controls allowing to export the QRCode\n"
              "to a SVG file or an PNG file."))
        self.tools_box.addWidget(self.export_label)
        self.export_frame = FCFrame()
        self.tools_box.addWidget(self.export_frame)
        self.export_lay = GLay(v_spacing=5, h_spacing=3)
        self.export_frame.setLayout(self.export_lay)
        self.fill_color_label = FCLabel('%s:' % _('Fill Color'))
        self.fill_color_label.setToolTip(_("Set the QRCode fill color (squares color)."))
        self.fill_color_entry = FCEntry()
        self.fill_color_button = FCButton()
        self.fill_color_button.setFixedSize(15, 15)
        fill_lay_child = QtWidgets.QHBoxLayout()
        fill_lay_child.setContentsMargins(0, 0, 0, 0)
        fill_lay_child.addWidget(self.fill_color_entry)
        fill_lay_child.addWidget(self.fill_color_button, alignment=Qt.AlignmentFlag.AlignRight)
        fill_lay_child.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        fill_color_widget = QtWidgets.QWidget()
        fill_color_widget.setLayout(fill_lay_child)
        self.export_lay.addWidget(self.fill_color_label, 0, 0)
        self.export_lay.addWidget(fill_color_widget, 0, 1)
        self.transparent_cb = FCCheckBox(_("Transparent back color"))
        self.export_lay.addWidget(self.transparent_cb, 1, 0, 1, 2)
        self.back_color_label = FCLabel('%s:' % _('Back Color'))
        self.back_color_label.setToolTip(_("Set the QRCode background color."))
        self.back_color_entry = FCEntry()
        self.back_color_button = FCButton()
        self.back_color_button.setFixedSize(15, 15)
        back_lay_child = QtWidgets.QHBoxLayout()
        back_lay_child.setContentsMargins(0, 0, 0, 0)
        back_lay_child.addWidget(self.back_color_entry)
        back_lay_child.addWidget(self.back_color_button, alignment=Qt.AlignmentFlag.AlignRight)
        back_lay_child.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        back_color_widget = QtWidgets.QWidget()
        back_color_widget.setLayout(back_lay_child)
        self.export_lay.addWidget(self.back_color_label, 2, 0)
        self.export_lay.addWidget(back_color_widget, 2, 1)
        self.export_svg_button = FCButton(_("Export QRCode SVG"))
        self.export_svg_button.setToolTip(_("Export a SVG file with the QRCode content."))
        self.export_svg_button.bold = True
        self.tools_box.addWidget(self.export_svg_button)
        self.export_png_button = FCButton(_("Export QRCode PNG"))
        self.export_png_button.setToolTip(_("Export a PNG image file with the QRCode content."))
        self.export_png_button.bold = True
        self.tools_box.addWidget(self.export_png_button)
        self.qrcode_button = FCButton(_("Insert QRCode"))
        self.qrcode_button.setIcon(QtGui.QIcon(self.app.resource_location + '/qrcode32.png'))
        self.qrcode_button.setToolTip(_("Create the QRCode object."))
        self.qrcode_button.bold = True
        self.tools_box.addWidget(self.qrcode_button)
        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)

    def advanced_widgets(self):
        return [self.export_label, self.export_frame, self.export_svg_button, self.export_png_button,
                self.placement_title, self.placement_frame, self.vars_title, self.vars_frame,
                self.output_title, self.output_frame, self.preview_title, self.preview_frame,
                self.mask_pattern_label, self.mask_pattern_combo, self.rotation_label, self.rotation_radio,
                self.mirror_cb, self.margin_label, self.margin_entry, self.margin_units_label]

    def on_level_changed(self, checked):
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("QToolButton {color: green;}")
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("QToolButton {color: red;}")
        for widget in self.advanced_widgets():
            widget.setVisible(bool(checked))
        # the Insert button is available in both modes
        self.qrcode_button.show()

    def on_qrcode_fill_color_entry(self):
        color = self.fill_color_entry.get_value()
        self.fill_color_button.setStyleSheet("background-color:%s;" % str(color))

    def on_qrcode_fill_color_button(self):
        current_color = QtGui.QColor(self.fill_color_entry.get_value())
        c_dialog = QtWidgets.QColorDialog()
        fill_color = c_dialog.getColor(initial=current_color)
        if fill_color.isValid() is False:
            return
        self.fill_color_button.setStyleSheet("background-color:%s;" % str(fill_color.name()))
        self.fill_color_entry.set_value(str(fill_color.name()))

    def on_qrcode_back_color_entry(self):
        color = self.back_color_entry.get_value()
        self.back_color_button.setStyleSheet("background-color:%s;" % str(color))

    def on_qrcode_back_color_button(self):
        current_color = QtGui.QColor(self.back_color_entry.get_value())
        c_dialog = QtWidgets.QColorDialog()
        back_color = c_dialog.getColor(initial=current_color)
        if back_color.isValid() is False:
            return
        self.back_color_button.setStyleSheet("background-color:%s;" % str(back_color.name()))
        self.back_color_entry.set_value(str(back_color.name()))

    def on_transparent_back_color(self, state, old_back_color):
        if state:
            self.back_color_entry.setDisabled(True)
            self.back_color_button.setDisabled(True)
            self.back_color_entry.set_value('transparent')
        else:
            self.back_color_entry.setDisabled(False)
            self.back_color_button.setDisabled(False)
            self.back_color_entry.set_value(old_back_color)

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' % (_("Edited value is out of range"),
                                                                                  self.decimals, minval,
                                                                                  self.decimals, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
