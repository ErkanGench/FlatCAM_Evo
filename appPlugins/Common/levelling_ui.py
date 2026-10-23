# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/15/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################
"""The probe-point widgets, shared by the Levelling and the GRBL Sender UIs."""

from PyQt6 import QtWidgets, QtCore

from appGUI.GUIElements import (
    FCLabel, FCButton, FCFrame, GLay, FCCheckBox, RadioSet, FCDoubleSpinner, FCSpinner, FCTable)

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def build_probe_points_ui(ui, app, parent_box, connect_preferences=True):
    """
    Make the probe-point widgets as attributes of `ui` and add them to
    `parent_box` (a QVBoxLayout). After the call `ui` has: al_frame, al_box,
    al_title, show_al_table, al_probe_points_table, plot_probing_pts_cb,
    avoid_exc_holes_cb, avoid_exc_holes_size_label, avoid_exc_holes_size_entry,
    probe_gc_label, probe_tip_dia_entry, ptravelz_entry, pdepth_entry,
    feedrate_probe_entry, al_mode_radio, al_method_lbl, al_method_radio,
    al_columns_entry, al_columns_label, al_rows_entry, al_rows_label,
    al_add_button, import_heights_button, tool_grid, param_grid.

    :param ui:         the UI object (LevelUI or GrblSenderUI); it needs ui.decimals.
    :param app:        the App.
    :param parent_box: the layout that gets al_frame.
    :param connect_preferences: keep the legacy preference hookups unless the controller owns them.
    """
    # Autolevelling
    ui.al_frame = QtWidgets.QFrame()
    ui.al_frame.setContentsMargins(0, 0, 0, 0)
    parent_box.addWidget(ui.al_frame)

    ui.al_box = QtWidgets.QVBoxLayout()
    ui.al_box.setContentsMargins(0, 0, 0, 0)
    ui.al_frame.setLayout(ui.al_box)
    ui.al_frame.setDisabled(True)

    grid0 = GLay(v_spacing=5, h_spacing=3)
    ui.al_box.addLayout(grid0)

    ui.al_title = FCLabel('%s' % _("Probe Points Table"), bold=True)
    ui.al_title.setToolTip(_("Generate GCode that will obtain the height map"))

    ui.show_al_table = FCCheckBox(_("Show"))
    ui.show_al_table.setToolTip(_("Toggle the display of the Probe Points table."))
    ui.show_al_table.setChecked(True)

    hor_lay = QtWidgets.QHBoxLayout()
    hor_lay.addWidget(ui.al_title)
    hor_lay.addStretch()
    hor_lay.addWidget(ui.show_al_table, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

    grid0.addLayout(hor_lay, 0, 0, 1, 2)

    # #############################################################################################################
    # Tool Table Frame
    # #############################################################################################################
    tt_frame = FCFrame()
    ui.al_box.addWidget(tt_frame)

    # Grid Layout
    tool_grid = GLay(v_spacing=5, h_spacing=3, c_stretch=[0, 1])
    tt_frame.setLayout(tool_grid)

    # Probe Points table
    ui.al_probe_points_table = FCTable()
    ui.al_probe_points_table.setColumnCount(3)
    ui.al_probe_points_table.setColumnWidth(0, 20)
    ui.al_probe_points_table.setHorizontalHeaderLabels(['#', _('X-Y Coordinates'), _('Height')])

    tool_grid.addWidget(ui.al_probe_points_table, 0, 0, 1, 2)

    # Plot Probe Points
    ui.plot_probing_pts_cb = FCCheckBox(_("Plot probing points"))
    ui.plot_probing_pts_cb.setToolTip(
        _("Plot the probing points in the table.\n"
          "If a Voronoi method is used then\n"
          "the Voronoi areas are also plotted.")
    )
    tool_grid.addWidget(ui.plot_probing_pts_cb, 2, 0, 1, 2)

    # Avoid Excellon holes
    ui.avoid_exc_holes_cb = FCCheckBox(_("Avoid Excellon holes"))
    ui.avoid_exc_holes_cb.setToolTip(
        _("When active, the user cannot add probe points over a drill hole.")
    )
    tool_grid.addWidget(ui.avoid_exc_holes_cb, 4, 0, 1, 2)

    # Avoid Excellon holes Size
    ui.avoid_exc_holes_size_label = FCLabel('%s:' % _("Avoid Step"))
    ui.avoid_exc_holes_size_label.setToolTip(
        _("The incremental size to move to the side, to avoid an Excellon hole.")
    )

    ui.avoid_exc_holes_size_entry = FCDoubleSpinner()
    ui.avoid_exc_holes_size_entry.set_precision(ui.decimals)
    ui.avoid_exc_holes_size_entry.set_range(0.0001, 99999.0000)

    tool_grid.addWidget(ui.avoid_exc_holes_size_label, 6, 0)
    tool_grid.addWidget(ui.avoid_exc_holes_size_entry, 6, 1, 1, 1)

    # #############################################################################################################
    # ############### Probe GCode Generation ######################################################################
    # #############################################################################################################
    ui.probe_gc_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
    ui.probe_gc_label.setToolTip(
        _("Will create a GCode which will be sent to the controller,\n"
          "either through a file or directly, with the intent to get the height map\n"
          "that is to modify the original GCode to level the cutting height.")
    )
    ui.al_box.addWidget(ui.probe_gc_label)

    tp_frame = FCFrame()
    ui.al_box.addWidget(tp_frame)

    # Grid Layout
    param_grid = GLay(v_spacing=5, h_spacing=3)
    tp_frame.setLayout(param_grid)

    # Probe Diameter
    ui.probe_tip_dia_label = FCLabel('%s:' % _("Probe Tip Dia"))
    ui.probe_tip_dia_label.setToolTip(
        _("The probe tip diameter.")
    )
    ui.probe_tip_dia_entry = FCDoubleSpinner()
    ui.probe_tip_dia_entry.set_precision(ui.decimals)
    ui.probe_tip_dia_entry.set_range(0.0000, 10.0000)

    param_grid.addWidget(ui.probe_tip_dia_label, 0, 0)
    param_grid.addWidget(ui.probe_tip_dia_entry, 0, 1)

    # Travel Z Probe
    ui.ptravelz_label = FCLabel('%s:' % _("Probe Z travel"))
    ui.ptravelz_label.setToolTip(
        _("The safe Z for probe travelling between probe points.")
    )
    ui.ptravelz_entry = FCDoubleSpinner()
    ui.ptravelz_entry.set_precision(ui.decimals)
    ui.ptravelz_entry.set_range(0.0000, 10000.0000)

    param_grid.addWidget(ui.ptravelz_label, 2, 0)
    param_grid.addWidget(ui.ptravelz_entry, 2, 1)

    # Probe depth
    ui.pdepth_label = FCLabel('%s:' % _("Probe Z depth"))
    ui.pdepth_label.setToolTip(
        _("The maximum depth that the probe is allowed\n"
          "to probe. Negative value, in current units.")
    )
    ui.pdepth_entry = FCDoubleSpinner()
    ui.pdepth_entry.set_precision(ui.decimals)
    ui.pdepth_entry.set_range(-910000.0000, 0.0000)

    param_grid.addWidget(ui.pdepth_label, 4, 0)
    param_grid.addWidget(ui.pdepth_entry, 4, 1)

    # Probe feedrate
    ui.feedrate_probe_label = FCLabel('%s:' % _("Probe Feedrate"))
    ui.feedrate_probe_label.setToolTip(
       _("The feedrate used while the probe is probing.")
    )
    ui.feedrate_probe_entry = FCDoubleSpinner()
    ui.feedrate_probe_entry.set_precision(ui.decimals)
    ui.feedrate_probe_entry.set_range(0, 910000.0000)

    param_grid.addWidget(ui.feedrate_probe_label, 6, 0)
    param_grid.addWidget(ui.feedrate_probe_entry, 6, 1)

    separator_line = QtWidgets.QFrame()
    separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    param_grid.addWidget(separator_line, 8, 0, 1, 2)

    # AUTOLEVELL MODE
    al_mode_lbl = FCLabel('%s' % _("Mode"), bold=True)
    al_mode_lbl.setToolTip(_("Choose a mode for height map generation.\n"
                             "- Manual: will pick a selection of probe points by clicking on canvas\n"
                             "- Grid: will automatically generate a grid of probe points"))

    ui.al_mode_radio = RadioSet(
        [
            {'label': _('Manual'), 'value': 'manual'},
            {'label': _('Grid'), 'value': 'grid'}
        ])
    param_grid.addWidget(al_mode_lbl, 10, 0)
    param_grid.addWidget(ui.al_mode_radio, 10, 1)

    # AUTOLEVELL METHOD
    ui.al_method_lbl = FCLabel('%s:' % _("Method"))
    ui.al_method_lbl.setToolTip(_("Choose a method for approximation of heights from autolevelling data.\n"
                                    "- Voronoi: will generate a Voronoi diagram\n"
                                    "- Bilinear: will use bilinear interpolation. Usable only for grid mode.\n"
                                    "- Bicubic: smooth surface through the grid. Needs at least 4 rows and 4 columns."))

    ui.al_method_radio = RadioSet(
        [
            {'label': _('Voronoi'), 'value': 'v'},
            {'label': _('Bilinear'), 'value': 'b'},
            {'label': _('Bicubic'), 'value': 'c'}
        ])
    ui.al_method_lbl.setDisabled(True)
    ui.al_method_radio.setDisabled(True)
    ui.al_method_radio.set_value('v')

    param_grid.addWidget(ui.al_method_lbl, 12, 0)
    param_grid.addWidget(ui.al_method_radio, 12, 1)

    # ## Columns
    ui.al_columns_entry = FCSpinner()
    ui.al_columns_entry.setMinimum(2)

    ui.al_columns_label = FCLabel('%s:' % _("Columns"))
    ui.al_columns_label.setToolTip(
        _("The number of grid columns.")
    )
    param_grid.addWidget(ui.al_columns_label, 14, 0)
    param_grid.addWidget(ui.al_columns_entry, 14, 1)

    # ## Rows
    ui.al_rows_entry = FCSpinner()
    ui.al_rows_entry.setMinimum(2)

    ui.al_rows_label = FCLabel('%s:' % _("Rows"))
    ui.al_rows_label.setToolTip(
        _("The number of grid rows.")
    )
    param_grid.addWidget(ui.al_rows_label, 16, 0)
    param_grid.addWidget(ui.al_rows_entry, 16, 1)

    ui.al_add_button = FCButton(_("Add Probe Points"))
    ui.al_box.addWidget(ui.al_add_button)

    ui.import_heights_button = FCButton(_("Import Height Map"))
    ui.import_heights_button.setToolTip(
        _("Import the file that has the Z heights\n"
          "obtained through probing and then apply this data\n"
          "over the original GCode therefore\n"
          "doing autolevelling.")
    )
    ui.al_box.addWidget(ui.import_heights_button)

    ui.tool_grid = tool_grid
    ui.param_grid = param_grid

    def on_plot_points_changed(state):
        app.options["tools_al_plot_points"] = False if not state else True

    def on_avoid_exc_holes_changed(state):
        app.options["tools_al_avoid_exc_holes"] = False if not state else True

    if connect_preferences:
        ui.plot_probing_pts_cb.stateChanged.connect(on_plot_points_changed)
        ui.avoid_exc_holes_cb.stateChanged.connect(on_avoid_exc_holes_changed)
