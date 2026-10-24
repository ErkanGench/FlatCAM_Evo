# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     6/15/2020                                      #
# License:  MIT Licence                                    #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appGUI.GUIElements import FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCComboBox2, RadioSet, FCDoubleSpinner, FCSpinner, NumericalEvalTupleEntry, NumericalEvalEntry, FCTable, \
    OptionalInputSection, OptionalHideInputSection

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class DrillingUI:

    pluginName = _("Drilling")

    def __init__(self, layout, app, name):
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
        title_label = FCLabel("%s" % name, size=16, bold=True)
        title_label.setToolTip(
            _("Create CNCJob with toolpaths for drilling or milling holes.")
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

        # #############################################################################################################
        # Excellon Source Object Frame
        # #############################################################################################################
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("Excellon object for drilling/milling operation.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        # Grid Layout
        obj_grid = GLay(v_spacing=5, h_spacing=3)
        self.tools_box.addLayout(obj_grid)

        # ################################################
        # ##### The object to be drilled #################
        # ################################################
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        # self.object_combo.setCurrentIndex(1)
        self.object_combo.is_last = True

        obj_grid.addWidget(self.object_combo, 0, 0, 1, 2)

        # More Excellon objects in the same job (Advanced level): their tools are merged by diameter
        self.extra_objects_label = FCLabel('%s:' % _("Add objects"))
        self.extra_objects_label.setToolTip(
            _("More Excellon objects that are drilled in the same job. Their tools are merged with the tools of\n"
              "the source object by diameter. The objects themselves are not changed.\n"
              "Click an object to add it or to remove it.")
        )
        self.extra_objects_list = QtWidgets.QListWidget()
        self.extra_objects_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.extra_objects_list.setMaximumHeight(70)
        obj_grid.addWidget(self.extra_objects_label, 1, 0)
        obj_grid.addWidget(self.extra_objects_list, 1, 1)
        self.extra_objects_widgets = [self.extra_objects_label, self.extra_objects_list]

        # separator_line = QtWidgets.QFrame()
        # separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        # separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        # obj_grid.addWidget(separator_line, 2, 0, 1, 2)

        # #############################################################################################################
        # Excellon Tool Table Frame
        # #############################################################################################################
        self.tools_table_label = FCLabel('%s' % _("Tools Table"), color='green', bold=True)
        self.tools_table_label.setToolTip(_("Tools in the object used for drilling."))
        self.tools_box.addWidget(self.tools_table_label)

        tt_frame = FCFrame()
        self.tools_box.addWidget(tt_frame)

        tool_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 0])
        tt_frame.setLayout(tool_grid)

        # Tools Table
        self.tools_table = FCTable(drag_drop=True)
        tool_grid.addWidget(self.tools_table, 0, 0, 1, 2)

        self.tools_table.setColumnCount(5)
        self.tools_table.setColumnHidden(3, True)
        self.tools_table.setSortingEnabled(False)

        self.tools_table.setHorizontalHeaderLabels(['#', _('Diameter'), _('Drills'), '', _('Slots')])
        self.tools_table.horizontalHeaderItem(0).setToolTip(
            _("This is the Tool Number.\n"
              "When ToolChange is checked, on toolchange event this value\n"
              "will be showed as a T1, T2 ... Tn in the Machine Code.\n\n"
              "Here the tools are selected for G-code generation."))
        self.tools_table.horizontalHeaderItem(1).setToolTip(
            _("Tool Diameter. Its value\n"
              "is the cut width into the material."))
        self.tools_table.horizontalHeaderItem(2).setToolTip(
            _("The number of Drill holes. Holes that are drilled with\n"
              "a drill bit."))
        self.tools_table.horizontalHeaderItem(4).setToolTip(
            _("The number of Slot holes. Holes that are created by\n"
              "milling them with an endmill bit."))

        # Tool order
        self.order_label = FCLabel('%s:' % _('Tool order'))
        self.order_label.setToolTip(_("This set the way that the tools in the tools table are used.\n"
                                      "'Default' --> the order from the file\n"
                                      "'Forward' --> tools will be ordered from small to big\n"
                                      "'Reverse' --> tools will ordered from big to small."))

        self.order_combo = FCComboBox2()
        self.order_combo.addItems([_('Default'), _('Forward'), _('Reverse')])

        tool_grid.addWidget(self.order_label, 2, 0)
        tool_grid.addWidget(self.order_combo, 2, 1)

        # Manual Load of Tools from DB
        self.search_load_db_btn = FCButton(_("Search DB"))
        self.search_load_db_btn.setIcon(QtGui.QIcon(self.app.resource_location + '/search_db32.png'))
        self.search_load_db_btn.setToolTip(
            _("Will search and try to replace the tools from Tools Table\n"
              "with tools from DB that have a close diameter value.")
        )

        tool_grid.addWidget(self.search_load_db_btn, 4, 0, 1, 2)

        # #############################################################################################################
        # ALL Parameters Frame
        # #############################################################################################################
        self.tool_data_label = FCLabel(
            '<span style="color:blue;"><b>%s: %s %d</b></span>' % (_('Parameters for'), _("Tool"), int(1)))
        self.tool_data_label.setToolTip(
            _(
                "The data used for creating GCode.\n"
                "Each tool store it's own set of such data."
            )
        )
        self.tools_box.addWidget(self.tool_data_label)

        # shown while extra objects are selected (the tool parameters are read-only then)
        self.extras_note_label = FCLabel(
            _("With added objects the tool parameters are read-only. Remove the added objects to edit them."))
        self.extras_note_label.setWordWrap(True)
        self.extras_note_label.setVisible(False)
        self.tools_box.addWidget(self.extras_note_label)

        self.exc_param_frame = QtWidgets.QFrame()
        self.exc_param_frame.setContentsMargins(0, 0, 0, 0)
        self.tools_box.addWidget(self.exc_param_frame)

        self.exc_tools_box = QtWidgets.QVBoxLayout()
        self.exc_tools_box.setContentsMargins(0, 0, 0, 0)
        self.exc_param_frame.setLayout(self.exc_tools_box)

        # #############################################################################################################
        # Tool Parameters Frame
        # #############################################################################################################
        self.tool_param_frame = FCFrame()
        self.exc_tools_box.addWidget(self.tool_param_frame)

        # Grid Layout
        param_grid = GLay(v_spacing=5, h_spacing=3)
        self.tool_param_frame.setLayout(param_grid)

        # Cut Z
        self.cutzlabel = FCLabel('%s:' % _('Cut Z'))
        self.cutzlabel.setToolTip(
            _("Drill depth (negative)\n"
              "below the copper surface.")
        )

        self.cutz_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.cutz_entry.set_precision(self.decimals)
        self.cutz_entry.set_range(-10000.0000, 10000.0000)

        self.cutz_entry.setSingleStep(0.1)
        self.cutz_entry.setObjectName("e_cutz")

        param_grid.addWidget(self.cutzlabel, 4, 0)
        param_grid.addWidget(self.cutz_entry, 4, 1)

        # Multi-Depth
        self.mpass_cb = FCCheckBox('%s:' % _("Multi-Depth"))
        self.mpass_cb.setToolTip(
            _(
                "Use multiple passes to limit\n"
                "the cut depth in each pass. Will\n"
                "cut multiple times until Cut Z is\n"
                "reached."
            )
        )
        self.mpass_cb.setObjectName("e_multidepth")

        self.maxdepth_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.maxdepth_entry.set_precision(self.decimals)
        self.maxdepth_entry.set_range(0, 10000.0000)
        self.maxdepth_entry.setSingleStep(0.1)

        self.maxdepth_entry.setToolTip(_("Depth of each pass (positive)."))
        self.maxdepth_entry.setObjectName("e_depthperpass")

        self.mis_mpass_geo = OptionalInputSection(self.mpass_cb, [self.maxdepth_entry])

        param_grid.addWidget(self.mpass_cb, 5, 0)
        param_grid.addWidget(self.maxdepth_entry, 5, 1)

        # Travel Z (z_move)
        self.travelzlabel = FCLabel('%s:' % _('Travel Z'))
        self.travelzlabel.setToolTip(
            _("Tool height when travelling\n"
              "across the XY plane.")
        )

        self.travelz_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.travelz_entry.set_precision(self.decimals)
        self.travelz_entry.set_range(-10000.0000, 10000.0000)

        self.travelz_entry.setSingleStep(0.1)
        self.travelz_entry.setObjectName("e_travelz")

        param_grid.addWidget(self.travelzlabel, 6, 0)
        param_grid.addWidget(self.travelz_entry, 6, 1)

        # Excellon Feedrate Z
        self.frzlabel = FCLabel('%s:' % _('Feedrate Z'))
        self.frzlabel.setToolTip(
            _("Tool speed while drilling\n"
              "(in units per minute).\n"
              "So called 'Plunge' feedrate.\n"
              "This is for linear move G01.")
        )
        self.feedrate_z_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.feedrate_z_entry.set_precision(self.decimals)
        self.feedrate_z_entry.set_range(0.0, 910000.0000)
        self.feedrate_z_entry.setSingleStep(0.1)
        self.feedrate_z_entry.setObjectName("e_feedratez")

        param_grid.addWidget(self.frzlabel, 14, 0)
        param_grid.addWidget(self.feedrate_z_entry, 14, 1)

        # Excellon Rapid Feedrate
        self.feedrate_rapid_label = FCLabel('%s:' % _('Feedrate Rapids'))
        self.feedrate_rapid_label.setToolTip(
            _("Tool speed while drilling\n"
              "(in units per minute).\n"
              "This is for the rapid move G00.\n"
              "It is useful only for Marlin,\n"
              "ignore for any other cases.")
        )
        self.feedrate_rapid_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.feedrate_rapid_entry.set_precision(self.decimals)
        self.feedrate_rapid_entry.set_range(0.0, 910000.0000)
        self.feedrate_rapid_entry.setSingleStep(0.1)
        self.feedrate_rapid_entry.setObjectName("e_fr_rapid")

        param_grid.addWidget(self.feedrate_rapid_label, 16, 0)
        param_grid.addWidget(self.feedrate_rapid_entry, 16, 1)

        # default values is to hide
        self.feedrate_rapid_label.hide()
        self.feedrate_rapid_entry.hide()

        # Spindlespeed
        self.spindle_label = FCLabel('%s:' % _('Spindle speed'))
        self.spindle_label.setToolTip(
            _("Speed of the spindle\n"
              "in RPM (optional)")
        )

        self.spindlespeed_entry = FCSpinner(callback=self.confirmation_message_int)
        self.spindlespeed_entry.set_range(0, 1000000)
        self.spindlespeed_entry.set_step(100)
        self.spindlespeed_entry.setObjectName("e_spindlespeed")

        param_grid.addWidget(self.spindle_label, 18, 0)
        param_grid.addWidget(self.spindlespeed_entry, 18, 1)

        # Laser power minimum
        self.las_min_pwr_label = FCLabel('%s:' % _('Min Power'))
        self.las_min_pwr_label.setToolTip(
            "%s\n%s" % (
                _("The laser power when the laser is travelling."),
                _("Above 0 the laser is not turned off between the cuts:\n"
                  "the 'laser OFF' lines set this power instead.\n"
                  "Keep it 0 to turn the laser off between the cuts.")
            )
        )

        self.las_min_pwr_entry = FCSpinner(callback=self.confirmation_message_int)
        self.las_min_pwr_entry.set_range(0, 1000000)
        self.las_min_pwr_entry.set_step(1)
        self.las_min_pwr_entry.setObjectName("e_minpower")

        param_grid.addWidget(self.las_min_pwr_label, 20, 0)
        param_grid.addWidget(self.las_min_pwr_entry, 20, 1)
        self.las_min_pwr_label.hide()
        self.las_min_pwr_entry.hide()

        # Laser Turn ON Code
        self.laser_turn_on_lbl = FCLabel('%s:' % _('Turn ON Code'))
        self.laser_turn_on_lbl.setToolTip(
            _("The Gode that will be executed to turn the laser on.")
        )

        self.laser_turn_on_combo = FCComboBox()
        self.laser_turn_on_combo.addItems(["M03", "M04"])
        self.laser_turn_on_combo.setObjectName("e_laser_turn_on")

        param_grid.addWidget(self.laser_turn_on_lbl, 22, 0)
        param_grid.addWidget(self.laser_turn_on_combo, 22, 1)
        self.laser_turn_on_lbl.hide()
        self.laser_turn_on_combo.hide()

        # Dwell
        self.dwell_cb = FCCheckBox('%s:' % _('Dwell'))
        self.dwell_cb.setToolTip(
            _("Pause to allow the spindle to reach its\n"
              "speed before cutting.")
        )
        self.dwell_cb.setObjectName("e_dwell")

        # Dwelltime
        self.dwelltime_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.dwelltime_entry.set_precision(self.decimals)
        self.dwelltime_entry.set_range(0.0, 10000.0000)
        self.dwelltime_entry.setSingleStep(0.1)

        self.dwelltime_entry.setToolTip(
            _("Number of time units for spindle to dwell.")
        )
        self.dwelltime_entry.setObjectName("e_dwelltime")

        param_grid.addWidget(self.dwell_cb, 24, 0)
        param_grid.addWidget(self.dwelltime_entry, 24, 1)

        self.ois_dwell = OptionalInputSection(self.dwell_cb, [self.dwelltime_entry])

        # Tool Offset
        self.tool_offset_label = FCLabel('%s:' % _('Offset Z'))
        self.tool_offset_label.setToolTip(
            _("Some drill bits (the larger ones) need to drill deeper\n"
              "to create the desired exit hole diameter due of the tip shape.\n"
              "The value here can compensate the Cut Z parameter.")
        )

        self.offset_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.offset_entry.set_precision(self.decimals)
        self.offset_entry.set_range(-10000.0000, 10000.0000)
        self.offset_entry.setObjectName("e_offset")

        param_grid.addWidget(self.tool_offset_label, 26, 0)
        param_grid.addWidget(self.offset_entry, 26, 1)

        # Drill slots
        self.drill_slots_cb = FCCheckBox('%s' % _('Drill slots'))
        self.drill_slots_cb.setToolTip(
            _("If the selected tool has slots then they will be drilled.")
        )
        self.drill_slots_cb.setObjectName("e_drill_slots")
        param_grid.addWidget(self.drill_slots_cb, 28, 0, 1, 2)

        # Drill Overlap
        self.drill_overlap_label = FCLabel('%s:' % _('Overlap'))
        self.drill_overlap_label.setToolTip(
            _("How much (percentage) of the tool diameter to overlap previous drill hole.")
        )

        self.drill_overlap_entry = FCDoubleSpinner(suffix='%', callback=self.confirmation_message)
        self.drill_overlap_entry.set_precision(self.decimals)
        self.drill_overlap_entry.set_range(0.0, 100.0000)
        self.drill_overlap_entry.setSingleStep(0.1)

        self.drill_overlap_entry.setObjectName("e_drill_slots_overlap")

        param_grid.addWidget(self.drill_overlap_label, 30, 0)
        param_grid.addWidget(self.drill_overlap_entry, 30, 1)

        # Last drill in slot
        self.last_drill_cb = FCCheckBox('%s' % _('Last drill'))
        self.last_drill_cb.setToolTip(
            _("If the slot length is not completely covered by drill holes,\n"
              "add a drill hole on the slot end point.")
        )
        self.last_drill_cb.setObjectName("e_drill_last_drill")
        param_grid.addWidget(self.last_drill_cb, 32, 0, 1, 2)

        # Dwell at the bottom of the holes
        self.dwell_bottom_cb = FCCheckBox('%s' % _('Dwell at bottom'))
        self.dwell_bottom_cb.setToolTip(
            _("Pause at the bottom of every hole, for the Dwell time\n"
              "(the time set above, also when Dwell is not checked).\n"
              "Ignored by the laser preprocessors.")
        )
        self.dwell_bottom_cb.setObjectName("e_dwell_bottom")
        param_grid.addWidget(self.dwell_bottom_cb, 34, 0, 1, 2)

        # Peck drilling
        self.peck_cb = FCCheckBox('%s:' % _('Peck drilling'))
        self.peck_cb.setToolTip(
            _("Drill each hole in steps of Peck depth. After each step the tool\n"
              "goes up to the Travel Z (it clears the chips), goes down fast to the\n"
              "Peck retract clearance above the previous depth and feeds on.\n"
              "It replaces the Multi-Depth. Ignored by the laser preprocessors.")
        )
        self.peck_cb.setObjectName("e_peck")

        self.peck_depth_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.peck_depth_entry.set_precision(self.decimals)
        self.peck_depth_entry.set_range(0.0, 10000.0000)
        self.peck_depth_entry.setSingleStep(0.1)
        self.peck_depth_entry.setToolTip(_("Depth of each peck step (positive)."))
        self.peck_depth_entry.setObjectName("e_peck_depth")

        param_grid.addWidget(self.peck_cb, 36, 0)
        param_grid.addWidget(self.peck_depth_entry, 36, 1)

        self.peck_retract_label = FCLabel('%s:' % _('Peck retract'))
        self.peck_retract_label.setToolTip(
            _("Clearance above the previous depth to which the tool goes down fast\n"
              "after the full retract, before it feeds on.")
        )
        self.peck_retract_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.peck_retract_entry.set_precision(self.decimals)
        self.peck_retract_entry.set_range(0.0, 10000.0000)
        self.peck_retract_entry.setSingleStep(0.1)
        self.peck_retract_entry.setObjectName("e_peck_retract")

        param_grid.addWidget(self.peck_retract_label, 38, 0)
        param_grid.addWidget(self.peck_retract_entry, 38, 1)

        self.ois_peck = OptionalInputSection(self.peck_cb, [self.peck_depth_entry, self.peck_retract_label,
                                                            self.peck_retract_entry])

        # Spindle direction
        self.spindledir_label = FCLabel('%s:' % _('Spindle direction'))
        self.spindledir_label.setToolTip(
            _("The direction that the spindle is rotating.\n"
              "It can be either:\n"
              "- CW = clockwise or\n"
              "- CCW = counter clockwise")
        )
        self.spindledir_radio = RadioSet([{'label': _('CW'), 'value': 'CW'},
                                          {'label': _('CCW'), 'value': 'CCW'}], compact=True)
        self.spindledir_radio.setObjectName("e_spindledir")

        param_grid.addWidget(self.spindledir_label, 40, 0)
        param_grid.addWidget(self.spindledir_radio, 40, 1)

        # Fast Plunge
        self.fplunge_cb = FCCheckBox('%s' % _('Fast Plunge'))
        self.fplunge_cb.setToolTip(
            _("By checking this, the vertical move from\n"
              "Z_Toolchange to Z_move is done with G0,\n"
              "meaning the fastest speed available.\n"
              "WARNING: the move is done at Toolchange X,Y coords.")
        )
        self.fplunge_cb.setObjectName("e_f_plunge")
        param_grid.addWidget(self.fplunge_cb, 42, 0, 1, 2)

        # Fast retract
        self.fretract_cb = FCCheckBox('%s' % _('Fast Retract'))
        self.fretract_cb.setToolTip(
            _("Exit hole strategy.\n"
              " - When unchecked, while exiting the drilled hole the drill bit\n"
              "will travel slow, with set feedrate (G1), up to zero depth and then\n"
              "travel as fast as possible (G0) to the Z Move (travel height).\n"
              " - When checked the travel from Z cut (cut depth) to Z_move\n"
              "(travel height) is done as fast as possible (G0) in one move.")
        )
        self.fretract_cb.setObjectName("e_f_retract")
        param_grid.addWidget(self.fretract_cb, 44, 0, 1, 2)

        # the controls of the Advanced level; the peck, the bottom dwell and the spindle direction do not apply to a
        # laser preprocessor
        self.advanced_drill_widgets = [self.dwell_bottom_cb, self.peck_cb, self.peck_depth_entry,
                                       self.peck_retract_label, self.peck_retract_entry, self.spindledir_label,
                                       self.spindledir_radio, self.fplunge_cb, self.fretract_cb]
        self.no_laser_drill_widgets = [self.dwell_bottom_cb, self.peck_cb, self.peck_depth_entry,
                                       self.peck_retract_label, self.peck_retract_entry, self.spindledir_label,
                                       self.spindledir_radio]

        self.drill_overlap_label.hide()
        self.drill_overlap_entry.hide()
        self.last_drill_cb.hide()

        self.ois_drill_overlap = OptionalHideInputSection(
            self.drill_slots_cb,
            [
                self.drill_overlap_label,
                self.drill_overlap_entry,
                self.last_drill_cb
            ]
        )

        self.apply_param_to_all = FCButton(_("Apply parameters to all tools"))
        self.apply_param_to_all.setIcon(QtGui.QIcon(self.app.resource_location + '/param_all32.png'))
        self.apply_param_to_all.setToolTip(
            _("The parameters in the current form will be applied\n"
              "on all the tools from the Tool Table.")
        )
        self.exc_tools_box.addWidget(self.apply_param_to_all)

        # #############################################################################################################
        # COMMON PARAMETERS Frame
        # #############################################################################################################
        # General Parameters
        self.gen_param_label = FCLabel('%s' % _("Common Parameters"), color='indigo', bold=True)
        self.gen_param_label.setToolTip(
            _("Parameters that are common for all tools.")
        )
        self.exc_tools_box.addWidget(self.gen_param_label)

        gp_frame = FCFrame()
        self.exc_tools_box.addWidget(gp_frame)

        all_par_grid = GLay(v_spacing=5, h_spacing=3)
        gp_frame.setLayout(all_par_grid)

        # Tool change
        self.toolchange_cb = FCCheckBox('%s:' % _("Tool change Z"))
        self.toolchange_cb.setToolTip(
            _("Include tool-change sequence\n"
              "in G-Code (Pause for tool change).")
        )
        self.toolchange_cb.setObjectName("e_toolchange")

        # Tool change Z
        self.toolchangez_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.toolchangez_entry.setToolTip(
            _("Z-axis position (height) for\n"
              "tool change.")
        )
        self.toolchangez_entry.set_precision(self.decimals)
        self.toolchangez_entry.setObjectName("e_toolchangez")
        self.toolchangez_entry.set_range(-10000.0000, 10000.0000)

        self.toolchangez_entry.setSingleStep(0.1)

        all_par_grid.addWidget(self.toolchange_cb, 0, 0)
        all_par_grid.addWidget(self.toolchangez_entry, 0, 1)

        # Tool change X-Y
        self.toolchange_xy_label = FCLabel('%s:' % _('Toolchange X-Y'))
        self.toolchange_xy_label.setToolTip(
            _("Toolchange X,Y position.")
        )
        self.toolchangexy_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.toolchangexy_entry.setObjectName("e_toolchangexy")

        all_par_grid.addWidget(self.toolchange_xy_label, 2, 0)
        all_par_grid.addWidget(self.toolchangexy_entry, 2, 1)

        self.ois_tcz_e = OptionalInputSection(self.toolchange_cb,
                                              [
                                                  self.toolchangez_entry,
                                                  self.toolchange_xy_label,
                                                  self.toolchangexy_entry
                                              ])

        # Start move Z:
        self.estartz_label = FCLabel('%s:' % _("Start Z"))
        self.estartz_label.setToolTip(
            _("Height of the tool just after starting the work.\n"
              "Delete the value if you don't need this feature.")
        )
        self.estartz_entry = NumericalEvalEntry(border_color='#0069A9')
        self.estartz_entry.setObjectName("e_startz")

        all_par_grid.addWidget(self.estartz_label, 4, 0)
        all_par_grid.addWidget(self.estartz_entry, 4, 1)

        # End move Z:
        self.endz_label = FCLabel('%s:' % _("End move Z"))
        self.endz_label.setToolTip(
            _("Height of the tool after\n"
              "the last move at the end of the job.")
        )
        self.endz_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.endz_entry.set_precision(self.decimals)
        self.endz_entry.setObjectName("e_endz")
        self.endz_entry.set_range(-10000.0000, 10000.0000)

        self.endz_entry.setSingleStep(0.1)

        all_par_grid.addWidget(self.endz_label, 6, 0)
        all_par_grid.addWidget(self.endz_entry, 6, 1)

        # End Move X,Y
        self.endmove_xy_label = FCLabel('%s:' % _('End move X,Y'))
        self.endmove_xy_label.setToolTip(
            _("End move X,Y position. In format (x,y).\n"
              "If no value is entered then there is no move\n"
              "on X,Y plane at the end of the job.")
        )
        self.endxy_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.endxy_entry.setPlaceholderText(_("X,Y coordinates"))
        self.endxy_entry.setObjectName("e_endxy")

        all_par_grid.addWidget(self.endmove_xy_label, 8, 0)
        all_par_grid.addWidget(self.endxy_entry, 8, 1)

        # Probe depth
        self.pdepth_label = FCLabel('%s:' % _("Probe Z depth"))
        self.pdepth_label.setToolTip(
            _("The maximum depth that the probe is allowed\n"
              "to probe. Negative value, in current units.")
        )

        self.pdepth_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.pdepth_entry.set_precision(self.decimals)
        self.pdepth_entry.set_range(-10000.0000, 10000.0000)
        self.pdepth_entry.setSingleStep(0.1)
        self.pdepth_entry.setObjectName("e_depth_probe")

        all_par_grid.addWidget(self.pdepth_label, 10, 0)
        all_par_grid.addWidget(self.pdepth_entry, 10, 1)

        self.pdepth_label.hide()
        self.pdepth_entry.setVisible(False)

        # Probe feedrate
        self.feedrate_probe_label = FCLabel('%s:' % _("Feedrate Probe"))
        self.feedrate_probe_label.setToolTip(
            _("The feedrate used while the probe is probing.")
        )

        self.feedrate_probe_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.feedrate_probe_entry.set_precision(self.decimals)
        self.feedrate_probe_entry.set_range(0.0, 10000.0000)
        self.feedrate_probe_entry.setSingleStep(0.1)
        self.feedrate_probe_entry.setObjectName("e_fr_probe")

        all_par_grid.addWidget(self.feedrate_probe_label, 12, 0)
        all_par_grid.addWidget(self.feedrate_probe_entry, 12, 1)

        self.feedrate_probe_label.hide()
        self.feedrate_probe_entry.setVisible(False)

        # Preprocessor Excellon selection
        pp_excellon_label = FCLabel('%s:' % _("Preprocessor"))
        pp_excellon_label.setToolTip(
            _("The preprocessor JSON file that dictates\n"
              "Gcode output for Excellon Objects.")
        )
        self.pp_excellon_name_cb = FCComboBox()
        self.pp_excellon_name_cb.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.pp_excellon_name_cb.setObjectName("e_pp")

        all_par_grid.addWidget(pp_excellon_label, 14, 0)
        all_par_grid.addWidget(self.pp_excellon_name_cb, 14, 1)

        # Spot drilling pass: a job option (Advanced level)
        self.spot_cb = FCCheckBox('%s:' % _('Spot drilling'))
        self.spot_cb.setToolTip(
            _("The job starts with an extra pass over all the selected holes with a spot drill\n"
              "(centering): its own tool number (the next free one), a toolchange before it,\n"
              "then the drill tools. Needs the toolchange: without it the pass is left out.\n"
              "Ignored by the laser preprocessors. Peck, multi-depth and dwell at the bottom\n"
              "do not apply to it.")
        )
        self.spot_cb.setObjectName("e_spot")

        self.spot_dia_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.spot_dia_entry.set_precision(self.decimals)
        self.spot_dia_entry.set_range(0.0, 10000.0000)
        self.spot_dia_entry.setSingleStep(0.1)
        self.spot_dia_entry.setToolTip(_("Diameter of the spot drill."))
        self.spot_dia_entry.setObjectName("e_spot_dia")

        all_par_grid.addWidget(self.spot_cb, 16, 0)
        all_par_grid.addWidget(self.spot_dia_entry, 16, 1)

        self.spot_cutz_label = FCLabel('%s:' % _("Spot Cut Z"))
        self.spot_cutz_label.setToolTip(_("Depth of the spot holes. Negative value, in current units."))
        self.spot_cutz_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.spot_cutz_entry.set_precision(self.decimals)
        self.spot_cutz_entry.set_range(-10000.0000, 10000.0000)
        self.spot_cutz_entry.setSingleStep(0.1)
        self.spot_cutz_entry.setObjectName("e_spot_cutz")

        all_par_grid.addWidget(self.spot_cutz_label, 17, 0)
        all_par_grid.addWidget(self.spot_cutz_entry, 17, 1)

        self.spot_feedrate_label = FCLabel('%s:' % _("Spot Feedrate Z"))
        self.spot_feedrate_label.setToolTip(_("Feedrate on the Z axis of the spot holes."))
        self.spot_feedrate_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.spot_feedrate_entry.set_precision(self.decimals)
        self.spot_feedrate_entry.set_range(0.0, 910000.0000)
        self.spot_feedrate_entry.setSingleStep(0.1)
        self.spot_feedrate_entry.setObjectName("e_spot_feedrate")

        all_par_grid.addWidget(self.spot_feedrate_label, 18, 0)
        all_par_grid.addWidget(self.spot_feedrate_entry, 18, 1)

        self.spot_widgets = [self.spot_cb, self.spot_dia_entry, self.spot_cutz_label, self.spot_cutz_entry,
                             self.spot_feedrate_label, self.spot_feedrate_entry]
        self.ois_spot = OptionalInputSection(self.spot_cb, [self.spot_dia_entry, self.spot_cutz_label,
                                                            self.spot_cutz_entry, self.spot_feedrate_label,
                                                            self.spot_feedrate_entry])

        # ------------------------------------------------------------------------------------------------------------
        # ------------------------- EXCLUSION AREAS ------------------------------------------------------------------
        # ------------------------------------------------------------------------------------------------------------

        # Exclusion Areas
        self.exclusion_cb = FCCheckBox('%s' % _("Add exclusion areas"))
        self.exclusion_cb.setToolTip(
            _(
                "Include exclusion areas.\n"
                "In those areas the travel of the tools\n"
                "is forbidden."
            ))
        self.exclusion_cb.setObjectName("e_area_exclusion")

        all_par_grid.addWidget(self.exclusion_cb, 20, 0, 1, 2)

        self.exclusion_frame = QtWidgets.QFrame()
        self.exclusion_frame.setContentsMargins(0, 0, 0, 0)
        all_par_grid.addWidget(self.exclusion_frame, 22, 0, 1, 2)

        self.exclusion_box = QtWidgets.QVBoxLayout()
        self.exclusion_box.setContentsMargins(0, 0, 0, 0)
        self.exclusion_frame.setLayout(self.exclusion_box)

        self.exclusion_table = FCTable()
        self.exclusion_box.addWidget(self.exclusion_table)
        self.exclusion_table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)

        self.exclusion_table.setColumnCount(4)
        self.exclusion_table.setColumnWidth(0, 20)
        self.exclusion_table.setHorizontalHeaderLabels(['#', _('Object'), _('Strategy'), _('Over Z')])

        self.exclusion_table.horizontalHeaderItem(0).setToolTip(_("This is the Area ID."))
        self.exclusion_table.horizontalHeaderItem(1).setToolTip(
            _("Type of the object where the exclusion area was added."))
        self.exclusion_table.horizontalHeaderItem(2).setToolTip(
            _("The strategy used for exclusion area. Go around the exclusion areas or over it."))
        self.exclusion_table.horizontalHeaderItem(3).setToolTip(
            _("If the strategy is to go over the area then this is the height at which the tool will go to avoid the "
              "exclusion area."))

        self.exclusion_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)

        exclud_grid = GLay(v_spacing=5, h_spacing=3)
        self.exclusion_box.addLayout(exclud_grid)

        # Chose Strategy
        self.strategy_label = FCLabel('%s:' % _("Strategy"))
        self.strategy_label.setToolTip(_("The strategy followed when encountering an exclusion area.\n"
                                         "Can be:\n"
                                         "- Over -> when encountering the area, the tool will go to a set height\n"
                                         "- Around -> will avoid the exclusion area by going around the area"))
        self.strategy_radio = RadioSet([{'label': _('Over'), 'value': 'over'},
                                        {'label': _('Around'), 'value': 'around'}])
        self.strategy_radio.setObjectName("e_area_strategy")

        exclud_grid.addWidget(self.strategy_label, 1, 0)
        exclud_grid.addWidget(self.strategy_radio, 1, 1)

        # Over Z
        self.over_z_label = FCLabel('%s:' % _("Over Z"))
        self.over_z_label.setToolTip(_("The height Z to which the tool will rise in order to avoid\n"
                                       "an interdiction area."))
        self.over_z_entry = FCDoubleSpinner()
        self.over_z_entry.set_range(-10000.0000, 10000.0000)
        self.over_z_entry.set_precision(self.decimals)
        self.over_z_entry.setObjectName("e_area_overz")

        exclud_grid.addWidget(self.over_z_label, 2, 0)
        exclud_grid.addWidget(self.over_z_entry, 2, 1)

        # Button Add Area
        self.add_area_button = FCButton(_('Add Area:'))
        self.add_area_button.setToolTip(_("Add an Exclusion Area."))

        # Area Selection shape
        self.area_shape_radio = RadioSet([{'label': _("Square"), 'value': 'square'},
                                          {'label': _("Polygon"), 'value': 'polygon'}])
        self.area_shape_radio.setToolTip(
            _("The kind of selection shape used for area selection.")
        )
        self.area_shape_radio.setObjectName("e_area_shape")

        exclud_grid.addWidget(self.add_area_button, 4, 0)
        exclud_grid.addWidget(self.area_shape_radio, 4, 1)

        h_lay_1 = QtWidgets.QHBoxLayout()
        self.exclusion_box.addLayout(h_lay_1)

        # Button Delete All Areas
        self.delete_area_button = FCButton(_('Delete All'))
        self.delete_area_button.setToolTip(_("Delete all exclusion areas."))

        # Button Delete Selected Areas
        self.delete_sel_area_button = FCButton(_('Delete Selected'))
        self.delete_sel_area_button.setToolTip(_("Delete all exclusion areas that are selected in the table."))

        h_lay_1.addWidget(self.delete_area_button)
        h_lay_1.addWidget(self.delete_sel_area_button)

        self.ois_exclusion_exc = OptionalHideInputSection(self.exclusion_cb, [self.exclusion_frame])
        # -------------------------- EXCLUSION AREAS END -------------------------------------------------------------
        # ------------------------------------------------------------------------------------------------------------

        # Job XY transforms of the drill points: mirror -> offset -> array (job options, Advanced level)
        self.job_offset_label = FCLabel('%s:' % _('Job offset X,Y'))
        self.job_offset_label.setToolTip(
            _("Move all the drill points of the job by this X,Y distance (after the mirror, before the array).\n"
              "Blank: no move. The Excellon object is not changed.")
        )
        self.job_offset_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.job_offset_entry.setPlaceholderText(_("X,Y distance"))
        self.job_offset_entry.setObjectName("e_job_offset")
        all_par_grid.addWidget(self.job_offset_label, 24, 0)
        all_par_grid.addWidget(self.job_offset_entry, 24, 1)

        self.mirror_label = FCLabel('%s:' % _('Job mirror'))
        self.mirror_label.setToolTip(
            _("Mirror all the drill points of the job: No, on the X axis (the Y values flip),\n"
              "on the Y axis (the X values flip) or both. The mirror is done first.")
        )
        self.mirror_radio = RadioSet([{'label': _('No'), 'value': 'no'}, {'label': 'X', 'value': 'x'},
                                      {'label': 'Y', 'value': 'y'}, {'label': 'XY', 'value': 'xy'}])
        self.mirror_radio.setObjectName("e_mirror")
        all_par_grid.addWidget(self.mirror_label, 25, 0)
        all_par_grid.addWidget(self.mirror_radio, 25, 1)

        self.mirror_point_label = FCLabel('%s:' % _('Mirror point X,Y'))
        self.mirror_point_label.setToolTip(
            _("The point the mirror axes pass through.\n"
              "Blank: the center of the bounding box of the selected holes.")
        )
        self.mirror_point_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.mirror_point_entry.setPlaceholderText(_("Bounding box center"))
        self.mirror_point_entry.setObjectName("e_mirror_point")
        all_par_grid.addWidget(self.mirror_point_label, 26, 0)
        all_par_grid.addWidget(self.mirror_point_entry, 26, 1)

        self.array_columns_label = FCLabel('%s:' % _('Array columns'))
        self.array_columns_label.setToolTip(_("Repeat the holes along X this many times. 1 x 1 is no array."))
        self.array_columns_entry = FCSpinner()
        self.array_columns_entry.set_range(1, 1000)
        self.array_columns_entry.setObjectName("e_array_columns")
        all_par_grid.addWidget(self.array_columns_label, 27, 0)
        all_par_grid.addWidget(self.array_columns_entry, 27, 1)

        self.array_rows_label = FCLabel('%s:' % _('Array rows'))
        self.array_rows_label.setToolTip(_("Repeat the holes along Y this many times. 1 x 1 is no array."))
        self.array_rows_entry = FCSpinner()
        self.array_rows_entry.set_range(1, 1000)
        self.array_rows_entry.setObjectName("e_array_rows")
        all_par_grid.addWidget(self.array_rows_label, 28, 0)
        all_par_grid.addWidget(self.array_rows_entry, 28, 1)

        self.array_pitch_label = FCLabel('%s:' % _('Array pitch X,Y'))
        self.array_pitch_label.setToolTip(
            _("The distance between the copies of the array, along X and along Y.\n"
              "The array is made last, after the mirror and the offset.")
        )
        self.array_pitch_entry = NumericalEvalTupleEntry(border_color='#0069A9')
        self.array_pitch_entry.setPlaceholderText(_("X,Y pitch"))
        self.array_pitch_entry.setObjectName("e_array_pitch")
        all_par_grid.addWidget(self.array_pitch_label, 29, 0)
        all_par_grid.addWidget(self.array_pitch_entry, 29, 1)

        self.transform_widgets = [self.job_offset_label, self.job_offset_entry, self.mirror_label, self.mirror_radio,
                                  self.mirror_point_label, self.mirror_point_entry, self.array_columns_label,
                                  self.array_columns_entry, self.array_rows_label, self.array_rows_entry,
                                  self.array_pitch_label, self.array_pitch_entry]

        # separator_line = QtWidgets.QFrame()
        # separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        # separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        # all_par_grid.addWidget(separator_line, 25, 0, 1, 2)

        # Hole selection (job option, Advanced level): all the holes or only those inside the areas drawn on the canvas
        self.holes_label = FCLabel('%s:' % _('Holes'))
        self.holes_label.setToolTip(
            _("Which holes are drilled: All, or only those inside the areas drawn on the canvas (Inside area).\n"
              "The areas are applied before the job mirror, offset and array.")
        )
        self.holes_radio = RadioSet([{'label': _('All'), 'value': 'all'}, {'label': _('Inside area'), 'value': 'area'}])
        self.holes_radio.setObjectName("e_holes_selection")
        all_par_grid.addWidget(self.holes_label, 30, 0)
        all_par_grid.addWidget(self.holes_radio, 30, 1)

        self.hole_area_button = FCButton(_('Add Hole Area:'))
        self.hole_area_button.setToolTip(
            _("Draw an area on the canvas. Only the holes inside the areas are drilled when Holes is Inside area.\n"
              "These areas are not exclusion areas."))
        self.hole_area_shape_radio = RadioSet([{'label': _("Square"), 'value': 'square'},
                                               {'label': _("Polygon"), 'value': 'polygon'}])
        self.hole_area_shape_radio.setToolTip(_("The kind of selection shape used for area selection."))
        all_par_grid.addWidget(self.hole_area_button, 31, 0)
        all_par_grid.addWidget(self.hole_area_shape_radio, 31, 1)

        self.hole_areas_label = FCLabel(_("No hole areas"))
        self.hole_areas_clear_button = FCButton(_('Clear Hole Areas'))
        self.hole_areas_clear_button.setToolTip(_("Delete the areas that select the holes."))
        all_par_grid.addWidget(self.hole_areas_label, 32, 0)
        all_par_grid.addWidget(self.hole_areas_clear_button, 32, 1)

        self.hole_widgets = [self.holes_label, self.holes_radio, self.hole_area_button, self.hole_area_shape_radio,
                             self.hole_areas_label, self.hole_areas_clear_button]

        GLay.set_common_column_size([obj_grid, tool_grid, param_grid, all_par_grid], 0)

        self.generate_cnc_button = FCButton(_('Generate CNCJob object'), bold=True)
        self.generate_cnc_button.setIcon(QtGui.QIcon(self.app.resource_location + '/cnc16.png'))
        self.generate_cnc_button.setToolTip(
            _("Generate the CNC Job.\n"
              "If milling then an additional Geometry object will be created.\n"
              "Add / Select at least one tool in the tool-table.\n"
              "Click the # header to select all, or Ctrl + LMB\n"
              "for custom selection of tools.")
        )
        self.tools_box.addWidget(self.generate_cnc_button)

        self.tools_box.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.tools_box.addWidget(self.reset_button)
        # ############################ FINSIHED GUI ###################################
        # #############################################################################

    def on_pp_changed(self, current_pp, advanced):
        if "toolchange_probe" in current_pp.lower():
            self.pdepth_entry.setVisible(True)
            self.pdepth_label.show()

            self.feedrate_probe_entry.setVisible(True)
            self.feedrate_probe_label.show()
        else:
            self.pdepth_entry.setVisible(False)
            self.pdepth_label.hide()

            self.feedrate_probe_entry.setVisible(False)
            self.feedrate_probe_label.hide()

        if 'marlin' in current_pp.lower():
            self.feedrate_rapid_label.show()
            self.feedrate_rapid_entry.show()
        else:
            self.feedrate_rapid_label.hide()
            self.feedrate_rapid_entry.hide()

        if 'laser' in current_pp.lower():
            self.cutzlabel.hide()
            self.cutz_entry.hide()

            try:
                self.mpass_cb.hide()
                self.maxdepth_entry.hide()
            except AttributeError:
                pass

            if 'laser_z' in current_pp.lower():
                self.travelzlabel.setText('%s:' % _("Focus Z"))
                self.travelzlabel.show()
                self.travelz_entry.show()

                self.endz_label.show()
                self.endz_entry.show()

                # the feedrate Z was hidden by the 'laser' (no Z) preprocessors
                self.frzlabel.show()
                self.feedrate_z_entry.show()
            else:
                self.travelzlabel.hide()
                self.travelz_entry.hide()

                self.endz_label.hide()
                self.endz_entry.hide()

                try:
                    self.frzlabel.hide()
                    self.feedrate_z_entry.hide()
                except AttributeError:
                    pass

            self.dwell_cb.hide()
            self.dwelltime_entry.hide()

            for widget in self.no_laser_drill_widgets:
                widget.hide()
            if advanced:
                self.fplunge_cb.show()
                self.fretract_cb.show()

            self.spindle_label.setText('%s:' % _("Laser Power"))
            self.spindle_label.setToolTip(
                _("The laser power when the laser is cutting.")
            )

            self.las_min_pwr_label.show()
            self.las_min_pwr_entry.show()

            self.laser_turn_on_lbl.show()
            self.laser_turn_on_combo.show()

            try:
                self.tool_offset_label.hide()
                self.offset_entry.hide()
            except AttributeError:
                pass
        else:
            self.cutzlabel.show()
            self.cutz_entry.show()

            # if in Advanced Mode
            if advanced:
                try:
                    self.mpass_cb.show()
                    self.maxdepth_entry.show()
                except AttributeError:
                    pass

            self.travelzlabel.setText('%s:' % _('Travel Z'))
            self.travelzlabel.setToolTip(
                _("Tool height when travelling\n"
                  "across the XY plane.")
            )

            self.travelzlabel.show()
            self.travelz_entry.show()

            self.endz_label.show()
            self.endz_entry.show()

            try:
                self.frzlabel.show()
                self.feedrate_z_entry.show()
            except AttributeError:
                pass

            self.spindle_label.setText('%s:' % _('Spindle speed'))
            self.spindle_label.setToolTip(
                _("Speed of the spindle\n"
                  "in RPM (optional)")
            )

            self.las_min_pwr_label.hide()
            self.las_min_pwr_entry.hide()

            self.laser_turn_on_lbl.hide()
            self.laser_turn_on_combo.hide()

            # if in Advanced Mode
            if advanced:
                self.dwell_cb.show()
                self.dwelltime_entry.show()
                for widget in self.advanced_drill_widgets:
                    widget.show()

                try:
                    self.tool_offset_label.show()
                    self.offset_entry.show()
                except AttributeError:
                    pass
            else:
                # Beginner mode: the advanced controls stay hidden after a preprocessor change
                self.mpass_cb.hide()
                self.maxdepth_entry.hide()
                self.dwell_cb.hide()
                self.dwelltime_entry.hide()
                for widget in self.advanced_drill_widgets:
                    widget.hide()
                self.tool_offset_label.hide()
                self.offset_entry.hide()

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
