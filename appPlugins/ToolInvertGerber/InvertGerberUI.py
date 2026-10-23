# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 2/14/2020                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, RadioSet, FCDoubleSpinner

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class InvertUI:

    pluginName = _("Invert Gerber")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)

        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # Source Object Frame
        self.gerber_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.gerber_label.setToolTip(_("Gerber object that will be inverted."))
        self.tools_box.addWidget(self.gerber_label)

        self.gerber_combo = FCComboBox()
        self.gerber_combo.setModel(self.app.collection)
        self.gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.gerber_combo.is_last = True
        self.gerber_combo.obj_type = "Gerber"
        self.tools_box.addWidget(self.gerber_combo)

        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip('%s.' % _("Parameters for this tool"))
        self.tools_box.addWidget(self.param_label)

        self.gp_frame = FCFrame()
        self.tools_box.addWidget(self.gp_frame)
        grid0 = GLay(v_spacing=5, h_spacing=3)
        self.gp_frame.setLayout(grid0)

        self.margin_label = FCLabel('%s:' % _('Margin'))
        self.margin_label.setToolTip(
            _("Distance by which to avoid\n"
              "the edges of the Gerber object.")
        )
        self.margin_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.margin_entry.set_precision(self.decimals)
        self.margin_entry.set_range(0.0000, 10000.0000)
        self.margin_entry.setObjectName(_("Margin"))
        grid0.addWidget(self.margin_label, 0, 0)
        grid0.addWidget(self.margin_entry, 0, 1)

        self.join_label = FCLabel('%s:  ' % _("Lines Join Style"))
        self.join_label.setToolTip(
            _("The way that the lines in the object outline will be joined.\n"
              "Can be:\n"
              "- rounded -> an arc is added between two joining lines\n"
              "- square -> the lines meet in 90 degrees angle\n"
              "- bevel -> the lines are joined by a third line")
        )
        self.join_radio = RadioSet([
            {'label': _('Rounded'), 'value': 'r'},
            {'label': _('Square'), 'value': 's'},
            {'label': _('Bevel'), 'value': 'b'}
        ], orientation='vertical', compact=True)
        grid0.addWidget(self.join_label, 2, 0)
        grid0.addWidget(self.join_radio, 2, 1)

        self.invert_btn = FCButton(_('Invert Gerber'), bold=True)
        self.invert_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/invert32.png'))
        self.invert_btn.setToolTip(
            _("Will invert the Gerber object: areas that have copper\n"
              "will be empty of copper and previous empty area will be\n"
              "filled with copper.")
        )
        self.tools_box.addWidget(self.invert_btn)
        self.tools_box.addStretch(1)

        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(_("Will reset the tool parameters."))
        self.tools_box.addWidget(self.reset_button)

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
