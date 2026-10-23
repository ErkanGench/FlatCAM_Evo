from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import (FCLabel, FCButton, FCFrame, GLay, FCComboBox, RadioSet,
                                FCDoubleSpinner, FCCheckBox, OptionalInputSection)

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class FollowUI:

    pluginName = _("Follow")

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

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        title_label.setToolTip(
            _("Create a Geometry object with\n"
              "toolpaths to cut through the middle of polygons.")
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

        # #############################################################################################################
        # ################################ The object to be followed ##################################################
        # #############################################################################################################
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("A Gerber object to be followed.\n"
              "Create a Geometry object with a path\n"
              "following the Gerber traces.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = True

        self.tools_box.addWidget(self.object_combo)

        # #############################################################################################################
        # COMMON PARAMETERS Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters that are common for all tools."))
        self.tools_box.addWidget(self.param_label)

        self.gp_frame = FCFrame()
        self.tools_box.addWidget(self.gp_frame)

        grid0 = GLay(v_spacing=5, h_spacing=3)
        self.gp_frame.setLayout(grid0)

        # Simplification
        self.simplify_cb = FCCheckBox(_("Simplify"))
        self.simplify_cb.setToolTip(
            _("If checked, the toolpaths will be simplified with the given tolerance.")
        )
        self.tol_label = FCLabel('%s:' % _('Tolerance'))
        self.tol_label.setToolTip(
            _("The tolerance of the simplification.")
        )
        self.tol_entry = FCDoubleSpinner()
        self.tol_entry.set_range(0.0, 10000.0)
        self.tol_entry.set_precision(self.decimals)
        self.tol_entry.setSingleStep(0.01)

        self.simp_optional = OptionalInputSection(self.simplify_cb, [self.tol_label, self.tol_entry])

        grid0.addWidget(self.simplify_cb, 0, 0, 1, 2)
        grid0.addWidget(self.tol_label, 2, 0)
        grid0.addWidget(self.tol_entry, 2, 1)

        # UNION
        self.union_cb = FCCheckBox(_("Union"))
        self.union_cb.setToolTip(
            _("If checked, the toolpaths will be joined into a Union.")
        )

        grid0.addWidget(self.union_cb, 4, 0, 1, 2)

        # Polygon selection
        self.select_label = FCLabel('%s:' % _('Selection'))
        self.select_label.setToolTip(
            _("Selection of area to be processed.\n"
              "- 'All Polygons' - the process will start after click.\n"
              "- 'Area Selection' - left mouse click to start selection of the area to be processed.")
        )

        self.select_method_radio = RadioSet([{'label': _("All"), 'value': 'all'},
                                             {'label': _("Area Selection"), 'value': 'area'}])

        grid0.addWidget(self.select_label, 6, 0)
        grid0.addWidget(self.select_method_radio, 6, 1)

        # Area Selection shape
        self.area_shape_label = FCLabel('%s:' % _("Shape"))
        self.area_shape_label.setToolTip(
            _("The kind of selection shape used for area selection.")
        )

        self.area_shape_radio = RadioSet([{'label': _("Square"), 'value': 'square'},
                                          {'label': _("Polygon"), 'value': 'polygon'}])

        grid0.addWidget(self.area_shape_label, 8, 0)
        grid0.addWidget(self.area_shape_radio, 8, 1)

        self.area_shape_label.hide()
        self.area_shape_radio.hide()

        self.generate_geometry_button = FCButton("%s" % _("Generate Geometry"), bold=True)
        self.generate_geometry_button.setIcon(QtGui.QIcon(self.app.resource_location + '/geometry32.png'))
        self.generate_geometry_button.setToolTip(_("Generate a 'Follow' geometry.\n"
                                                   "This means that it will cut through\n"
                                                   "the middle of the trace."))
        self.tools_box.addWidget(self.generate_geometry_button)

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

    def on_selection(self, val):
        if val == 'area':  # _("Area Selection")
            self.area_shape_label.show()
            self.area_shape_radio.show()
        else:   # All
            self.area_shape_label.hide()
            self.area_shape_radio.hide()

    def set_level(self, checked):
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)
            self.gp_frame.hide()
            self.param_label.hide()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)
            self.gp_frame.show()
            self.param_label.show()

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
