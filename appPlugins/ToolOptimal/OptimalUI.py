"""Widgets for Find Optimal."""

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCEntry, FCTextArea, FCSpinner, OptionalHideInputSection

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class OptimalUI:

    pluginName = _("Find Optimal")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        self.units = self.app.app_units.upper()
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            "Gerber object for which to find the minimum distance between copper features.")
        self.layout.addWidget(self.obj_combo_label)
        self.gerber_object_combo = FCComboBox()
        self.gerber_object_combo.setModel(self.app.collection)
        self.gerber_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.gerber_object_combo.is_last = True
        self.gerber_object_combo.obj_type = "Gerber"
        self.gerber_object_label = FCLabel('%s:' % _("GERBER"), bold=True)
        self.gerber_object_label.setToolTip(
            "Gerber object for which to find the minimum distance between copper features.")
        self.layout.addWidget(self.gerber_object_combo)

        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters used for this tool."))
        self.layout.addWidget(self.param_label)
        par_frame = FCFrame()
        self.layout.addWidget(par_frame)
        param_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(param_grid)
        self.precision_label = FCLabel('%s:' % _("Precision"))
        self.precision_label.setToolTip(_("Number of decimals kept for found distances."))
        self.precision_spinner = FCSpinner(callback=self.confirmation_message_int)
        self.precision_spinner.set_range(2, 10)
        self.precision_spinner.setWrapping(True)
        param_grid.addWidget(self.precision_label, 0, 0)
        param_grid.addWidget(self.precision_spinner, 0, 1)

        res_label = FCLabel('%s' % _("Minimum distance"), color='green', bold=True)
        res_label.setToolTip(_("Display minimum distance between copper features."))
        self.layout.addWidget(res_label)
        res_frame = FCFrame()
        self.layout.addWidget(res_frame)
        res_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1, 0])
        res_frame.setLayout(res_grid)
        self.result_label = FCLabel('%s:' % _("Determined"))
        self.result_entry = FCEntry()
        self.result_entry.setReadOnly(True)
        self.units_lbl = FCLabel(self.units.lower())
        self.units_lbl.setDisabled(True)
        res_grid.addWidget(self.result_label, 0, 0)
        res_grid.addWidget(self.result_entry, 0, 1)
        res_grid.addWidget(self.units_lbl, 0, 2)
        self.freq_label = FCLabel('%s:' % _("Occurring"))
        self.freq_label.setToolTip(_("How many times this minimum is found."))
        self.freq_entry = FCEntry()
        self.freq_entry.setReadOnly(True)
        res_grid.addWidget(self.freq_label, 2, 0)
        res_grid.addWidget(self.freq_entry, 2, 1, 1, 2)
        self.locations_cb = FCCheckBox(_("Minimum points coordinates"))
        self.locations_cb.setToolTip(_("Coordinates for points where minimum distance was found."))
        res_grid.addWidget(self.locations_cb, 4, 0, 1, 3)
        self.locations_textb = FCTextArea()
        self.locations_textb.setPlaceholderText(_("Coordinates for points where minimum distance was found."))
        self.locations_textb.setReadOnly(True)
        stylesheet = """
                                QTextEdit { selection-background-color:blue;
                                            selection-color:white;
                                }
                             """
        self.locations_textb.setStyleSheet(stylesheet)
        res_grid.addWidget(self.locations_textb, 6, 0, 1, 3)
        self.locate_button = FCButton(_("Jump to selected position"))
        self.locate_button.setToolTip(_("Select a position in the Locations text box and then\n"
                                        "click this button."))
        self.locate_button.setMinimumWidth(60)
        self.locate_button.setDisabled(True)
        res_grid.addWidget(self.locate_button, 8, 0, 1, 3)

        self.title_second_res_label = FCLabel('%s' % _("Other distances"), color='magenta', bold=True)
        self.title_second_res_label.setToolTip(_("Will display other distances in the Gerber file ordered from\n"
                                                 "the minimum to the maximum, not including the absolute minimum."))
        self.layout.addWidget(self.title_second_res_label)
        other_frame = FCFrame()
        self.layout.addWidget(other_frame)
        other_grid = GLay(v_spacing=5, h_spacing=3)
        other_frame.setLayout(other_grid)
        self.sec_locations_cb = FCCheckBox(_("Other distances points coordinates"))
        self.sec_locations_cb.setToolTip(_("Other distances and the coordinates for points\n"
                                           "where the distance was found."))
        other_grid.addWidget(self.sec_locations_cb, 0, 0, 1, 2)
        self.sec_locations_frame = QtWidgets.QFrame()
        self.sec_locations_frame.setContentsMargins(0, 0, 0, 0)
        other_grid.addWidget(self.sec_locations_frame, 2, 0, 1, 2)
        self.distances_box = QtWidgets.QVBoxLayout()
        self.distances_box.setContentsMargins(0, 0, 0, 0)
        self.sec_locations_frame.setLayout(self.distances_box)
        self.distances_label = FCLabel('%s' % _("Gerber distances"))
        self.distances_label.setToolTip(_("Other distances and the coordinates for points\n"
                                          "where the distance was found."))
        self.distances_box.addWidget(self.distances_label)
        self.distances_textb = FCTextArea()
        self.distances_textb.setPlaceholderText(_("Other distances and the coordinates for points\n"
                                                  "where the distance was found."))
        self.distances_textb.setReadOnly(True)
        self.distances_textb.setStyleSheet(stylesheet)
        self.distances_box.addWidget(self.distances_textb)
        self.distances_box.addWidget(FCLabel(''))
        self.locations_label = FCLabel('%s' % _("Points coordinates"))
        self.locations_label.setToolTip(_("Other distances and the coordinates for points\n"
                                          "where the distance was found."))
        self.distances_box.addWidget(self.locations_label)
        self.locations_sec_textb = FCTextArea()
        self.locations_sec_textb.setPlaceholderText(_("Other distances and the coordinates for points\n"
                                                     "where the distance was found."))
        self.locations_sec_textb.setReadOnly(True)
        self.locations_sec_textb.setStyleSheet(stylesheet)
        self.distances_box.addWidget(self.locations_sec_textb)
        self.locate_sec_button = FCButton(_("Jump to selected position"))
        self.locate_sec_button.setToolTip(_("Select a position in the Locations text box and then\n"
                                            "click this button."))
        self.locate_sec_button.setMinimumWidth(60)
        self.locate_sec_button.setDisabled(True)
        self.distances_box.addWidget(self.locate_sec_button)

        self.calculate_button = FCButton(_("Find Minimum"), bold=True)
        self.calculate_button.setIcon(QtGui.QIcon(self.app.resource_location + '/open_excellon32.png'))
        self.calculate_button.setToolTip(_("Calculate the minimum distance between copper features,\n"
                                           "this will allow the determination of the right tool to\n"
                                           "use for isolation or copper clearing."))
        self.calculate_button.setMinimumWidth(60)
        self.layout.addWidget(self.calculate_button)
        GLay.set_common_column_size([param_grid, res_grid], 0)
        self.layout.addStretch(1)
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.layout.addWidget(self.reset_button)
        self.loc_ois = OptionalHideInputSection(self.locations_cb, [self.locations_textb, self.locate_button])
        self.sec_loc_ois = OptionalHideInputSection(self.sec_locations_cb, [self.sec_locations_frame])

    def on_update_text(self, data):
        txt = ''
        for loc in data:
            if loc:
                txt += '%s, %s\n' % (str(loc[0]), str(loc[1]))
        self.locations_textb.setPlainText(txt)
        self.locate_button.setDisabled(False)

    def on_update_sec_distances_txt(self, data):
        distance_list = sorted(list(data.keys()))
        txt = ''
        for loc in distance_list:
            txt += '%s\n' % str(loc)
        self.distances_textb.setPlainText(txt)
        self.locate_sec_button.setDisabled(False)

    def on_update_locations_text(self, data):
        txt = ''
        for loc in data:
            if loc:
                txt += '%s, %s\n' % (str(loc[0]), str(loc[1]))
        self.locations_sec_textb.setPlainText(txt)

    @staticmethod
    def clear_highlight(text_box):
        cursor = text_box.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.Document)
        tmp = cursor.blockFormat()
        tmp.clearBackground()
        cursor.setBlockFormat(tmp)

    def highlight_current_line(self, text_box):
        self.clear_highlight(text_box)
        cursor = text_box.textCursor()
        cursor.select(QtGui.QTextCursor.SelectionType.LineUnderCursor)
        tmp = cursor.blockFormat()
        tmp.setBackground(QtGui.QBrush(QtCore.Qt.GlobalColor.yellow))
        cursor.setBlockFormat(tmp)
        return cursor.selectedText()

    def confirmation_message(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%.*f, %.*f]' %
                                            (_("Edited value is out of range"), self.decimals, minval,
                                             self.decimals, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)

    def confirmation_message_int(self, accepted, minval, maxval):
        if accepted is False:
            self.app.inform[str, bool].emit('[WARNING_NOTCL] %s: [%d, %d]' %
                                            (_("Edited value is out of range"), minval, maxval), False)
        else:
            self.app.inform[str, bool].emit('[success] %s' % _("Edited value is within limits."), False)
