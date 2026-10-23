"""Widgets for the PcbWizard importer."""

from PyQt6 import QtWidgets, QtCore
from appGUI.GUIElements import FCLabel, FCButton, GLay, RadioSet, FCSpinner, FCTable

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class WizardUI:

    pluginName = _("PcbWizard Import")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)
        self.layout.addWidget(FCLabel(""))
        self.layout.addWidget(FCLabel("<b>%s:</b>" % _("Load files")))
        grid0 = GLay(v_spacing=5, h_spacing=3)
        self.layout.addLayout(grid0)
        self.excellon_label = FCLabel('%s:' % _("Excellon file"))
        self.excellon_label.setToolTip(_("Load the Excellon file.\n"
                                         "Usually it has a .DRL extension"))
        self.excellon_brn = FCButton(_("Open"))
        grid0.addWidget(self.excellon_label, 0, 0)
        grid0.addWidget(self.excellon_brn, 0, 1)
        self.inf_label = FCLabel('%s:' % _("INF file"))
        self.inf_label.setToolTip(_("Load the INF file."))
        self.inf_btn = FCButton(_("Open"))
        grid0.addWidget(self.inf_label, 2, 0)
        grid0.addWidget(self.inf_btn, 2, 1)

        self.tools_table = FCTable()
        self.layout.addWidget(self.tools_table)
        self.tools_table.setColumnCount(2)
        self.tools_table.setHorizontalHeaderLabels(['#Tool', _('Diameter')])
        self.tools_table.horizontalHeaderItem(0).setToolTip(_("Tool Number"))
        self.tools_table.horizontalHeaderItem(1).setToolTip(_("Tool diameter in file units."))
        self.tools_table.setVisible(False)
        self.layout.addWidget(FCLabel(""))
        self.layout.addWidget(FCLabel("<b>%s:</b>" % _("Excellon Format")))
        grid01 = GLay(v_spacing=5, h_spacing=3)
        self.layout.addLayout(grid01)
        self.int_entry = FCSpinner(callback=self.confirmation_message_int)
        self.int_entry.set_range(1, 10)
        self.int_label = FCLabel('%s:' % _("Int. digits"))
        self.int_label.setToolTip(_("The number of digits for the integral part of the coordinates."))
        grid01.addWidget(self.int_label, 0, 0)
        grid01.addWidget(self.int_entry, 0, 1)
        self.frac_entry = FCSpinner(callback=self.confirmation_message_int)
        self.frac_entry.set_range(1, 10)
        self.frac_label = FCLabel('%s:' % _("Frac. digits"))
        self.frac_label.setToolTip(_("The number of digits for the fractional part of the coordinates."))
        grid01.addWidget(self.frac_label, 2, 0)
        grid01.addWidget(self.frac_entry, 2, 1)
        self.zeros_radio = RadioSet([{'label': _('LZ'), 'value': 'LZ'},
                                     {'label': _('TZ'), 'value': 'TZ'},
                                     {'label': _('No Suppression'), 'value': 'D'}])
        self.zeros_label = FCLabel('%s:' % _("Zeros supp."))
        self.zeros_label.setToolTip(_("The type of zeros suppression used.\n"
                                      "Can be of type:\n"
                                      "- LZ = leading zeros are kept\n"
                                      "- TZ = trailing zeros are kept\n"
                                      "- No Suppression = no zero suppression"))
        grid01.addWidget(self.zeros_label, 4, 0)
        grid01.addWidget(self.zeros_radio, 4, 1)
        self.units_radio = RadioSet([{'label': _('Inch'), 'value': 'INCH'},
                                     {'label': _('mm'), 'value': 'METRIC'}])
        self.units_label = FCLabel('%s:' % _('Units'), bold=True)
        self.units_label.setToolTip(_("The type of units that the coordinates and tool\n"
                                      "diameters are using. Can be INCH or MM."))
        grid01.addWidget(self.units_label, 6, 0)
        grid01.addWidget(self.units_radio, 6, 1)
        self.import_button = FCButton(_("Import Excellon"))
        self.import_button.setToolTip(_("Import an Excellon file\n"
                                        "that store it's information's in 2 files.\n"
                                        "One usually has .DRL extension while\n"
                                        "the other has .INF extension."))
        grid01.addWidget(self.import_button, 8, 0, 1, 2)
        self.layout.addStretch(1)

    def build_tools_table(self, tools):
        sorted_tools = []
        if not tools:
            self.tools_table.setVisible(False)
        else:
            sorted_tools = sorted(int(k) for k in tools)
            self.tools_table.setRowCount(len(sorted_tools))
        for tool_row, tool in enumerate(sorted_tools):
            tool_id_item = QtWidgets.QTableWidgetItem('%d' % int(tool))
            tool_id_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.tools_table.setItem(tool_row, 0, tool_id_item)
            tool_dia_item = QtWidgets.QTableWidgetItem(str(tools[tool]))
            tool_dia_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.tools_table.setItem(tool_row, 1, tool_dia_item)
        self.tools_table.resizeColumnsToContents()
        self.tools_table.resizeRowsToContents()
        self.tools_table.verticalHeader().hide()
        self.tools_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        horizontal_header = self.tools_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tools_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tools_table.setSortingEnabled(False)
        self.tools_table.setMinimumHeight(self.tools_table.getHeight())
        self.tools_table.setMaximumHeight(self.tools_table.getHeight())

    def on_units_change(self, val):
        if val == 'INCH':
            self.int_entry.set_value(2)
            self.frac_entry.set_value(4)
        else:
            self.int_entry.set_value(3)
            self.frac_entry.set_value(3)

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
