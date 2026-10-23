"""Widgets and presentation for the QRCode plugin."""

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    RadioSet, FCTextArea, FCSpinner, FCEntry

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
        grid0.addWidget(self.text_data, 0, 0, 1, 2)

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
              "to 40 (177x177 boxes)."))
        self.version_entry = FCSpinner(callback=self.confirmation_message_int)
        self.version_entry.set_range(1, 40)
        self.version_entry.setWrapping(True)
        grid1.addWidget(self.version_label, 2, 0)
        grid1.addWidget(self.version_entry, 2, 1)
        self.error_label = FCLabel('%s:' % _("Error correction"))
        self.error_label.setToolTip(
            _("Parameter that controls the error correction used for the QR Code.\n"
              "L = maximum 7%% errors can be corrected\n"
              "M = maximum 15%% errors can be corrected\n"
              "Q = maximum 25%% errors can be corrected\n"
              "H = maximum 30%% errors can be corrected."))
        self.error_radio = RadioSet([{'label': 'L', 'value': 'L'},
                                     {'label': 'M', 'value': 'M'},
                                     {'label': 'Q', 'value': 'Q'},
                                     {'label': 'H', 'value': 'H'}])
        self.error_radio.setToolTip(
            _("Parameter that controls the error correction used for the QR Code.\n"
              "L = maximum 7%% errors can be corrected\n"
              "M = maximum 15%% errors can be corrected\n"
              "Q = maximum 25%% errors can be corrected\n"
              "H = maximum 30%% errors can be corrected."))
        grid1.addWidget(self.error_label, 4, 0)
        grid1.addWidget(self.error_radio, 4, 1)
        self.bsize_label = FCLabel('%s:' % _("Box Size"))
        self.bsize_label.setToolTip(
            _("Box size control the overall size of the QRcode\n"
              "by adjusting the size of each box in the code."))
        self.bsize_entry = FCSpinner(callback=self.confirmation_message_int)
        self.bsize_entry.set_range(1, 9999)
        self.bsize_entry.setWrapping(True)
        grid1.addWidget(self.bsize_label, 6, 0)
        grid1.addWidget(self.bsize_entry, 6, 1)
        self.border_size_label = FCLabel('%s:' % _("Border Size"))
        self.border_size_label.setToolTip(
            _("Size of the QRCode border. How many boxes thick is the border.\n"
              "Default value is 4. The width of the clearance around the QRCode."))
        self.border_size_entry = FCSpinner(callback=self.confirmation_message_int)
        self.border_size_entry.set_range(1, 9999)
        self.border_size_entry.setWrapping(True)
        grid1.addWidget(self.border_size_label, 8, 0)
        grid1.addWidget(self.border_size_entry, 8, 1)
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
        grid1.addWidget(self.pol_label, 10, 0)
        grid1.addWidget(self.pol_radio, 10, 1)
        self.bb_label = FCLabel('%s:' % _("Bounding Box"))
        self.bb_label.setToolTip(
            _("The bounding box, meaning the empty space that surrounds\n"
              "the QRCode geometry, can have a rounded or a square shape."))
        self.bb_radio = RadioSet([{'label': _('Rounded'), 'value': 'r'},
                                  {'label': _('Square'), 'value': 's'}])
        self.bb_radio.setToolTip(
            _("The bounding box, meaning the empty space that surrounds\n"
              "the QRCode geometry, can have a rounded or a square shape."))
        grid1.addWidget(self.bb_label, 12, 0)
        grid1.addWidget(self.bb_radio, 12, 1)

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
        self.export_frame.hide()
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

    def on_level_changed(self, checked):
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("QToolButton {color: green;}")
            self.export_label.hide()
            self.export_frame.hide()
            self.export_svg_button.hide()
            self.export_png_button.hide()
            self.qrcode_button.show()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("QToolButton {color: red;}")
            self.export_label.show()
            self.export_frame.show()
            self.export_svg_button.show()
            self.export_png_button.show()
            self.qrcode_button.hide()

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
