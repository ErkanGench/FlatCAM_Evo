
from PyQt6 import QtWidgets

from appGUI.GUIElements import FCButton, FCLabel
from appGUI.preferences.OptionsGroupUI import OptionsGroupUI

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class FAFlatPrefGroupUI(OptionsGroupUI):
    def __init__(self, app, parent=None):
        super(FAFlatPrefGroupUI, self).__init__(self, parent=parent)

        self.setTitle(str(_("FlatCAM Files associations")))
        self.decimals = app.decimals
        self.options = app.options

        self.ext_label = FCLabel('%s:' % _("Extensions"), bold=True)
        self.ext_label.setToolTip(_("The FlatCAM project and configuration file extensions."))
        self.layout.addWidget(self.ext_label)

        self.ext_value = FCLabel('.flatprj, .flatconfig')
        self.layout.addWidget(self.ext_value)

        self.reg_btn = FCButton(_("Apply Association"))
        self.reg_btn.setToolTip(_("Apply the file associations between\n"
                                  "FlatCAM and the project and configuration files.\n"
                                  "They will be active after next logon.\n"
                                  "This work only in Windows."))
        self.unreg_btn = FCButton(_("Remove Association"))
        self.unreg_btn.setToolTip(_("Remove the file associations written by 'Apply Association'.\n"
                                    "Associations that now belong to another application are kept.\n"
                                    "This work only in Windows."))

        hlay = QtWidgets.QHBoxLayout()
        self.layout.addLayout(hlay)
        hlay.addWidget(self.reg_btn)
        hlay.addWidget(self.unreg_btn)
