# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     11/12/2020                                     #
# License:  MIT Licence                                    #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox
from appPlugins.Common.levelling_ui import build_probe_points_ui

import gettext
import appTranslation as fcTranslate
import builtins


fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class LevelUI:
    pluginName = _("Levelling")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout
        self.persist_probe_preference = None

        self.tools_frame = QtWidgets.QFrame()
        self.tools_frame.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.tools_frame)
        self.tools_box = QtWidgets.QVBoxLayout()
        self.tools_box.setContentsMargins(0, 0, 0, 0)
        self.tools_frame.setLayout(self.tools_box)

        self.title_box = QtWidgets.QHBoxLayout()
        self.tools_box.addLayout(self.title_box)

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Generate CNC Code with auto-levelled paths.")
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
        # self.level.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.level.setCheckable(True)
        self.title_box.addWidget(self.level)

        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("CNCJob source object to be levelled.")
        )

        self.tools_box.addWidget(self.obj_combo_label)

        # #############################################################################################################
        # ################################ The object to be Auto-levelled ##############################################
        # #############################################################################################################
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(3, 0, QtCore.QModelIndex()))
        # self.object_combo.setCurrentIndex(1)
        self.object_combo.is_last = True

        self.tools_box.addWidget(self.object_combo)

        # separator_line = QtWidgets.QFrame()
        # separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        # separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        # self.tools_box.addWidget(separator_line)

        build_probe_points_ui(self, self.app, self.tools_box, connect_preferences=False)

        # #############################################################################################################
        # Controller Frame
        # #############################################################################################################
        self.al_controller_label = FCLabel('%s' % _("Controller"), color='red', bold=True)
        self.al_controller_label.setToolTip(
            _("The kind of controller for which to generate\n"
              "height map gcode.")
        )
        self.al_box.addWidget(self.al_controller_label)

        self.c_frame = FCFrame()
        self.al_box.addWidget(self.c_frame)

        ctrl_grid = GLay(v_spacing=5, h_spacing=3)
        self.c_frame.setLayout(ctrl_grid)

        self.al_controller_combo = FCComboBox()
        self.al_controller_combo.addItems(["MACH3", "MACH4", "LinuxCNC"])
        ctrl_grid.addWidget(self.al_controller_combo, 0, 0, 1, 2)


        height_lay = QtWidgets.QHBoxLayout()
        self.h_gcode_button = FCButton(_("Save Probing GCode"))
        self.h_gcode_button.setToolTip(
            _("Will save the probing GCode.")
        )
        self.h_gcode_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                          QtWidgets.QSizePolicy.Policy.MinimumExpanding)

        height_lay.addWidget(self.h_gcode_button)
        self.view_h_gcode_button = QtWidgets.QToolButton()
        self.view_h_gcode_button.setIcon(QtGui.QIcon(self.app.resource_location + '/edit_file32.png'))
        # self.view_h_gcode_button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
        #                                        QtWidgets.QSizePolicy.Policy.Ignored)
        self.view_h_gcode_button.setToolTip(
            _("View/Edit the probing GCode.")
        )
        # height_lay.addStretch()
        height_lay.addWidget(self.view_h_gcode_button)

        self.al_box.addLayout(height_lay)


        # self.h_gcode_button.hide()
        # self.import_heights_button.hide()

        # separator_line = QtWidgets.QFrame()
        # separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        # separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        # grid0.addWidget(separator_line, 35, 0, 1, 2)

        self.tools_box.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.tools_box.addWidget(self.reset_button)
        # ############################ FINISHED GUI ###################################
        # #############################################################################

        GLay.set_common_column_size([self.tool_grid, self.param_grid], 0)

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

    def on_plot_points_changed(self, state):
        if self.persist_probe_preference is not None:
            self.persist_probe_preference("tools_al_plot_points", state)

    def on_avoid_exc_holes_changed(self, state):
        if self.persist_probe_preference is not None:
            self.persist_probe_preference("tools_al_avoid_exc_holes", state)
