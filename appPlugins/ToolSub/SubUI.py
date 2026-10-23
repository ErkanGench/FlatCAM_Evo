# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 4/24/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class SubUI:

    pluginName = _("Subtract")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        self.title_box = QtWidgets.QHBoxLayout()
        self.layout.addLayout(self.title_box)

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("A plugin to help subtract a Gerber/Geometry object from another of the same type.")
        )
        self.title_box.addWidget(title_label)

        # App Level label
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

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        # #############################################################################################################
        # COMMON PARAMETERS Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters that are common for all tools."))
        self.tools_box.addWidget(self.param_label)

        self.gp_frame = FCFrame()
        self.tools_box.addWidget(self.gp_frame)

        param_grid = GLay(v_spacing=5, h_spacing=3)
        self.gp_frame.setLayout(param_grid)

        self.delete_sources_cb = FCCheckBox(_("Delete source"))
        self.delete_sources_cb.setToolTip(
            _("When checked will delete the source objects\n"
              "after a successful operation.")
        )
        param_grid.addWidget(self.delete_sources_cb, 0, 0, 1, 2)

        # #############################################################################################################
        # Gerber Subtraction Frame
        # #############################################################################################################
        self.grb_label = FCLabel('%s' % _("Gerber"), color='green', bold=True)
        self.tools_box.addWidget(self.grb_label)

        grb_frame = FCFrame()
        self.tools_box.addWidget(grb_frame)

        grb_grid = GLay(v_spacing=5, h_spacing=3)
        grb_frame.setLayout(grb_grid)

        # Target Gerber Object
        self.target_gerber_label = FCLabel('%s:' % _("Target"))
        self.target_gerber_label.setToolTip(
            _("Gerber object from which to subtract\n"
              "the subtractor Gerber object.")
        )

        self.target_gerber_combo = FCComboBox()
        self.target_gerber_combo.setModel(self.app.collection)
        self.target_gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        # self.target_gerber_combo.setCurrentIndex(1)
        self.target_gerber_combo.is_last = True
        self.target_gerber_combo.obj_type = "Gerber"

        grb_grid.addWidget(self.target_gerber_label, 0, 0)
        grb_grid.addWidget(self.target_gerber_combo, 0, 1)

        # Substractor Gerber Object
        self.sub_gerber_combo = FCComboBox()
        self.sub_gerber_combo.setModel(self.app.collection)
        self.sub_gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.sub_gerber_combo.is_last = True
        self.sub_gerber_combo.obj_type = "Gerber"

        self.sub_gerber_label = FCLabel('%s:' % _("Subtractor"))
        self.sub_gerber_label.setToolTip(
            _("Gerber object that will be subtracted\n"
              "from the target Gerber object.")
        )

        grb_grid.addWidget(self.sub_gerber_label, 2, 0)
        grb_grid.addWidget(self.sub_gerber_combo, 2, 1)

        # #############################################################################################################
        # Gerber Subtraction Button
        # #############################################################################################################
        self.intersect_btn = FCButton(_('Subtract Gerber'), bold=True)
        self.intersect_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/subtract_btn32.png'))
        self.intersect_btn.setToolTip(
            _("Will remove the area occupied by the subtractor\n"
              "Gerber from the Target Gerber.\n"
              "Can be used to remove the overlapping silkscreen\n"
              "over the soldermask.")
        )
        self.tools_box.addWidget(self.intersect_btn)
        # self.tools_box.addWidget(FCLabel(''))

        # #############################################################################################################
        # Geometry Subtraction Frame
        # #############################################################################################################
        self.geo_label = FCLabel('%s' % _("Geometry"), color='red', bold=True)
        self.tools_box.addWidget(self.geo_label)

        geo_frame = FCFrame()
        self.tools_box.addWidget(geo_frame)

        geo_grid = GLay(v_spacing=5, h_spacing=3)
        geo_frame.setLayout(geo_grid)

        self.geo_title = FCLabel('%s' % _("GEOMETRY"), bold=True)
        self.tools_box.addWidget(self.geo_title)

        # Target Geometry Object
        self.target_geo_label = FCLabel('%s:' % _("Target"))
        self.target_geo_label.setToolTip(
            _("Geometry object from which to subtract\n"
              "the subtractor Geometry object.")
        )

        self.target_geo_combo = FCComboBox()
        self.target_geo_combo.setModel(self.app.collection)
        self.target_geo_combo.setRootModelIndex(self.app.collection.index(2, 0, QtCore.QModelIndex()))
        # self.target_geo_combo.setCurrentIndex(1)
        self.target_geo_combo.is_last = True
        self.target_geo_combo.obj_type = "Geometry"

        geo_grid.addWidget(self.target_geo_label, 0, 0)
        geo_grid.addWidget(self.target_geo_combo, 0, 1)

        # Substractor Geometry Object
        self.sub_geo_label = FCLabel('%s:' % _("Subtractor"))
        self.sub_geo_label.setToolTip(
            _("Geometry object that will be subtracted\n"
              "from the target Geometry object.")
        )

        self.sub_geo_combo = FCComboBox()
        self.sub_geo_combo.setModel(self.app.collection)
        self.sub_geo_combo.setRootModelIndex(self.app.collection.index(2, 0, QtCore.QModelIndex()))
        self.sub_geo_combo.is_last = True
        self.sub_geo_combo.obj_type = "Geometry"

        geo_grid.addWidget(self.sub_geo_label, 2, 0)
        geo_grid.addWidget(self.sub_geo_combo, 2, 1)

        self.close_paths_cb = FCCheckBox(_("Close paths"))
        self.close_paths_cb.setToolTip(_("Checking this will close the paths cut by the subtractor object."))

        geo_grid.addWidget(self.close_paths_cb, 4, 0, 1, 2)

        # #############################################################################################################
        # Geometry Subtraction Button
        # #############################################################################################################
        self.intersect_geo_btn = FCButton(_('Subtract Geometry'), bold=True)
        self.intersect_geo_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/subtract_btn32.png'))
        self.intersect_geo_btn.setToolTip(
            _("Will remove the area occupied by the subtractor\n"
              "Geometry from the Target Geometry.")
        )

        self.tools_box.addWidget(self.intersect_geo_btn)

        self.tools_box.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.tools_box.addWidget(self.reset_button)

        # #################################### FINSIHED GUI ###########################
        # #############################################################################

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
