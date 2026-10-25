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
            _("Create a Geometry object along the center line of the Gerber traces and paths.\n"
              "The pads (flashes) are skipped, only the traces, arcs and region outlines are followed.\n"
              "The Gerber object is not changed.")
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
            _("The Gerber object to be followed.\n"
              "When Gerber objects are selected in the Project tab, every selected one is followed,\n"
              "each into its own new Geometry object. Otherwise the object chosen here is followed.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        source_frame = FCFrame()
        self.tools_box.addWidget(source_frame)
        source_grid = GLay(v_spacing=5, h_spacing=3)
        source_frame.setLayout(source_grid)

        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.object_combo.is_last = True
        self.object_combo.obj_type = "Gerber"
        source_grid.addWidget(self.object_combo, 0, 0, 1, 3)

        self.apertures_label = FCLabel('%s:' % _("Apertures"))
        self.apertures_label.setToolTip(
            _("Follow only the paths drawn with the selected apertures: aperture code, type and size.\n"
              "No selection means all the apertures.\n"
              "Used only when a single Gerber object is followed (the object above).")
        )
        source_grid.addWidget(self.apertures_label, 2, 0, 1, 3)

        self.apertures_list = QtWidgets.QListWidget()
        self.apertures_list.setMaximumHeight(110)
        self.apertures_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        source_grid.addWidget(self.apertures_list, 4, 0, 1, 3)

        # #############################################################################################################
        # PARAMETERS Frame
        # #############################################################################################################
        self.param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.param_label.setToolTip(_("Parameters that are common for all tools."))
        self.tools_box.addWidget(self.param_label)

        self.gp_frame = FCFrame()
        self.tools_box.addWidget(self.gp_frame)

        grid0 = GLay(v_spacing=5, h_spacing=3)
        self.gp_frame.setLayout(grid0)

        # Tool diameter mode
        self.dia_mode_label = FCLabel('%s:' % _("Tool Diameter"))
        self.dia_mode_label.setToolTip(
            _("The diameter of the tools in the new Geometry object.\n"
              "- Mill default: one tool, the diameter from the Milling preferences.\n"
              "- Aperture size: one tool for each aperture size; the paths of the apertures\n"
              "  with the same size are in the same tool. The regions use the Mill default diameter.")
        )
        self.dia_mode_radio = RadioSet([{'label': _("Mill default"), 'value': 'default'},
                                        {'label': _("Aperture size"), 'value': 'aperture'}],
                                       orientation='vertical', compact=True)
        grid0.addWidget(self.dia_mode_label, 0, 0)
        grid0.addWidget(self.dia_mode_radio, 0, 1, 1, 2)

        # Simplification
        self.simplify_cb = FCCheckBox(_("Simplify"))
        self.simplify_cb.setToolTip(
            _("If checked, the paths are simplified with the given tolerance:\n"
              "the vertices that deviate less than the tolerance from the line are removed.\n"
              "The output has fewer points per path.")
        )
        self.tol_label = FCLabel('%s:' % _('Tolerance'))
        self.tol_label.setToolTip(
            _("The tolerance of the simplification, in application units.\n"
              "Used only when Simplify is checked.")
        )
        self.tol_entry = FCDoubleSpinner()
        self.tol_entry.set_range(0.0, 10000.0)
        self.tol_entry.set_precision(max(int(self.decimals), 4))
        self.tol_entry.setSingleStep(0.01)
        self.tol_units_label = FCLabel('')

        self.simp_optional = OptionalInputSection(self.simplify_cb, [self.tol_label, self.tol_entry,
                                                                     self.tol_units_label])

        grid0.addWidget(self.simplify_cb, 2, 0, 1, 3)
        grid0.addWidget(self.tol_label, 4, 0)
        grid0.addWidget(self.tol_entry, 4, 1)
        grid0.addWidget(self.tol_units_label, 4, 2)

        # UNION
        self.union_cb = FCCheckBox(_("Union"))
        self.union_cb.setToolTip(
            _("If checked, the paths that cross each other are cut at the crossing points.\n"
              "The output has no overlapping duplicate segments: a junction becomes a node\n"
              "where the paths meet, and the paths are not run twice.")
        )
        grid0.addWidget(self.union_cb, 6, 0, 1, 3)

        # MERGE
        self.merge_cb = FCCheckBox(_("Merge"))
        self.merge_cb.setToolTip(
            _("If checked, the paths that touch end to end are joined into one longer path.\n"
              "The output has fewer, longer paths and fewer tool lifts.\n"
              "The paths are joined only where exactly two of them meet.")
        )
        grid0.addWidget(self.merge_cb, 8, 0, 1, 3)

        # #############################################################################################################
        # SELECTION Frame
        # #############################################################################################################
        self.select_frame_label = FCLabel('%s' % _("Selection"), color='brown', bold=True)
        self.tools_box.addWidget(self.select_frame_label)
        self.select_frame = FCFrame()
        self.tools_box.addWidget(self.select_frame)
        grid1 = GLay(v_spacing=5, h_spacing=3)
        self.select_frame.setLayout(grid1)

        # Polygon selection
        self.select_label = FCLabel('%s:' % _('Area'))
        self.select_label.setToolTip(
            _("Selection of the area to be followed.\n"
              "- 'All' - the whole object is followed after the click on Generate.\n"
              "- 'Area Selection' - after the click on Generate, draw one or more zones on the canvas:\n"
              "  left click to add the corners, right click to finish. Escape cancels.\n"
              "  Only the parts of the paths inside the zones are followed.")
        )

        self.select_method_radio = RadioSet([{'label': _("All"), 'value': 'all'},
                                             {'label': _("Area Selection"), 'value': 'area'}])

        grid1.addWidget(self.select_label, 0, 0)
        grid1.addWidget(self.select_method_radio, 0, 1)

        # Area Selection shape
        self.area_shape_label = FCLabel('%s:' % _("Shape"))
        self.area_shape_label.setToolTip(
            _("The kind of selection shape used for area selection.")
        )

        self.area_shape_radio = RadioSet([{'label': _("Square"), 'value': 'square'},
                                          {'label': _("Polygon"), 'value': 'polygon'}])

        grid1.addWidget(self.area_shape_label, 2, 0)
        grid1.addWidget(self.area_shape_radio, 2, 1)

        self.area_shape_label.hide()
        self.area_shape_radio.hide()

        self.preview_button = FCButton(_("Preview"), bold=True)
        self.preview_button.setToolTip(
            _("Draw the lines that would be created for the source object on the canvas.\n"
              "Nothing is created. The area selection is not used by the preview.")
        )
        self.tools_box.addWidget(self.preview_button)

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

    def populate_apertures(self, tools):
        """Fill the aperture list with the code, type and size of every aperture. Nothing selected means all."""
        self.apertures_list.blockSignals(True)
        self.apertures_list.clear()
        for code in sorted(tools, key=lambda k: (not str(k).lstrip('-').isdigit(),
                                                 int(k) if str(k).lstrip('-').isdigit() else 0, str(k))):
            tool = tools[code]
            try:
                size = self.app.dec_format(float(tool.get('size') or 0.0), self.decimals)
            except (TypeError, ValueError):
                size = ''
            item = QtWidgets.QListWidgetItem('%s   %s   %s' % (code, tool.get('type', ''), size))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, code)
            self.apertures_list.addItem(item)
        self.apertures_list.blockSignals(False)

    def selected_apertures(self):
        """The codes of the selected apertures, or None when nothing is selected (all apertures)."""
        codes = [item.data(QtCore.Qt.ItemDataRole.UserRole) for item in self.apertures_list.selectedItems()]
        return codes or None

    def on_selection(self, val):
        if val == 'area':  # _("Area Selection")
            self.area_shape_label.show()
            self.area_shape_radio.show()
        else:   # All
            self.area_shape_label.hide()
            self.area_shape_radio.hide()

    def set_level(self, checked):
        widgets = (self.gp_frame, self.param_label, self.select_frame, self.select_frame_label,
                   self.apertures_label, self.apertures_list)
        if not checked:
            self.level.setText('%s' % _('Beginner'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)
            for wdg in widgets:
                wdg.hide()
        else:
            self.level.setText('%s' % _('Advanced'))
            self.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)
            for wdg in widgets:
                wdg.show()

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
