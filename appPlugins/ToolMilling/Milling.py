# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     6/15/2020                                      #
# License:  MIT Licence                                    #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCComboBox2, RadioSet, FCDoubleSpinner, FCSpinner, NumericalEvalTupleEntry, FCTable, \
    OptionalInputSection, OptionalHideInputSection

import logging
from copy import deepcopy
import numpy as np
import sys
import math
import traceback
from contextlib import contextmanager

from shapely import LineString, box

import gettext
import appTranslation as fcTranslate
import builtins

from appDatabase import load_tools_database, tools_database_error_message
from defaults import AppDefaults
from camlib import Geometry, grace, deepcopy_keep_geometry
from appHandlers.appHistory import history_of, object_state, SnapshotStep
from appPlugins.ToolMilling.MillingUI import MillingUI
from appPlugins.ToolMilling import MillingGen

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')

# The tool data of a Geometry saved by an older app version keeps its milling settings under older names. FlatCAM 8.994
# uses the name without the 'tools_mill_' prefix (the tool data of real 8.994 projects; FlatCAMGeometry.py of that
# version). FlatCAM Evo before 12.2023 names the probe depth 'tools_mill_z_pdepth' (renamed in 993a195bd).
# modern key -> its older names in the tool data
LEGACY_MILL_DATA_KEYS = {
    'tools_mill_cutz': ('cutz',),
    'tools_mill_vtipdia': ('vtipdia',),
    'tools_mill_vtipangle': ('vtipangle',),
    'tools_mill_multidepth': ('multidepth',),
    'tools_mill_depthperpass': ('depthperpass',),
    'tools_mill_travelz': ('travelz',),
    'tools_mill_toolchange': ('toolchange',),
    'tools_mill_toolchangez': ('toolchangez',),
    'tools_mill_toolchangexy': ('toolchangexy',),
    'tools_mill_startz': ('startz',),
    'tools_mill_endz': ('endz',),
    'tools_mill_endxy': ('endxy',),
    'tools_mill_feedrate': ('feedrate',),
    'tools_mill_feedrate_z': ('feedrate_z',),
    'tools_mill_feedrate_rapid': ('feedrate_rapid',),
    'tools_mill_spindlespeed': ('spindlespeed',),    # a laser preprocessor: the laser power, as now
    'tools_mill_spindledir': ('spindledir',),
    'tools_mill_laser_on': ('spindledir',),     # the laser preprocessors of 8.994 used it: M03 for CW, M04 for CCW
    'tools_mill_dwell': ('dwell',),
    'tools_mill_dwelltime': ('dwelltime',),
    'tools_mill_ppname_g': ('ppname_g',),
    'tools_mill_extracut': ('extracut',),
    'tools_mill_extracut_length': ('extracut_length',),
    'tools_mill_f_plunge': ('f_plunge',),
    'tools_mill_z_p_depth': ('tools_mill_z_pdepth', 'z_pdepth'),
    'tools_mill_feedrate_probe': ('feedrate_probe',),
    'tools_mill_area_exclusion': ('area_exclusion',),
    'tools_mill_area_shape': ('area_shape',),
    'tools_mill_area_strategy': ('area_strategy',),
    'tools_mill_area_overz': ('area_overz',),
    'tools_mill_polish': ('polish',),
    'tools_mill_polish_margin': ('polish_margin',),
    'tools_mill_polish_overlap': ('polish_overlap',),
    'tools_mill_polish_method': ('polish_method',),
    'tools_mill_optimization_type': ('optimization_type',),
    'tools_mill_search_time': ('search_time',),
}

# The older value of these settings in the tool data can be the text of a combo box: the development builds of
# 21-28.10.2020 (0b94eef84 to eb7de1173, before the FlatCAM 8.994 release) saved the polish method as 'Standard', 'Seed'
# or 'Lines' (translated in another interface language); the 8.994 release and FlatCAM Evo save the index. The laser ON
# code comes from the 8.994 spindle direction: the 8.994 GRBL_laser and Z_laser sent M03 for CW, M04 for CCW (its
# multi-geometry job took the direction from the tool, its single-geometry job from the application option). The
# 'tools_mill_spindledir' of FlatCAM Evo before 12.2023 does not give it: the GRBL_laser and Z_laser (GRBL_laser_z) of
# the Evo builds of 12.2020 to 01.2022 (3d83f93d5 to 13ec36e50) still sent M03 or M04 from the spindle direction, those
# of 01.2022 to 12.2023 (13ec36e50 to 993a195bd) M3 for any direction, and their tool data cannot tell them apart. So
# such a tool gets the application laser ON code, also a laser tool saved with CCW in 2021 (it made M04 then).
# modern key -> the modern value of each older text
LEGACY_MILL_DATA_TEXTS = {
    'tools_mill_polish_method': {'standard': 0, 'seed': 1, 'lines': 2},
    'tools_mill_laser_on': {'cw': 'M03', 'ccw': 'M04'},
}

# FlatCAM 8.994 keeps these settings in the tool itself, next to its data. The offset, type and tool_type are combo box
# texts. The 8.994 release saves the type in English; a translated type comes from older versions (before bb2bb7fc2,
# 2020-11-03: 8.993 and older), from a Tools Database entry saved by them, or from the 8.994 polishing (_('Polish')).
# modern key -> (older key, the modern value of each older value; None when the value is the same)
LEGACY_MILL_TOOL_KEYS = {
    'tools_mill_tooldia': ('tooldia', None),
    'tools_mill_offset_value': ('offset_value', None),
    'tools_mill_offset_type': ('offset', {'path': 0, 'in': 1, 'out': 2, 'custom': 3}),
    'tools_mill_job_type': ('type', {'rough': 0, 'finish': 1, 'iso': 2}),
    'tools_mill_tool_shape': ('tool_type', {'c1': 0, 'c2': 1, 'c3': 2, 'c4': 3, 'b': 4, 'v': 5}),
}

# FlatCAM 8.994 preprocessors that have another name now (renamed in baeb4b87e, 13ec36e50 and eb9e7b420)
LEGACY_PREPROCESSOR_NAMES = {'grbl_11': 'GRBL_11', 'line_xyz': 'Line_xyz', 'Z_laser': 'GRBL_laser_z'}


def legacy_choice(value, choices):
    """
    The modern value of an older combo box choice: its English text ('Path', 'Iso', 'C1', 'Standard', 'CW'...; spaces
    and case are ignored, 8.994 sometimes saved them with spaces) or an int that is already a modern index. None when it
    is not recognized (e.g. a translated text).
    """
    if type(value) is int:
        return value if value in choices.values() else None
    return choices.get(str(value).strip().lower())


def legacy_mill_value(tool, key):
    """
    Find the milling setting 'key' that a tool made by an older app version keeps under an older name.

    :param tool:    a tool of a Geometry: {'tooldia': ..., 'data': {...}, ...}
    :param key:     a modern 'tools_mill_*' key
    :return:        (True, a copy of the value; a renamed preprocessor gets its current name, a combo box text its
                    modern value) or (False, None) when the tool has no recognized older setting
    """
    data = tool['data']
    for old_key in LEGACY_MILL_DATA_KEYS.get(key, ()):
        if old_key in data:
            value = deepcopy(data[old_key])
            if key == 'tools_mill_ppname_g' and isinstance(value, str):
                value = LEGACY_PREPROCESSOR_NAMES.get(value, value)
            elif key in LEGACY_MILL_DATA_TEXTS:
                value = legacy_choice(value, LEGACY_MILL_DATA_TEXTS[key])
                if value is None:
                    return False, None
            return True, value
    if key in LEGACY_MILL_TOOL_KEYS:
        old_key, values = LEGACY_MILL_TOOL_KEYS[key]
        if old_key in tool:
            if values is None:
                return True, deepcopy(tool[old_key])
            value = legacy_choice(tool[old_key], values)
            if value is not None:
                return True, value
    return False, None


class HybridGeoExc:
    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        """
        self.tools = {}
        This is a dictionary. Each dict key is associated with a tool used in tools_table_mill_geo. The key is the 
        tool_id of the tools and the value is another dict that will hold the data under the following form:
            {tooluid:   {
                        'tooldia': 1,
                        'data': self.default_tool_data
                        'solid_geometry': []
                        }
            }
        """
        self.obj_options = {}
        self.tools = {}
        self.solid_geometry = []

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        kind = 'geometry'
        for option in self.app.options:
            if option.find(kind + "_") == 0:
                oname = option[len(kind) + 1:]
                self.obj_options[oname] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))
        for option in self.app.options:
            if option.find('tools_mill_') == 0:
                self.obj_options[option] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))
        for option in self.app.options:
            if option.find('tools_') == 0:
                self.obj_options[option] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))

        self.obj_options['xmin'] = 0
        self.obj_options['ymin'] = 0
        self.obj_options['xmax'] = 0
        self.obj_options['ymax'] = 0

        self.multigeo = True
        self.multitool = True


@contextmanager
def _history_step(tool, label):
    """
    1 Undo step with the state of the target object of the plugin before and after the body (none if the body changed
    nothing). A step recorded inside another step is part of it. Only the handlers of a user action use it: building
    the UI never records.
    """
    obj = tool.target_obj
    history = history_of(tool.app)
    nested = getattr(tool, '_history_depth', 0)
    if obj is None or nested or not hasattr(obj, 'history_uid') or not history.is_recording():
        yield
        return
    tool._history_depth = 1
    before = object_state(obj)
    try:
        yield
    finally:
        tool._history_depth = 0
        after = object_state(obj)
        try:
            same = before == after
        except Exception:
            same = False
        if not same:
            history.push(SnapshotStep(_("Milling") + ': ' + label, [(obj.history_uid, before, after)]))


class ToolMilling(Geometry, AppTool):
    build_ui_sig = QtCore.pyqtSignal()
    launch_job = QtCore.pyqtSignal()

    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        AppTool.__init__(self, app)
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        Geometry.__init__(
            self,
            geo_steps_per_circle=int(self.app.options.get(
                "excellon_circle_steps",
                app_defaults.get("excellon_circle_steps", AppDefaults.factory_defaults.get("excellon_circle_steps")))),
            app=app)

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = None
        self.pluginName = _("Milling")

        # #############################################################################
        # ########################## VARIABLES ########################################
        # #############################################################################
        self.units = ''
        self.tooluid = 0

        # dict that holds the object names and the option name
        # the key is the object name (defines in ObjectUI) for each UI element that is a parameter
        # particular for a tool and the value is the actual name of the option that the UI element is changing
        self.name2option = {}

        # store here the default data for Geometry Data
        self.default_data = {}

        # store here the Geometry tools selected in the Geo Tools Table
        self.sel_tools = {}

        self.obj_name = ""
        self.target_obj = None

        self.first_click = False
        self.cursor_pos = None
        self.mouse_is_dragging = False

        # store here the points for the "Polygon" area selection shape
        self.points = []

        # variable to store the total amount of drills per job
        self.tot_drill_cnt = 0
        self.tool_row = 0

        # variable to store the total amount of slots per job
        self.tot_slot_cnt = 0
        self.tool_row_slots = 0

        # variable to store the current row in the (geo) tools table
        self.current_row = -1

        # variable to store the distance travelled
        self.travel_distance = 0.0

        self.grid_status_memory = self.app.ui.grid_snap_btn.isChecked()

        # store here the state of the exclusion checkbox state to be restored after building the UI
        # TODO add this in the self.app.options dict and in Preferences
        self.exclusion_area_cb_is_checked = False

        # store here solid_geometry when there are tool with isolation job
        self.solid_geometry = []

        self.circle_steps = int(self.app.options.get(
            "geometry_circle_steps",
            app_defaults.get("geometry_circle_steps", AppDefaults.factory_defaults.get("geometry_circle_steps"))))

        self.tooldia = None

        # multiprocessing
        self.pool = self.app.pool
        self.results = []

        # disconnect flags
        self.area_sel_disconnect_flag = False
        self.poly_sel_disconnect_flag = False

        # updated in the self.set_tool_ui()
        self.form_fields = {}
        self.general_form_fields = {}

        self.old_tool_dia = None
        self.poly_drawn = False

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+M', **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolMilling()")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            # if the Tool Tab is hidden display it, else hide it but only if the objectName is the same
            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
            # show the Tab
            if not found_idx:
                try:
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                except RuntimeError:
                    self.app.ui.plugin_tab = QtWidgets.QWidget()
                    self.app.ui.plugin_tab.setObjectName("plugin_tab")
                    self.app.ui.plugin_tab_layout = QtWidgets.QVBoxLayout(self.app.ui.plugin_tab)
                    self.app.ui.plugin_tab_layout.setContentsMargins(2, 2, 2, 2)

                    self.app.ui.plugin_scroll_area = VerticalScrollArea()
                    self.app.ui.plugin_tab_layout.addWidget(self.app.ui.plugin_scroll_area)
                    self.app.ui.notebook.addTab(self.app.ui.plugin_tab, _("Plugin"))
                # focus on Tool Tab
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    # if the Tool Tab is not focused, focus on it
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        # focus on Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        # else remove the Tool Tab
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)

                        # if there are no objects loaded in the app then hide the Notebook widget
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        self.set_tool_ui()

        super().run()

        # reset those objects on a new run
        self.target_obj = None
        self.obj_name = ''

        self.build_ui()

        # all the tools are selected by default
        self.ui.tools_table_mill_exc.selectAll()

        self.app.ui.notebook.setTabText(2, _("Milling"))

    def connect_signals(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        self.build_ui_sig.connect(self.build_ui)

        self.ui.level.toggled.connect(self.on_level_changed)

        # add Tool
        self.ui.search_and_add_btn.clicked.connect(lambda: self.on_tool_add())
        self.ui.deltool_btn.clicked.connect(lambda: self.on_tool_delete())
        self.ui.addtool_from_db_btn.clicked.connect(self.on_tool_add_from_db_clicked)

        self.ui.target_radio.activated_custom.connect(self.on_target_changed)
        self.ui.job_type_combo.currentIndexChanged.connect(self.on_job_changed)
        self.ui.offset_type_combo.currentIndexChanged.connect(self.on_offset_type_changed)
        self.ui.pp_geo_name_cb.activated.connect(self.on_pp_changed)

        # V tool shape params changed
        self.ui.tipdia_entry.valueChanged.connect(lambda: self.on_update_cutz())
        self.ui.tipangle_entry.valueChanged.connect(lambda: self.on_update_cutz())

        self.ui.apply_param_to_all.clicked.connect(self.on_apply_param_to_all_clicked)
        self.ui.tools_table_mill_exc.drag_drop_sig.connect(self.on_exc_rebuild_ui)

        # Exclusion areas signals
        self.ui.exclusion_table.horizontalHeader().sectionClicked.connect(self.exclusion_table_toggle_all)
        self.ui.exclusion_table.lost_focus.connect(self.clear_selection)
        self.ui.exclusion_table.itemClicked.connect(self.draw_sel_shape)
        self.ui.add_area_button.clicked.connect(self.on_add_area_click)
        self.ui.delete_area_button.clicked.connect(self.on_clear_area_click)
        self.ui.delete_sel_area_button.clicked.connect(self.on_delete_sel_areas)
        self.ui.strategy_radio.activated_custom.connect(self.on_strategy)

        # Geo Tools Table signals
        self.ui.tools_table_mill_geo.drag_drop_sig.connect(self.on_geo_rebuild_ui)
        self.ui.tools_table_mill_geo.horizontalHeader().sectionClicked.connect(self.on_toggle_all_rows)

        # Generate CNCJob
        self.launch_job.connect(self.generate_cnc_job_handler)
        self.ui.generate_cnc_button.clicked.connect(self.on_generate_cncjob_click)

        # Reset Tool
        self.ui.reset_button.clicked.connect(self.set_tool_ui)
        # Cleanup on Graceful exit (CTRL+ALT+X combo key)
        self.app.cleanup.connect(self.set_tool_ui)

    def disconnect_signals(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        try:
            self.build_ui_sig.disconnect()
        except (TypeError, AttributeError):
            pass

        try:
            self.ui.level.toggled.disconnect()
        except (TypeError, AttributeError):
            pass

        # add Tool
        try:
            self.ui.search_and_add_btn.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.deltool_btn.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.addtool_from_db_btn.clicked.disconnect()
        except (TypeError, AttributeError):
            pass

        try:
            self.ui.target_radio.activated_custom.disconnect()
        except (TypeError, AttributeError):
            pass

        try:
            self.ui.job_type_combo.currentIndexChanged.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.offset_type_combo.currentIndexChanged.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.pp_geo_name_cb.activated.disconnect()
        except (TypeError, AttributeError):
            pass

        # V tool shape params changed
        try:
            self.ui.tipdia_entry.valueChanged.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tipangle_entry.valueChanged.disconnect()
        except (TypeError, AttributeError):
            pass

        try:
            self.ui.apply_param_to_all.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tools_table_mill_exc.drag_drop_sig.disconnect()
        except (TypeError, AttributeError):
            pass

        # Exclusion areas signals
        try:
            self.ui.exclusion_table.horizontalHeader().sectionClicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.exclusion_table.lost_focus.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.exclusion_table.itemClicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.add_area_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.delete_area_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.delete_sel_area_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.strategy_radio.activated_custom.disconnect()
        except (TypeError, AttributeError):
            pass

        # Geo Tools Table signals
        try:
            self.ui.tools_table_mill_geo.drag_drop_sig.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tools_table_mill_geo.horizontalHeader().sectionClicked.disconnect()
        except (TypeError, AttributeError):
            pass

        # Generate CNCJob
        try:
            self.launch_job.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.generate_cnc_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass

        # Reset Tool
        try:
            self.ui.reset_button.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        # Cleanup on Graceful exit (CTRL+ALT+X combo key)
        try:
            self.app.cleanup.disconnect()
        except (TypeError, AttributeError):
            pass

    def set_context_menu(self):

        # #############################################################################################################
        # ############################### TOOLS TABLE context menu ####################################################
        # #############################################################################################################
        self.ui.tools_table_mill_geo.setupContextMenu()
        self.ui.tools_table_mill_geo.addContextMenu(
            _("Pick from DB"), self.on_tool_add_from_db_clicked,
            icon=QtGui.QIcon(self.app.resource_location + "/plus16.png"))
        self.ui.tools_table_mill_geo.addContextMenu(
            _("Copy"), self.on_tool_copy,
            icon=QtGui.QIcon(self.app.resource_location + "/copy16.png"))
        self.ui.tools_table_mill_geo.addContextMenu(
            _("Delete"), lambda: self.on_tool_delete(all_tools=None),
            icon=QtGui.QIcon(self.app.resource_location + "/trash16.png"))

        # #############################################################################################################
        # ############################## EXCLUSION TABLE context menu #################################################
        # #############################################################################################################
        self.ui.exclusion_table.setupContextMenu()
        self.ui.exclusion_table.addContextMenu(
            '%s %s' % (_("Copy"), _("coords")), self.on_copy_exclusion_area_coords,
            icon=QtGui.QIcon(self.app.resource_location + "/copy16.png")
        )
        self.ui.exclusion_table.addContextMenu(
            _("Delete"), self.on_delete_sel_areas, icon=QtGui.QIcon(self.app.resource_location + "/trash16.png")
        )

    def unset_context_menu(self):
        self.ui.tools_table_mill_geo.removeContextMenu()

    def init_ui(self):
        self.ui = MillingUI(layout=self.layout, app=self.app, name=self.pluginName)
        self.add_object_creation_controls()

    def set_tool_ui(self):
        self.units = self.app.app_units.upper()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.old_tool_dia = self.app.options.get(
            "tools_iso_newdia", app_defaults.get("tools_iso_newdia", AppDefaults.factory_defaults.get("tools_iso_newdia")))

        self.obj_name = ""
        self.target_obj = None

        self.first_click = False
        self.cursor_pos = None
        self.mouse_is_dragging = False

        self.clear_ui(self.layout)
        self.init_ui()

        self.unset_context_menu()
        self.set_context_menu()

        self.disconnect_signals()
        self.connect_signals()

        # try to select in the Target combobox the active object
        selected_obj = self.app.collection.get_active()
        try:

            if not selected_obj:
                self.ui.target_radio.set_value('geo')
                self.ui.object_combo.setCurrentIndex(0)
            else:
                if selected_obj.kind == 'excellon':
                    self.ui.target_radio.set_value('exc')
                    self.ui.object_combo.set_value(selected_obj.obj_options['name'])
                elif selected_obj.kind == 'geometry':
                    self.ui.target_radio.set_value('geo')
                    self.ui.object_combo.set_value(selected_obj.obj_options['name'])
                else:
                    self.ui.target_radio.set_value('geo')
                    self.ui.object_combo.setCurrentIndex(0)

        except Exception as err:
            self.app.log.error("ToolMilling.set_tool_ui() --> %s" % str(err))

        # Update the GUI data holding structures
        self.form_fields = {
            # Excellon properties
            "tools_mill_milling_type": self.ui.milling_type_radio,
            "tools_mill_milling_dia": self.ui.mill_dia_entry,
            "tools_mill_milling_overlap": self.ui.overlap_entry,
            "tools_mill_milling_connect": self.ui.connect_cb,

            # Geometry properties
            # "tools_mill_tooldia": self.ui.addtool_entry,
            "tools_mill_offset_type": self.ui.offset_type_combo,
            "tools_mill_offset_value": self.ui.offset_entry,

            "tools_mill_tool_shape": self.ui.tool_shape_combo,
            "tools_mill_job_type": self.ui.job_type_combo,
            "tools_mill_polish_margin": self.ui.polish_margin_entry,
            "tools_mill_polish_overlap": self.ui.polish_over_entry,
            "tools_mill_polish_method": self.ui.polish_method_combo,

            "tools_mill_vtipdia": self.ui.tipdia_entry,
            "tools_mill_vtipangle": self.ui.tipangle_entry,

            "tools_mill_cutz": self.ui.cutz_entry,
            "tools_mill_multidepth": self.ui.mpass_cb,
            "tools_mill_depthperpass": self.ui.maxdepth_entry,

            "tools_mill_travelz": self.ui.travelz_entry,
            "tools_mill_feedrate": self.ui.xyfeedrate_entry,
            "tools_mill_feedrate_z": self.ui.feedrate_z_entry,
            "tools_mill_feedrate_rapid": self.ui.feedrate_rapid_entry,

            "tools_mill_extracut": self.ui.extracut_cb,
            "tools_mill_extracut_length": self.ui.e_cut_entry,

            "tools_mill_spindlespeed": self.ui.spindlespeed_entry,
            "tools_mill_dwell": self.ui.dwell_cb,
            "tools_mill_dwelltime": self.ui.dwelltime_entry,
            "tools_mill_min_power": self.ui.las_min_pwr_entry,
            "tools_mill_laser_on": self.ui.laser_turn_on_combo
        }

        self.general_form_fields = {
            "tools_mill_toolchange": self.ui.toolchange_cb,
            "tools_mill_toolchangez": self.ui.toolchangez_entry,
            "tools_mill_toolchangexy": self.ui.toolchangexy_entry,

            "tools_mill_endz": self.ui.endz_entry,
            "tools_mill_endxy": self.ui.endxy_entry,

            "tools_mill_z_p_depth": self.ui.pdepth_entry,
            "tools_mill_feedrate_probe": self.ui.feedrate_probe_entry,
            "tools_mill_ppname_g": self.ui.pp_geo_name_cb,
            "seg_x":    self.ui.seg_x_entry,
            "seg_y":    self.ui.seg_y_entry,

            # "gcode_type": self.ui.excellon_gcode_type_radio,
            "tools_mill_area_exclusion": self.ui.exclusion_cb,
            "tools_mill_area_shape": self.ui.area_shape_radio,
            "tools_mill_area_strategy": self.ui.strategy_radio,
            "tools_mill_area_overz": self.ui.over_z_entry,
        }

        self.name2option = {
            "milling_type":     "tools_mill_milling_type",
            "milling_dia":      "tools_mill_milling_dia",
            "milling_overlap": "tools_mill_milling_overlap",
            "milling_connect": "tools_mill_milling_connect",

            "mill_offset_type": "tools_mill_offset_type",
            "mill_offset":      "tools_mill_offset_value",

            "mill_tool_shape":   "tools_mill_tool_shape",
            "mill_job_type":       "tools_mill_job_type",

            "mill_polish_margin":   "tools_mill_polish_margin",
            "mill_polish_overlap":          "tools_mill_polish_overlap",
            "mill_polish_method":      "tools_mill_polish_method",

            "mill_tipdia":         "tools_mill_vtipdia",
            "mill_tipangle":    "tools_mill_vtipangle",

            "mill_cutz":    "tools_mill_cutz",
            "mill_multidepth":       "tools_mill_multidepth",
            "mill_depthperpass":       "tools_mill_depthperpass",

            "mill_travelz": "tools_mill_travelz",
            "mill_feedratexy": "tools_mill_feedrate",
            "mill_feedratez": "tools_mill_feedrate_z",
            "mill_fr_rapid": "tools_mill_feedrate_rapid",

            "mill_extracut": "tools_mill_extracut",
            "mill_extracut_length": "tools_mill_extracut_length",

            "mill_spindlespeed": "tools_mill_spindlespeed",
            "mill_dwell": "tools_mill_dwell",
            "mill_dwelltime": "tools_mill_dwelltime",
            "mill_minpower": "tools_mill_min_power",
            "mill_laser_turn_on": "tools_mill_laser_on",

            # General Parameters
            "mill_toolchange": "tools_mill_toolchange",
            "mill_toolchangez": "tools_mill_toolchangez",
            "mill_toolchangexy": "tools_mill_toolchangexy",

            "mill_endz": "tools_mill_endz",
            "mill_endxy": "tools_mill_endxy",

            "mill_depth_probe": "tools_mill_z_p_depth",
            "mill_fr_probe": "tools_mill_feedrate_probe",
            "mill_ppname_g": "tools_mill_ppname_g",
            "mill_seg_x":    "seg_x",
            "mill_seg_y":    "seg_y",

            "mill_exclusion": "tools_mill_area_exclusion",
            "mill_area_shape": "tools_mill_area_shape",
            "mill_strategy": "tools_mill_area_strategy",
            "mill_overz": "tools_mill_area_overz",
        }

        # reset the Geometry preprocessor combo
        self.ui.pp_geo_name_cb.clear()
        # populate Geometry (milling) preprocessor combobox list
        for name in list(self.app.preprocessors.keys()):
            self.ui.pp_geo_name_cb.addItem(name)
        # and add ToolTips (useful when names are too long)
        for it in range(self.ui.pp_geo_name_cb.count()):
            self.ui.pp_geo_name_cb.setItemData(it, self.ui.pp_geo_name_cb.itemText(it),
                                               QtCore.Qt.ItemDataRole.ToolTipRole)

        # Fill form fields
        self.to_form()

        self.ui.tools_frame.show()

        self.ui.order_combo.set_value(self.app.options.get(
            "tools_drill_tool_order",
            app_defaults.get("tools_drill_tool_order", AppDefaults.factory_defaults.get("tools_drill_tool_order"))))
        self.ui.milling_type_radio.set_value(self.app.options.get(
            "tools_mill_milling_type",
            app_defaults.get("tools_mill_milling_type", AppDefaults.factory_defaults.get("tools_mill_milling_type"))))

        # init the working variables
        self.default_data.clear()
        kind = 'geometry'
        for option in self.app.options:
            if option.find(kind + "_") == 0:
                oname = option[len(kind) + 1:]
                self.default_data[oname] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))

            if option.find('tools_') == 0:
                self.default_data[option] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))

        # fill in self.default_data values from self.options
        for opt_key, opt_val in self.app.options.items():
            if opt_key.find('geometry_') == 0:
                oname = opt_key[len('geometry_'):]
                self.default_data[oname] = deepcopy(opt_val)
        for opt_key, opt_val in self.app.options.items():
            if opt_key.find('tools_') == 0:
                self.default_data[opt_key] = deepcopy(opt_val)

        # ########################################
        # #######3 TEMP SETTINGS #################
        # ########################################

        try:
            self.ui.addtool_entry.set_value(selected_obj.obj_options["tools_mill_tooldia"])
        except AttributeError:
            self.ui.addtool_entry.set_value(self.app.options.get(
                "tools_mill_tooldia",
                app_defaults.get("tools_mill_tooldia", AppDefaults.factory_defaults.get("tools_mill_tooldia"))))

        self.on_object_changed()
        if self.target_obj:
            self.build_ui()

        try:
            self.ui.object_combo.currentIndexChanged.disconnect()
        except (AttributeError, TypeError):
            pass
        self.ui.object_combo.currentIndexChanged.connect(self.on_object_changed)

        self.ui.offset_type_combo.set_value(0)  # 'Path'

        # handle the Plot checkbox
        self.plot_cb_handler()

        # Show/Hide Advanced Options
        app_mode = self.app.options.get(
            "global_app_level", app_defaults.get("global_app_level", AppDefaults.factory_defaults.get("global_app_level")))
        self.change_level(app_mode)

        self.ui.tools_table_mill_geo.drag_drop = True

    def plot_cb_handler(self):
        # load the Milling object
        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return

        try:
            self.ui.plot_cb.stateChanged.disconnect()
        except (AttributeError, TypeError):
            pass

        self.ui.plot_cb.stateChanged.connect(self.on_plot_clicked)
        if self.target_obj is not None:
            self.ui.plot_cb.set_value(self.target_obj.obj_options['plot'])

    def on_plot_clicked(self, state):
        if self.target_obj:
            self.target_obj.obj_options['plot'] = True if state else False

    def change_level(self, level):
        """

        :param level:   application level: either 'b' or 'a'
        :type level:    str
        :return:
        """

        if level == 'a':
            self.ui.level.setChecked(True)
        else:
            self.ui.level.setChecked(False)
        self.on_level_changed(self.ui.level.isChecked())

    def on_level_changed(self, checked):

        self.target_obj = self.app.collection.get_by_name(self.ui.object_combo.get_value())
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        if not checked:
            self.ui.level.setText('%s' % _('Beginner'))
            self.ui.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)

            # Add Tool section
            self.ui.add_tool_frame.hide()

            # Tool parameters section
            if self.ui.target_radio.get_value() == 'geo':
                if self.target_obj:
                    for tool in self.target_obj.tools:
                        tool_data = self.target_obj.tools[tool]['data']

                        tool_data['tools_mill_offset_type'] = 0  # 'Path'
                        tool_data['tools_mill_offset_value'] = 0.0
                        tool_data['tools_mill_job_type'] = 0    # _('Roughing')

                        # we made the decision here what to do with the hidden parameters
                        # some will disable some of the hidden features but other are set by
                        # other plugins so, we hide them, but we do not disable (like the `multidepth`)
                        # tool_data['tools_mill_multidepth'] = False
                        tool_data['tools_mill_extracut'] = self.app.options.get(
                            "tools_mill_extracut",
                            app_defaults.get("tools_mill_extracut", AppDefaults.factory_defaults.get("tools_mill_extracut")))
                        tool_data['tools_mill_dwell'] = self.app.options.get(
                            "tools_mill_dwell",
                            app_defaults.get("tools_mill_dwell", AppDefaults.factory_defaults.get("tools_mill_dwell")))
                        tool_data['tools_mill_area_exclusion'] = False

                self.ui.offset_type_lbl.hide()
                self.ui.offset_type_combo.hide()
                self.ui.offset_label.hide()
                self.ui.offset_entry.hide()
                self.ui.offset_type_lbl.hide()
                self.ui.offset_separator_line.hide()
                self.ui.offset_type_lbl.hide()

                self.ui.job_type_lbl.hide()
                self.ui.job_type_combo.hide()
                self.ui.job_separator_line.hide()

                self.ui.mpass_cb.hide()
                self.ui.maxdepth_entry.hide()

                self.ui.extracut_cb.hide()
                self.ui.e_cut_entry.hide()

                # self.ui.dwell_cb.hide()
                # self.ui.dwelltime_entry.hide()

                self.ui.endmove_xy_label.hide()
                self.ui.endxy_entry.hide()

                self.ui.exclusion_cb.hide()

            # All param section
            self.ui.apply_param_to_all.hide()

            # Context Menu section
            self.ui.tools_table_mill_geo.removeContextMenu()
        else:
            self.ui.level.setText('%s' % _('Advanced'))
            self.ui.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)

            # Add Tool section
            self.ui.add_tool_frame.show()

            # Tool parameters section
            if self.ui.target_radio.get_value() == 'geo':
                if self.target_obj:
                    app_defaults = self.target_obj.obj_options
                    for tool in self.target_obj.tools:
                        tool_data = self.target_obj.tools[tool]['data']

                        tool_data['tools_mill_offset_type'] = app_defaults['tools_mill_offset_type']
                        tool_data['tools_mill_offset_value'] = app_defaults['tools_mill_offset_value']
                        tool_data['tools_mill_job_type'] = app_defaults['tools_mill_job_type']

                        # we made the decision here what to do with the hidden parameters
                        # some will disable some of the hidden features but other are set by
                        # other plugins so, we hide them but, we do not disable (like the `multidepth`)
                        # tool_data['tools_mill_multidepth'] = app_defaults['tools_mill_multidepth']
                        tool_data['tools_mill_extracut'] = app_defaults['tools_mill_extracut']
                        tool_data['tools_mill_dwell'] = app_defaults['tools_mill_dwell']
                        tool_data['tools_mill_area_exclusion'] = app_defaults['tools_mill_area_exclusion']

                self.ui.offset_type_lbl.show()
                self.ui.offset_type_combo.show()
                if self.ui.offset_type_combo.get_value() == 3:  # _("Custom")
                    self.ui.offset_label.show()
                    self.ui.offset_entry.show()
                self.ui.offset_type_lbl.show()
                self.ui.offset_separator_line.show()
                self.ui.offset_type_lbl.show()

                self.ui.job_type_lbl.show()
                self.ui.job_type_combo.show()
                self.ui.job_separator_line.show()

                self.ui.mpass_cb.show()
                self.ui.maxdepth_entry.show()

                self.ui.extracut_cb.show()
                self.ui.e_cut_entry.show()

                self.ui.dwell_cb.show()
                self.ui.dwelltime_entry.show()

                self.ui.endmove_xy_label.show()
                self.ui.endxy_entry.show()

                self.ui.exclusion_cb.show()

            # All param section
            self.ui.apply_param_to_all.show()

            # Context Menu section
            self.ui.tools_table_mill_geo.setupContextMenu()

        # update the changes in UI depending on the selected preprocessor in Preferences
        # after this moment all the changes in the Posprocessor combo will be handled by the activated signal of the
        # pp combobox
        self.on_pp_changed()

    def on_exc_rebuild_ui(self):
        with _history_step(self, _("Reorder tools")):
            ToolMilling._exc_rebuild_ui(self)

    def _exc_rebuild_ui(self):
        # read the table tools uid
        current_uid_list = []
        # we have (n+2) rows because there are 'n' tools, each a row, plus the last 2 rows for totals.
        for row in range(self.ui.tools_table_mill_exc.rowCount() - 2):
            uid = int(self.ui.tools_table_mill_exc.item(row, 3).text())
            current_uid_list.append(uid)

        new_tools = {}
        new_uid = 1

        for current_uid in current_uid_list:
            new_tools[new_uid] = deepcopy(self.target_obj.tools[current_uid])
            new_uid += 1

        self.target_obj.tools = new_tools

        # the tools table changed therefore we need to rebuild it
        QtCore.QTimer.singleShot(20, self.build_ui)

    def on_geo_rebuild_ui(self):
        # read the table tools uid
        current_uid_list = []
        for row in range(self.ui.tools_table_mill_geo.rowCount()):
            uid = int(self.ui.tools_table_mill_geo.item(row, 3).text())
            current_uid_list.append(uid)

        new_tools = {}
        new_uid = 1

        try:
            for current_uid in current_uid_list:
                new_tools[new_uid] = deepcopy(self.tools[current_uid])
                new_uid += 1
        except Exception as err:
            self.app.log.error("ToolMilling.on_geo_rebuild_ui() -> %s" % str(err))
            return

        self.tools = new_tools

        # the tools table changed therefore we need to reconnect the signals to the cellWidgets
        self.ui_disconnect()
        self.ui_connect()

    def build_ui(self):
        self.ui_disconnect()

        # load the Milling object
        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception as err:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            self.app.log.error("ToolMilling.build_ui() getting the object --> %s" % str(err))
            self.ui_disconnect()
            self.ui_connect()
            return

        # build the UI
        try:
            if self.ui.target_radio.get_value() == 'geo':
                self.build_ui_mill()
            else:
                self.build_ui_exc()
        except Exception as err:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Could not build the Plugin UI"))
            self.app.log.error("ToolMilling.build_ui() building the UI --> %s" % str(err))
            self.ui_connect()
            return

        # Build Exclusion Areas section
        self.ui_disconnect()
        e_len = len(self.app.exc_areas.exclusion_areas_storage)
        self.ui.exclusion_table.setRowCount(e_len)

        area_id = 0

        for area in range(e_len):
            area_id += 1

            area_dict = self.app.exc_areas.exclusion_areas_storage[area]

            # --------------------  ID  -------------------------------
            area_id_item = QtWidgets.QTableWidgetItem('%d' % int(area_id))
            area_id_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.ui.exclusion_table.setItem(area, 0, area_id_item)  # Area id

            # --------------------  Object Type  ----------------------
            object_item = QtWidgets.QTableWidgetItem('%s' % area_dict["obj_type"])
            object_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.ui.exclusion_table.setItem(area, 1, object_item)  # Origin Object

            # --------------------  Strategy  -------------------------
            strategy_item = FCComboBox2(policy=False)
            strategy_item.addItems([_("Around"), _("Over")])
            idx = 0 if area_dict["strategy"] == 'around' else 1
            # protection against having this translated or loading a project with translated values
            if idx == -1:
                strategy_item.setCurrentIndex(0)
            else:
                strategy_item.setCurrentIndex(idx)
            self.ui.exclusion_table.setCellWidget(area, 2, strategy_item)  # Strategy

            # --------------------  Over Z  ---------------------------
            overz_item = QtWidgets.QTableWidgetItem('%s' % area_dict["overz"])
            overz_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.ui.exclusion_table.setItem(area, 3, overz_item)  # Over Z

        # make the Overz column editable
        for row in range(e_len):
            self.ui.exclusion_table.item(row, 3).setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable |
                                                          QtCore.Qt.ItemFlag.ItemIsEditable |
                                                          QtCore.Qt.ItemFlag.ItemIsEnabled)

        self.ui.exclusion_table.resizeColumnsToContents()
        self.ui.exclusion_table.resizeRowsToContents()

        area_vheader = self.ui.exclusion_table.verticalHeader()
        area_vheader.hide()
        self.ui.exclusion_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        area_hheader = self.ui.exclusion_table.horizontalHeader()
        area_hheader.setMinimumSectionSize(10)
        area_hheader.setDefaultSectionSize(70)

        area_hheader.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        area_hheader.resizeSection(0, 20)
        area_hheader.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        area_hheader.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        area_hheader.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        # area_hheader.setStretchLastSection(True)
        self.ui.exclusion_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.ui.exclusion_table.setColumnWidth(0, 20)

        self.ui.exclusion_table.setMinimumHeight(self.ui.exclusion_table.getHeight())
        self.ui.exclusion_table.setMaximumHeight(self.ui.exclusion_table.getHeight())

        self.ui_connect()

        # set the text on tool_data_label after loading the object
        sel_rows = set()
        sel_items = self.ui.tools_table_mill_exc.selectedItems()
        for it in sel_items:
            sel_rows.add(it.row())
        if len(sel_rows) > 1:
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("Multiple Tools"))
            )

    def build_ui_mill(self):
        self.units = self.app.app_units

        if self.target_obj:
            self.ui.param_frame.setDisabled(False)

            tools_dict = self.target_obj.tools

        else:
            tools_dict = {}

        row_idx = 0

        n = len(tools_dict)
        self.ui.tools_table_mill_geo.setRowCount(n)

        for tooluid_key, tooluid_value in tools_dict.items():

            # -------------------- ID ------------------------------------------ #
            tool_id = QtWidgets.QTableWidgetItem('%d' % int(row_idx + 1))
            tool_id.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled |
                             QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_geo.setItem(row_idx, 0, tool_id)  # Tool name/id

            # -------------------- DIAMETER ------------------------------------- #
            dia_item = QtWidgets.QTableWidgetItem('%.*f' % (self.decimals, float(tooluid_value['tooldia'])))
            dia_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled |
                              QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_geo.setItem(row_idx, 1, dia_item)  # Diameter

            # -------------------- TOOL TYPE ------------------------------------- #
            # tool_type_item = FCComboBox(policy=False)
            # for item in ["C1", "C2", "C3", "C4", "B", "V", "L"]:
            #     tool_type_item.addItem(item)
            # idx = tool_type_item.findText(tooluid_value['data']['tools_mill_tool_type'])
            # # protection against having this translated or loading a project with translated values
            # if idx == -1:
            #     tool_type_item.setCurrentIndex(0)
            # else:
            #     tool_type_item.setCurrentIndex(idx)
            # self.ui.tools_table_mill_geo.setCellWidget(row_idx, 2, tool_type_item)

            # -------------------- TOOL UID   ------------------------------------- #
            tool_uid_item = QtWidgets.QTableWidgetItem(str(tooluid_key))
            # ## REMEMBER: THIS COLUMN IS HIDDEN IN OBJECTUI.PY ###
            self.ui.tools_table_mill_geo.setItem(row_idx, 3, tool_uid_item)  # Tool unique ID

            # -------------------- PLOT       ------------------------------------- #
            empty_plot_item = QtWidgets.QTableWidgetItem('')
            empty_plot_item.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.ui.tools_table_mill_geo.setItem(row_idx, 4, empty_plot_item)
            plot_item = FCCheckBox()
            plot_item.setLayoutDirection(QtCore.Qt.LayoutDirection.RightToLeft)
            if self.ui.plot_cb.isChecked():
                plot_item.setChecked(True)
            self.ui.tools_table_mill_geo.setCellWidget(row_idx, 4, plot_item)

            row_idx += 1

        # make the diameter column editable
        for row in range(row_idx):
            self.ui.tools_table_mill_geo.item(row, 1).setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable |
                                                               QtCore.Qt.ItemFlag.ItemIsEditable |
                                                               QtCore.Qt.ItemFlag.ItemIsEnabled |
                                                               QtCore.Qt.ItemFlag.ItemIsDragEnabled)

        # sort the tool diameter column
        # self.ui.tools_table_mill_geo.sortItems(1)
        # all the tools are selected by default
        # self.ui.tools_table_mill_geo.selectColumn(0)

        self.ui.tools_table_mill_geo.resizeColumnsToContents()
        self.ui.tools_table_mill_geo.resizeRowsToContents()

        vertical_header = self.ui.tools_table_mill_geo.verticalHeader()
        # vertical_header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        vertical_header.hide()
        self.ui.tools_table_mill_geo.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        horizontal_header = self.ui.tools_table_mill_geo.horizontalHeader()
        horizontal_header.setMinimumSectionSize(10)
        horizontal_header.setDefaultSectionSize(70)
        horizontal_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(0, 20)
        horizontal_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        # horizontal_header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        # horizontal_header.resizeSection(2, 40)
        horizontal_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(4, 17)
        # horizontal_header.setStretchLastSection(True)
        self.ui.tools_table_mill_geo.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.ui.tools_table_mill_geo.setColumnWidth(0, 20)
        # self.ui.tools_table_mill_geo.setColumnWidth(2, 40)
        self.ui.tools_table_mill_geo.setColumnWidth(4, 17)

        # self.ui.tools_table_mill_geo.setSortingEnabled(True)

        self.ui.tools_table_mill_geo.setMinimumHeight(self.ui.tools_table_mill_geo.getHeight())
        self.ui.tools_table_mill_geo.setMaximumHeight(self.ui.tools_table_mill_geo.getHeight())

        # disable the Plot column in Tool Table if the geometry is SingleGeo as it is not needed
        # and can create some problems
        if self.target_obj and self.target_obj.multigeo is True:
            self.ui.tools_table_mill_geo.setColumnHidden(4, False)
        else:
            self.ui.tools_table_mill_geo.setColumnHidden(4, True)

        self.ui.tools_table_mill_geo.selectAll()

        # set the text on tool_data_label after loading the object
        sel_rows = set()
        sel_items = self.ui.tools_table_mill_geo.selectedItems()
        for it in sel_items:
            sel_rows.add(it.row())
            it.setSelected(True)

        if len(sel_rows) > 1:
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("Multiple Tools"))
            )

    def build_ui_exc(self):
        # updated units
        self.units = self.app.app_units.upper()

        if self.target_obj:
            self.ui.param_frame.setDisabled(False)

            # order the tools by tool diameter if it's the case
            sorted_tools = []
            for k, v in self.target_obj.tools.items():
                sorted_tools.append(self.app.dec_format(float(v['tooldia'])))

            order = self.ui.order_combo.get_value()
            if order == 1:  # 'fwd'
                sorted_tools.sort(reverse=False)
            elif order == 2:  # 'rev'
                sorted_tools.sort(reverse=True)
            else:
                pass

            # remake the excellon_tools dict in the order above
            new_id = 1
            new_tools = {}
            for tooldia in sorted_tools:
                for old_tool in self.target_obj.tools:
                    if self.app.dec_format(float(self.target_obj.tools[old_tool]['tooldia'])) == tooldia:
                        new_tools[new_id] = deepcopy(self.target_obj.tools[old_tool])
                        new_id += 1

            self.target_obj.tools = new_tools
            tools = [k for k in self.target_obj.tools]

        else:
            tools = []

        n = len(tools)
        # we have (n+2) rows because there are 'n' tools, each a row, plus the last 2 rows for totals.
        self.ui.tools_table_mill_exc.setRowCount(n + 2)
        self.tool_row = 0

        for tool_no in tools:
            # drill_cnt = 0  # variable to store the nr of drills per tool
            # slot_cnt = 0  # variable to store the nr of slots per tool

            # Find no of drills for the current tool
            try:
                drill_cnt = len(self.target_obj.tools[tool_no]["drills"])
            except KeyError:
                drill_cnt = 0
            self.tot_drill_cnt += drill_cnt

            # Find no of slots for the current tool
            try:
                slot_cnt = len(self.target_obj.tools[tool_no]["slots"])
            except KeyError:
                slot_cnt = 0
            self.tot_slot_cnt += slot_cnt

            # Tool name/id
            exc_id_item = QtWidgets.QTableWidgetItem('%d' % int(tool_no))
            exc_id_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled |
                                 QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_exc.setItem(self.tool_row, 0, exc_id_item)

            # Tool Diameter
            dia_item = QtWidgets.QTableWidgetItem('%.*f' % (self.decimals, self.target_obj.tools[tool_no]['tooldia']))
            dia_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled |
                              QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_exc.setItem(self.tool_row, 1, dia_item)

            # Number of drills per tool
            drill_count_item = QtWidgets.QTableWidgetItem('%d' % drill_cnt)
            drill_count_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_exc.setItem(self.tool_row, 2, drill_count_item)

            # Tool unique ID
            tool_uid_item = QtWidgets.QTableWidgetItem(str(int(tool_no)))
            # ## REMEMBER: THIS COLUMN IS HIDDEN in UI
            self.ui.tools_table_mill_exc.setItem(self.tool_row, 3, tool_uid_item)

            # Number of slots per tool
            # if the slot number is zero is better to not clutter the GUI with zero's so, we print a space
            slot_count_str = '%d' % slot_cnt if slot_cnt > 0 else ''
            slot_count_item = QtWidgets.QTableWidgetItem(slot_count_str)
            slot_count_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsDragEnabled)
            self.ui.tools_table_mill_exc.setItem(self.tool_row, 4, slot_count_item)

            self.tool_row += 1

        # add a last row with the Total number of drills
        empty_1 = QtWidgets.QTableWidgetItem('')
        empty_1.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
        empty_1_1 = QtWidgets.QTableWidgetItem('')
        empty_1_1.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)

        label_tot_drill_count = QtWidgets.QTableWidgetItem(_('Total Drills'))
        label_tot_drill_count.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

        tot_drill_count = QtWidgets.QTableWidgetItem('%d' % self.tot_drill_cnt)
        tot_drill_count.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

        self.ui.tools_table_mill_exc.setItem(self.tool_row, 0, empty_1)
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 1, label_tot_drill_count)
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 2, tot_drill_count)  # Total number of drills
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 4, empty_1_1)

        font = QtGui.QFont()
        font.setBold(True)
        # font.setWeight(75)

        for k in [1, 2]:
            self.ui.tools_table_mill_exc.item(self.tool_row, k).setForeground(QtGui.QColor(127, 0, 255))
            self.ui.tools_table_mill_exc.item(self.tool_row, k).setFont(font)

        self.tool_row += 1

        # add a last row with the Total number of slots
        empty_2 = QtWidgets.QTableWidgetItem('')
        empty_2.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
        empty_2_1 = QtWidgets.QTableWidgetItem('')
        empty_2_1.setFlags(~QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)

        label_tot_slot_count = QtWidgets.QTableWidgetItem(_('Total Slots'))
        tot_slot_count = QtWidgets.QTableWidgetItem('%d' % self.tot_slot_cnt)
        label_tot_slot_count.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
        tot_slot_count.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)

        self.ui.tools_table_mill_exc.setItem(self.tool_row, 0, empty_2)
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 1, label_tot_slot_count)
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 2, empty_2_1)
        self.ui.tools_table_mill_exc.setItem(self.tool_row, 4, tot_slot_count)  # Total number of slots

        for kl in [1, 2, 4]:
            self.ui.tools_table_mill_exc.item(self.tool_row, kl).setFont(font)
            self.ui.tools_table_mill_exc.item(self.tool_row, kl).setForeground(QtGui.QColor(0, 70, 255))

        # make the diameter column editable
        for row in range(self.ui.tools_table_mill_exc.rowCount() - 2):
            self.ui.tools_table_mill_exc.item(row, 1).setFlags(
                QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)

        self.ui.tools_table_mill_exc.resizeColumnsToContents()
        self.ui.tools_table_mill_exc.resizeRowsToContents()

        vertical_header = self.ui.tools_table_mill_exc.verticalHeader()
        vertical_header.hide()
        self.ui.tools_table_mill_exc.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        horizontal_header = self.ui.tools_table_mill_exc.horizontalHeader()
        self.ui.tools_table_mill_exc.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        horizontal_header.setMinimumSectionSize(10)
        horizontal_header.setDefaultSectionSize(70)

        horizontal_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        horizontal_header.resizeSection(0, 20)
        horizontal_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        self.ui.tools_table_mill_exc.setSortingEnabled(False)

        self.ui.tools_table_mill_exc.setMinimumHeight(self.ui.tools_table_mill_exc.getHeight())
        self.ui.tools_table_mill_exc.setMaximumHeight(self.ui.tools_table_mill_exc.getHeight())

        # all the tools are selected by default
        self.ui.tools_table_mill_exc.selectAll()

    def on_target_changed(self, val):
        # handle the Plot checkbox
        self.plot_cb_handler()

        obj_type = 1 if val == 'exc' else 2
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.object_combo.setCurrentIndex(0)
        self.ui.object_combo.obj_type = {
            "exc": "Excellon", "geo": "Geometry"
        }[val]

        if val == 'exc':
            self.ui.tools_table_mill_exc.show()
            self.ui.order_label.show()
            self.ui.order_combo.show()

            self.ui.tools_table_mill_geo.hide()

            self.ui.mill_type_label.show()
            self.ui.milling_type_radio.show()
            self.ui.mill_dia_label.show()
            self.ui.mill_dia_entry.show()

            self.ui.ovlabel.show()
            self.ui.overlap_entry.show()
            self.ui.connect_cb.show()

            self.ui.extracut_cb.hide()
            self.ui.e_cut_entry.hide()

            self.ui.job_type_lbl.hide()
            self.ui.job_type_combo.hide()
            self.ui.job_type_combo.set_value(0)  # 'iso' - will hide the Polish UI elements

            self.ui.offset_separator_line.hide()
            self.ui.tool_shape_label.hide()
            self.ui.tool_shape_combo.hide()

            self.ui.add_tool_frame.hide()
        else:
            self.ui.tools_table_mill_exc.hide()
            self.ui.order_label.hide()
            self.ui.order_combo.hide()

            self.ui.tools_table_mill_geo.show()

            self.ui.mill_type_label.hide()
            self.ui.milling_type_radio.hide()
            self.ui.mill_dia_label.hide()
            self.ui.mill_dia_entry.hide()

            self.ui.ovlabel.hide()
            self.ui.overlap_entry.hide()
            self.ui.connect_cb.hide()

            self.ui.frxylabel.show()
            self.ui.xyfeedrate_entry.show()
            self.ui.extracut_cb.show()
            self.ui.e_cut_entry.show()

            self.ui.job_type_lbl.show()
            self.ui.job_type_combo.show()
            # self.ui.job_type_combo.set_value(self.app.options["tools_mill_job_val"])

            self.ui.offset_separator_line.show()
            self.ui.tool_shape_label.show()
            self.ui.tool_shape_combo.show()

            self.ui.add_tool_frame.show()

        # set the object as active so the Properties is populated by whatever object is selected
        self.obj_name = self.ui.object_combo.currentText()
        if self.obj_name and self.obj_name != '':
            self.app.collection.set_all_inactive()
            self.app.collection.set_active(self.obj_name)
        # self.build_ui()

        # new object that is now selected
        obj = self.app.collection.get_by_name(self.obj_name)
        if obj is not None and obj.tools:
            last_key = list(obj.tools.keys())[-1]
            self.to_form(storage=self._form_tool_data(obj, last_key))

        self.on_level_changed(self.ui.level.isChecked())

    def on_object_changed(self):
        # print(self.app.ui.notebook.currentWidget().objectName() != 'plugin_tab')
        if not self.app.ui.notebook.tabText(2) != _("Milling Tool"):
            return

        # handle the Plot checkbox
        self.plot_cb_handler()
        
        # load the Milling object
        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return

        if self.target_obj is None:
            self.ui.param_frame.setDisabled(True)
            self.ui.plot_cb.setDisabled(True)
        else:
            self.ui.param_frame.setDisabled(False)
            self.ui.plot_cb.setDisabled(False)

            # set the object as active so the Properties is populated by whatever object is selected
            if self.obj_name and self.obj_name != '':
                self.app.collection.set_all_inactive()
                self.app.collection.set_active(self.obj_name)
            self.build_ui()

            if self.target_obj.tools:
                self.ui.param_frame.setDisabled(False)
                self.ui.generate_cnc_button.setDisabled(False)
                last_key = list(self.target_obj.tools.keys())[-1]
                self.to_form(storage=self._form_tool_data(self.target_obj, last_key))
            else:
                self.ui.param_frame.setDisabled(True)
                self.ui.generate_cnc_button.setDisabled(True)

    def on_object_selection_changed(self, current, previous):
        found_idx = None
        for tab_idx in range(self.app.ui.notebook.count()):
            if self.app.ui.notebook.tabText(tab_idx) == self.ui.pluginName:
                found_idx = True
                break

        if found_idx:
            try:
                sel_obj = current.indexes()[0].internalPointer().obj
                name = sel_obj.obj_options['name']
                kind = sel_obj.kind
                if kind == 'excellon':
                    self.ui.target_radio.set_value('exc')
                    self.ui.object_combo.set_value(name)

                if kind == 'geometry':
                    self.ui.target_radio.set_value('geo')
                    self.ui.object_combo.set_value(name)
            except Exception:
                pass

    def on_job_changed(self, idx):
        if self.ui.target_radio.get_value() == 'geo':
            if idx == 3:    # 'Polish'
                self.ui.polish_margin_lbl.show()
                self.ui.polish_margin_entry.show()
                self.ui.polish_over_lbl.show()
                self.ui.polish_over_entry.show()
                self.ui.polish_method_lbl.show()
                self.ui.polish_method_combo.show()

                self.ui.cutzlabel.setText('%s:' % _("Pressure"))
                self.ui.cutzlabel.setToolTip(
                    _("Negative value. The higher the absolute value\n"
                      "the stronger the pressure of the brush on the material.")
                )
            else:
                self.ui.polish_margin_lbl.hide()
                self.ui.polish_margin_entry.hide()
                self.ui.polish_over_lbl.hide()
                self.ui.polish_over_entry.hide()
                self.ui.polish_method_lbl.hide()
                self.ui.polish_method_combo.hide()

                self.ui.cutzlabel.setText('%s:' % _('Cut Z'))
                self.ui.cutzlabel.setToolTip(
                    _("Drill depth (negative)\n"
                      "below the copper surface.")
                )

    def on_offset_type_changed(self, idx):
        if idx == 3:    # 'Custom'
            self.ui.offset_label.show()
            self.ui.offset_entry.show()
        else:
            self.ui.offset_label.hide()
            self.ui.offset_entry.hide()

    def ui_connect(self):
        # When object selection on canvas change
        # self.app.collection.view.selectionModel().selectionChanged.connect(self.on_object_selection_changed)
        try:
            self.app.proj_selection_changed.disconnect(self.on_object_selection_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self.app.proj_selection_changed.connect(self.on_object_selection_changed)

        # Area Exception - exclusion shape added signal
        try:
            self.app.exc_areas.e_shape_modified.disconnect(self.update_exclusion_table)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self.app.exc_areas.e_shape_modified.connect(self.update_exclusion_table)

        # connect Tool Table Widgets
        for row in range(self.ui.tools_table_mill_geo.rowCount()):
            self.ui.tools_table_mill_geo.cellWidget(row, 4).clicked.connect(self.on_plot_cb_click_table)

        # # Geo Tool Table - rows selected
        self.ui.tools_table_mill_geo.clicked.connect(self.on_row_selection_change)
        self.ui.tools_table_mill_geo.itemChanged.connect(self.on_tool_edit)
        self.ui.tools_table_mill_geo.horizontalHeader().sectionClicked.connect(self.on_toggle_all_rows)

        # Excellon Tool Table - rows selected
        self.ui.tools_table_mill_exc.clicked.connect(self.on_row_selection_change)
        self.ui.tools_table_mill_exc.horizontalHeader().sectionClicked.connect(self.on_toggle_all_rows)

        self.ui.tool_shape_combo.currentIndexChanged.connect(self.on_tt_change)

        # Tool Parameters
        for opt in self.form_fields:
            current_widget: QtWidgets.QWidget = self.form_fields[opt]
            if isinstance(current_widget, FCCheckBox):
                current_widget.stateChanged.connect(self.form_to_storage)   # noqa
            if isinstance(current_widget, RadioSet):
                current_widget.activated_custom.connect(self.form_to_storage)
            elif isinstance(current_widget, FCDoubleSpinner) or isinstance(current_widget, FCSpinner):
                current_widget.returnPressed.connect(self.form_to_storage)
            elif isinstance(current_widget, FCComboBox):
                current_widget.currentIndexChanged.connect(self.form_to_storage)    # noqa
            elif isinstance(current_widget, FCComboBox2):
                current_widget.currentIndexChanged.connect(self.form_to_storage)    # noqa

        # General Parameters
        for opt in self.general_form_fields:
            current_widget = self.general_form_fields[opt]
            if isinstance(current_widget, FCCheckBox):
                current_widget.stateChanged.connect(self.form_to_storage)   # noqa
            if isinstance(current_widget, RadioSet):
                current_widget.activated_custom.connect(self.form_to_storage)
            elif isinstance(current_widget, FCDoubleSpinner) or isinstance(current_widget, FCSpinner):
                current_widget.returnPressed.connect(self.form_to_storage)
            elif isinstance(current_widget, FCComboBox):
                current_widget.currentIndexChanged.connect(self.form_to_storage)    # noqa
            elif isinstance(current_widget, FCComboBox2):
                current_widget.currentIndexChanged.connect(self.form_to_storage)    # noqa

        self.ui.order_combo.currentIndexChanged.connect(self.on_order_changed)

        # Exclusion Table widgets connect
        for row in range(self.ui.exclusion_table.rowCount()):
            self.ui.exclusion_table.cellWidget(row, 2).currentIndexChanged.connect(self.on_exclusion_table_strategy)

        self.ui.exclusion_table.itemChanged.connect(self.on_exclusion_table_overz)

    def ui_disconnect(self):
        try:
            self.app.proj_selection_changed.disconnect(self.on_object_selection_changed)
        except (TypeError, RuntimeError, AttributeError):
            pass

        try:
            self.app.exc_areas.e_shape_modified.disconnect(self.update_exclusion_table)
        except (TypeError, RuntimeError, AttributeError):
            pass

        # Excellon Tool Table - rows selected
        try:
            self.ui.tools_table_mill_exc.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tools_table_mill_exc.horizontalHeader().sectionClicked.disconnect()
        except (TypeError, AttributeError):
            pass

        # Geo Tool Table
        try:
            self.ui.tools_table_mill_geo.clicked.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tools_table_mill_geo.itemChanged.disconnect()
        except (TypeError, AttributeError):
            pass
        try:
            self.ui.tools_table_mill_geo.horizontalHeader().sectionClicked.disconnect()
        except (TypeError, AttributeError):
            pass

        # Geometry Tool table widgets
        for row in range(self.ui.tools_table_mill_geo.rowCount()):
            try:
                self.ui.tools_table_mill_geo.cellWidget(row, 4).clicked.disconnect()
            except (TypeError, AttributeError):
                pass

        # Tool Parameters
        for opt in self.form_fields:
            current_widget = self.form_fields[opt]
            if isinstance(current_widget, FCCheckBox):
                try:
                    current_widget.stateChanged.disconnect(self.form_to_storage)    # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass
            if isinstance(current_widget, RadioSet):
                try:
                    current_widget.activated_custom.disconnect(self.form_to_storage)
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCDoubleSpinner) or isinstance(current_widget, FCSpinner):
                try:
                    current_widget.returnPressed.disconnect(self.form_to_storage)
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCComboBox):
                try:
                    current_widget.currentIndexChanged.disconnect(self.form_to_storage)     # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCComboBox2):
                try:
                    current_widget.currentIndexChanged.disconnect(self.form_to_storage)     # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass

        try:
            self.ui.tool_shape_combo.currentIndexChanged.disconnect(self.on_tt_change)
        except (TypeError, ValueError, RuntimeError):
            pass

        # General Parameters
        for opt in self.general_form_fields:
            current_widget = self.general_form_fields[opt]
            if isinstance(current_widget, FCCheckBox):
                try:
                    current_widget.stateChanged.disconnect(self.form_to_storage)    # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass
            if isinstance(current_widget, RadioSet):    # noqa
                try:
                    current_widget.activated_custom.disconnect(self.form_to_storage)
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCDoubleSpinner) or isinstance(current_widget, FCSpinner):
                try:
                    current_widget.returnPressed.disconnect(self.form_to_storage)
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCComboBox):
                try:
                    current_widget.currentIndexChanged.disconnect(self.form_to_storage)    # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass
            elif isinstance(current_widget, FCComboBox2):
                try:
                    current_widget.currentIndexChanged.disconnect(self.form_to_storage)    # noqa
                except (TypeError, ValueError, RuntimeError):
                    pass

        try:
            self.ui.order_combo.currentIndexChanged.disconnect()
        except (TypeError, ValueError):
            pass

        # Exclusion Table widgets disconnect
        for row in range(self.ui.exclusion_table.rowCount()):
            try:
                self.ui.exclusion_table.cellWidget(row, 2).currentIndexChanged.disconnect()
            except (TypeError, AttributeError):
                pass

        try:
            self.ui.exclusion_table.itemChanged.disconnect()
        except (TypeError, AttributeError):
            pass

    def on_toggle_all_rows(self):
        """
        will toggle the selection of all rows in Tools table

        :return:
        """

        self.ui_disconnect()

        if self.ui.target_radio.get_value() == 'exc':
            plugin_table = self.ui.tools_table_mill_exc
        else:
            plugin_table = self.ui.tools_table_mill_geo

        # #########################################################################################################
        # Tool Table
        # #########################################################################################################
        sel_model = plugin_table.selectionModel()
        sel_rows_index_list = sel_model.selectedRows()
        sel_rows = [r.row() for r in sel_rows_index_list]

        if len(sel_rows) == plugin_table.rowCount():
            plugin_table.clearSelection()
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("No Tool Selected"))
            )
        else:
            plugin_table.selectAll()
            if plugin_table.rowCount() == 1:
                # update the QLabel that shows for which Tool we have the parameters in the UI form
                tooluid = int(plugin_table.item(0, 3).text())
                self.ui.tool_data_label.setText(
                    "<b>%s: <font color='#0000FF'>%s %d</font></b>" % (_('Parameters for'), _("Tool"), tooluid)
                )
            else:
                self.ui.tool_data_label.setText(
                    "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("Multiple Tools"))
                )

        sel_rows_index_list = sel_model.selectedRows()
        sel_rows = [r.row() for r in sel_rows_index_list]
        if sel_rows and len(sel_rows) > 0:
            self.ui.param_frame.setDisabled(False)
            self.ui.generate_cnc_button.setDisabled(False)
        else:
            self.ui.param_frame.setDisabled(True)
            self.ui.generate_cnc_button.setDisabled(True)

        self.ui_connect()

    def on_row_selection_change(self):
        if self.ui.target_radio.get_value() == 'exc':
            plugin_table = self.ui.tools_table_mill_exc
        else:
            plugin_table = self.ui.tools_table_mill_geo

        self.update_ui()

        sel_model = plugin_table.selectionModel()
        sel_rows_index_list = sel_model.selectedRows()
        sel_rows = [r.row() for r in sel_rows_index_list]

        if sel_rows and len(sel_rows) > 0:
            self.ui.param_frame.setDisabled(False)
            self.ui.generate_cnc_button.setDisabled(False)
        else:
            self.ui.param_frame.setDisabled(True)
            self.ui.generate_cnc_button.setDisabled(True)

    def update_ui(self):
        self.ui_disconnect()

        # load the Milling object
        self.obj_name = self.ui.object_combo.currentText()
        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return

        if self.ui.target_radio.get_value() == 'exc':
            plugin_table = self.ui.tools_table_mill_exc
        else:
            plugin_table = self.ui.tools_table_mill_geo

        sel_model = plugin_table.selectionModel()
        sel_rows_index_list = sel_model.selectedRows()
        sel_rows = [r.row() for r in sel_rows_index_list]

        if not sel_rows or len(sel_rows) == 0:
            self.ui.generate_cnc_button.setDisabled(True)
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("No Tool Selected"))
            )
            self.ui_connect()
            return
        else:
            self.ui.generate_cnc_button.setDisabled(False)
            self.ui.param_frame.setDisabled(False)

        if len(sel_rows) == 1:
            # update the QLabel that shows for which Tool we have the parameters in the UI form
            tooluid = int(plugin_table.item(list(sel_rows)[0], 0).text())
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s %d</font></b>" % (_('Parameters for'), _("Tool"), tooluid)
            )
        else:
            self.ui.tool_data_label.setText(
                "<b>%s: <font color='#0000FF'>%s</font></b>" % (_('Parameters for'), _("Multiple Tools"))
            )
            # update UI only if only one row is selected otherwise having multiple rows selected will deform information
            # for the rows other that the current one (first selected)
            self.ui_connect()
            return

        # #########################################################################################################
        # update the form with the V-Shape fields if V-Shape selected in the geo_plugin_table
        # also modify the Cut Z form entry to reflect the calculated Cut Z from values got from V-Shape Fields
        # #########################################################################################################
        if self.ui.target_radio.get_value() == 'geo':
            try:
                item = self.ui.tool_shape_combo
                if item is not None:
                    tool_type_txt = item.currentText()
                    self.ui_update_v_shape(tool_type_txt=tool_type_txt)
                else:
                    self.ui_connect()
                    return
            except Exception as e:
                self.app.log.error("Tool missing in ui_update_v_shape(). Add a tool in Geo Tool Table. %s" % str(e))
                self.ui_connect()
                return

        for c_row in sel_rows:
            # populate the form with the data from the tool associated with the row parameter
            try:
                item = plugin_table.item(c_row, 3)
                if type(item) is not None:
                    tooluid = item.text()
                    # if self.ui.target_radio.get_value() == 'geo':
                    #     tooluid = int(tooluid)
                    tooluid = int(tooluid)
                    self.storage_to_form(self._form_tool_data(self.target_obj, tooluid))
                else:
                    self.ui_connect()
                    return
            except Exception as e:
                self.app.log.error("Tool missing. Add a tool in the Tool Table. %s" % str(e))
                self.ui_connect()
                return

        self.ui_connect()

    def to_form(self, storage=None):
        if storage is None:
            # load the Milling object
            self.obj_name = self.ui.object_combo.currentText()
            # Get source object.
            try:
                self.target_obj = self.app.collection.get_by_name(self.obj_name)
            except Exception:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
                return
            storage = self.app.options if self.target_obj is None else self.target_obj.obj_options

        # calculate self.currnet_row for the cellWidgets in the Tools Table
        if self.ui.target_radio.get_value() == 'geo':
            t_table = self.ui.tools_table_mill_geo
        else:
            t_table = self.ui.tools_table_mill_exc
        self.current_row = t_table.currentRow()

        # Showing values is not editing: with the signals connected each changed combo box or check box would run
        # form_to_storage() and write the shown value into the tools of the target (of the previous target when the
        # target is not set yet, as in on_target_changed()), changing the saved data of the tools.
        self.ui_disconnect()
        try:
            self._set_form_fields(storage)
            # what the changed combo boxes did through their signals: the fields that depend on the tool shape and on
            # the preprocessor (Preferences are not applied: the form shows the saved values)
            try:
                if 'tools_mill_tool_shape' in storage and self.ui.target_radio.get_value() == 'geo':
                    self._show_v_shape_fields(self.ui.tool_shape_combo.currentText())
                self.on_pp_changed()
            except Exception as err:
                self.app.log.error("ToolMilling.to_form() updating the dependent fields --> %s" % str(err))
        finally:
            self.ui_connect()

    def _set_form_fields(self, storage):
        for k in list(self.form_fields.keys()) + list(self.general_form_fields.keys()):
            for option in storage:
                if option.startswith('tools_mill_'):
                    if k == option:
                        try:
                            if k in self.form_fields:
                                self.form_fields[k].set_value(storage[option])
                            else:
                                self.general_form_fields[k].set_value(storage[option])
                        except Exception:
                            # it may fail for form fields found in the tools tables if there are no rows
                            pass
                elif option.startswith('geometry_'):
                    if k == option.replace('geometry_', ''):
                        try:
                            if k in self.form_fields:
                                self.form_fields[k].set_value(storage[option])
                            else:
                                self.general_form_fields[k].set_value(storage[option])
                        except Exception:
                            # it may fail for form fields found in the tools tables if there are no rows
                            pass

    def storage_to_form(self, dict_storage):
        """
        Will update the GUI with data from the "storage" in this case the dict "self.tools"

        :param dict_storage:    A dictionary holding the data relevant for generating Gcode
        :type dict_storage:     dict
        :return:                None
        :rtype:
        """

        # we get the current row in the (geo) tools table for the form fields found in the table
        if self.ui.target_radio.get_value() == 'geo':
            t_table = self.ui.tools_table_mill_geo
        else:
            t_table = self.ui.tools_table_mill_exc
        self.current_row = t_table.currentRow()

        for storage_key in dict_storage:
            if storage_key in self.form_fields and storage_key not in \
                    ["tools_mill_toolchange", "tools_mill_toolchangez", "tools_mill_endxy", "tools_mill_endz",
                     "tools_mill_ppname_g", "tools_mill_area_exclusion",
                     "tools_mill_area_shape", "tools_mill_area_strategy", "tools_mill_area_overz"]:

                try:
                    self.form_fields[storage_key].set_value(dict_storage[storage_key])
                except Exception as e:
                    self.app.log.error(
                        "ToolMilling.storage_to_form() for key: %s with value: %s--> %s" %
                        (str(storage_key), str(dict_storage[storage_key]), str(e))
                    )

    def form_to_storage(self):
        """
        Will update the 'storage' attribute which is the dict "self.tools" with data collected from GUI

        :return:    None
        :rtype:
        """
        obj_name = self.ui.object_combo.currentText()
        if obj_name is None:
            return

        # the Target Object is Excellon
        if self.ui.target_radio.get_value() == 'exc':
            used_tools_table = self.ui.tools_table_mill_exc
            if used_tools_table.rowCount() == 2:
                # there is no tool in tool table so, we can't save the GUI elements values to storage
                # Excellon Tool Table has 2 rows by default
                return

        # the Target Object is Geometry
        else:
            used_tools_table = self.ui.tools_table_mill_geo
            if used_tools_table.rowCount() == 0:
                # there is no tool in tool table so, we can't save the GUI elements values to storage
                return

        self.ui_disconnect()

        widget_changed = self.sender()
        wdg_objname = widget_changed.objectName()

        # if the widget objectName is '' then it is a widget that we are not interested into
        if wdg_objname == '':
            self.ui_connect()
            return

        option_changed = self.name2option[wdg_objname]

        # update the tool specific parameters
        rows = sorted(set(index.row() for index in used_tools_table.selectedIndexes()))
        selected_tools = set()
        for row in rows:
            if row < 0:
                row = 0
            selected_tools.add(int(used_tools_table.item(row, 3).text()))

        if option_changed in self.form_fields and selected_tools:
            new_option_value = self.form_fields[option_changed].get_value()
            for tooluid_key, tooluid_val in self.target_obj.tools.items():
                if int(tooluid_key) in selected_tools:
                    try:
                        tooluid_val['data'][option_changed] = new_option_value
                    except Exception as e:
                        self.app.log.error(
                            "ToolMilling.form_to_storage() for key: %s with value: %s --> %s" %
                            (str(option_changed), str(new_option_value), str(e))
                        )

        # update the general parameters in all tools
        if option_changed in self.general_form_fields and self.target_obj.tools:
            new_opt_val = self.general_form_fields[option_changed].get_value()
            for tooluid_key, tooluid_val in self.target_obj.tools.items():
                try:
                    tooluid_val['data'][option_changed] = new_opt_val
                except Exception as err:
                    self.app.log.error("ToolMilling.form_to_storage() general parameters --> %s" % str(err))
        self.ui_connect()

    def on_tt_change(self):
        cw = self.sender()
        assert isinstance(cw, FCComboBox2)

        tool_type = cw.currentText()
        self.ui_update_v_shape(tool_type)
        self.ui_update_l_shape(tool_type)

        self.form_to_storage()

    def ui_update_l_shape(self, t_type):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        if t_type.upper() == 'L':
            self.ui.pp_geo_name_cb.set_value('default_laser')
        else:
            self.ui.pp_geo_name_cb.set_value(self.app.options.get(
                'tools_mill_ppname_g',
                app_defaults.get('tools_mill_ppname_g', AppDefaults.factory_defaults.get('tools_mill_ppname_g'))))
        self.on_pp_changed()

    def ui_update_v_shape(self, tool_type_txt):
        self._show_v_shape_fields(tool_type_txt)
        if tool_type_txt == 'V':
            self.ui.job_type_combo.set_value(2)   # 'Isolation'
            self.on_update_cutz()
        else:
            self.ui.job_type_combo.set_value(0)   # 'Roughing'

    def _show_v_shape_fields(self, tool_type_txt):
        """Show the V-tip fields for a V-Shape tool and hide them for any other tool; the tool data is not changed."""
        if tool_type_txt == 'V':
            self.ui.tipdialabel.show()
            self.ui.tipdia_entry.show()
            self.ui.tipanglelabel.show()
            self.ui.tipangle_entry.show()
            self.ui.cutzlabel.setToolTip(
                _("For V-shape tools the depth of cut is\n"
                  "calculated from other parameters like:\n"
                  "- 'V-tip Angle' -> angle at the tip of the tool\n"
                  "- 'V-tip Dia' -> diameter at the tip of the tool \n"
                  "- Tool Dia -> 'Dia' column found in the Tool Table\n"
                  "NB: a value of zero means that Tool Dia = 'V-tip Dia'")
            )
        else:
            self.ui.tipdialabel.hide()
            self.ui.tipdia_entry.hide()
            self.ui.tipanglelabel.hide()
            self.ui.tipangle_entry.hide()
            self.ui.cutzlabel.setToolTip(
                _("Cutting depth (negative)\n"
                  "below the copper surface.")
            )
            self.ui.cutz_entry.setToolTip('')

    def on_update_cutz(self):
        vdia = float(self.ui.tipdia_entry.get_value())
        half_vangle = float(self.ui.tipangle_entry.get_value()) / 2

        row = self.ui.tools_table_mill_geo.currentRow()
        tool_uid_item = self.ui.tools_table_mill_geo.item(row, 3)
        if tool_uid_item is None:
            return
        tool_uid = int(tool_uid_item.text())

        tool_dia_item = self.ui.tools_table_mill_geo.item(row, 1)
        if tool_dia_item is None:
            return
        tooldia = float(tool_dia_item.text())

        try:
            new_cutz = (tooldia - vdia) / (2 * math.tan(math.radians(half_vangle)))
        except ZeroDivisionError:
            new_cutz = 0.0

        new_cutz = self.app.dec_format(new_cutz, self.decimals) * -1.0   # this value has to be negative

        self.ui.cutz_entry.set_value(new_cutz)

        # store the new CutZ value into storage (self.tools)
        for tooluid_key, tooluid_value in self.target_obj.tools.items():
            if int(tooluid_key) == tool_uid:
                tooluid_value['data']['tools_mill_cutz'] = new_cutz

    def get_selected_tools_list(self):
        """
        Returns the keys to the "self.tools" dictionary corresponding
        to the selections on the tool list in the appGUI.

        :return:    List of tools.
        :rtype:     list
        """

        return [str(x.text()) for x in self.ui.tools_table_mill_exc.selectedItems()]

    def on_apply_param_to_all_clicked(self):
        with _history_step(self, _("Apply to all tools")):
            return ToolMilling._on_apply_param_to_all_clicked(self)

    def _on_apply_param_to_all_clicked(self):
        # the tools table of the current target; the hidden Excellon table is not cleared for a Geometry target
        if self.ui.target_radio.get_value() == 'geo':
            tools_table = self.ui.tools_table_mill_geo
        else:
            tools_table = self.ui.tools_table_mill_exc

        if tools_table.rowCount() == 0:
            # there is no tool in tool table so, we can't save the GUI elements values to storage
            self.app.log.debug("ToolMilling.on_apply_param_to_all_clicked() --> no tool in Tools Table, aborting.")
            return

        row = tools_table.currentRow()
        if row < 0:
            row = 0

        # the 2 rows with the totals of the Excellon tools table have no tool UID, or a stale one: setRowCount() keeps
        # the items of the rows built before for an object with more tools
        uid_item = tools_table.item(row, 3)
        tooluid_item = int(uid_item.text()) if uid_item is not None and uid_item.text() else None
        temp_tool_data = None

        for tooluid_key, tooluid_val in self.target_obj.tools.items():
            if int(tooluid_key) == tooluid_item:
                # this will hold the 'data' key of the self.tools[tool] dictionary that corresponds to
                # the current row in the tool table
                temp_tool_data = tooluid_val['data']
                break

        if temp_tool_data is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No Tool Selected"))
            return

        self.ui_disconnect()

        for tooluid_key, tooluid_val in self.target_obj.tools.items():
            tooluid_val['data'] = deepcopy(temp_tool_data)

        self.app.inform.emit('[success] %s' % _("Current Tool parameters were applied to all tools."))
        self.ui_connect()

    def on_order_changed(self, order):
        if order != 0:  # "default" choice
            # the rebuild sorts the tools of an Excellon target: a user action
            with _history_step(self, _("Tool order")):
                self.build_ui()

    def on_tool_add(self, dia=None, new_geo=None):
        with _history_step(self, _("Add tool")):
            return ToolMilling._on_tool_add(self, dia, new_geo)

    def _on_tool_add(self, dia=None, new_geo=None):
        self.app.log.debug("GeometryObject.on_add_tool()")

        if self.target_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object is selected."))
            return

        self.ui_disconnect()

        filename = self.app.tools_database_path()

        tool_dia = dia if dia is not None else self.ui.addtool_entry.get_value()

        # construct a list of all 'tooluid' in the self.iso_tools
        tool_uid_list = [int(tooluid_key) for tooluid_key in self.target_obj.tools]

        # find maximum from the temp_uid, add 1 and this is the new 'tooluid'
        max_uid = 0 if not tool_uid_list else max(tool_uid_list)
        tooluid = int(max_uid) + 1

        new_tools_dict = deepcopy(self.default_data)
        updated_tooldia = None

        # determine the new tool diameter
        if tool_dia is None or tool_dia == 0:
            self.build_ui()
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Please enter a tool diameter with non-zero value, "
                                                        "in Float format."))
            self.ui_connect()
            return
        truncated_tooldia = self.app.dec_format(tool_dia, self.decimals)

        try:
            tools_db_dict = load_tools_database(filename, self.app.options, target=1,
                                               diameter=truncated_tooldia,
                                               units=getattr(self.app, 'app_units', None))
        except (OSError, TypeError, ValueError) as error:
            self.app.log.error("Could not load tools DB file.")
            self.app.log.error(str(error))
            self.app.inform.emit('[ERROR] %s' % tools_database_error_message(error))
            self.ui_connect()
            self.on_tool_default_add(dia=tool_dia)
            return

        tool_found = len(tools_db_dict)

        # look in database tools
        for db_tool, db_tool_val in tools_db_dict.items():
            db_tooldia = db_tool_val['tooldia']
            updated_tooldia = db_tooldia if db_tooldia != truncated_tooldia else None
            for d in db_tool_val['data']:
                if not d.startswith('tools_') or d.startswith('tools_mill_'):
                    new_tools_dict[d] = deepcopy(db_tool_val['data'][d])

        # test we found a suitable tool in Tools Database or if multiple ones
        if tool_found == 0:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Tool not in Tools Database. Adding a default tool."))
            self.on_tool_default_add(dia=tool_dia, new_geo=new_geo)
            self.ui_connect()
            return

        # if we found more than one tool then message "warning" and return
        if tool_found > 1:
            self.app.inform.emit(
                '[WARNING_NOTCL] %s' % _("Cancelled.\n"
                                         "Multiple tools for one tool diameter found in Tools Database."))
            self.ui_connect()
            return

        # i we found only one tool then go forward and add it
        new_tdia = deepcopy(updated_tooldia) if updated_tooldia is not None else deepcopy(truncated_tooldia)
        self.target_obj.tools.update({
            tooluid: {
                'tooldia':          new_tdia,
                'data':             deepcopy(new_tools_dict),
                'solid_geometry':   self.target_obj.solid_geometry
            }
        })
        self.ui_connect()
        self.build_ui()
        self.target_obj.build_ui()

        # select the tool just added
        for row in range(self.ui.tools_table_mill_geo.rowCount()):
            if int(self.ui.tools_table_mill_geo.item(row, 3).text()) == tooluid:
                self.ui.tools_table_mill_geo.selectRow(row)
                break

        # update the UI form
        self.update_ui()

        # if there is at least one tool left in the Tools Table, enable the parameters GUI
        if self.ui.tools_table_mill_geo.rowCount() != 0:
            self.ui.param_frame.setDisabled(False)

        self.app.inform.emit('[success] %s' % _("New tool added to Tool Table from Tools Database."))

    def on_tool_default_add(self, dia=None, new_geo=None, muted=None):
        with _history_step(self, _("Add tool")):
            return ToolMilling._on_tool_default_add(self, dia, new_geo, muted)

    def _on_tool_default_add(self, dia=None, new_geo=None, muted=None):
        self.ui_disconnect()

        tooldia = dia if dia is not None else self.ui.addtool_entry.get_value()

        if tooldia == 0.0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Please enter a tool diameter with non-zero value, "
                                                        "in Float format."))
            self.ui_connect()
            return 'fail'

        tool_uid_list = [int(tooluid_key) for tooluid_key in self.target_obj.tools]

        # find maximum from the temp_uid, add 1 and this is the new 'tooluid'
        max_uid = max(tool_uid_list) if tool_uid_list else 0
        self.tooluid = int(max_uid) + 1

        tooldia = self.app.dec_format(tooldia, self.decimals)

        # here we actually add the new tool; if there is no tool in the tool table we add a tool with default data
        # otherwise we add a tool with data copied from last tool
        if self.target_obj.tools:
            last_data = self.target_obj.tools[max_uid]['data']
            last_solid_geometry = self.target_obj.tools[max_uid]['solid_geometry'] if new_geo is None else new_geo

            # if previous geometry was empty (it may happen for the first tool added)
            # then copy the object.solid_geometry
            if not last_solid_geometry:
                last_solid_geometry = self.target_obj.solid_geometry

            self.target_obj.tools.update({
                self.tooluid: {
                    'tooldia':          tooldia,
                    'data':             deepcopy(last_data),
                    'solid_geometry':   deepcopy(last_solid_geometry)
                }
            })
        else:
            self.target_obj.tools.update({
                self.tooluid: {
                    'tooldia':          tooldia,
                    'data':             deepcopy(self.default_data),
                    'solid_geometry':   self.solid_geometry
                }
            })

        self.target_obj.tools[self.tooluid]['data']['name'] = deepcopy(self.target_obj.obj_options['name'])

        # we do this HACK to make sure the tools attribute to be serialized is updated in the self.ser_attrs list
        try:
            self.target_obj.ser_attrs.remove('tools')
        except TypeError:
            pass
        self.target_obj.ser_attrs.append('tools')

        if muted is None:
            self.app.inform.emit('[success] %s' % _("Tool added in Tool Table."))

        self.ui_connect()
        self.build_ui()
        self.target_obj.build_ui()

        # if there is at least one tool left in the Tools Table, enable the parameters GUI
        if self.ui.tools_table_mill_geo.rowCount() != 0:
            self.ui.param_frame.setDisabled(False)

    def on_tool_add_from_db_clicked(self):
        """
        Called when the user wants to add a new tool from Tools Database. It will create the Tools Database object
        and display the Tools Database tab in the form needed for the Tool adding
        :return: None
        """

        # if the Tools Database is already opened focus on it
        for idx in range(self.app.ui.plot_tab_area.count()):
            if self.app.ui.plot_tab_area.tabText(idx) == _("Tools Database"):
                self.app.ui.plot_tab_area.setCurrentWidget(self.app.tools_db_tab)
                break
        ret_val = self.app.on_tools_database(source='milling')
        if ret_val == 'fail':
            return
        self.app.tools_db_tab.ok_to_add = True
        self.app.tools_db_tab.ui.buttons_frame.hide()
        self.app.tools_db_tab.ui.add_tool_from_db.show()
        self.app.tools_db_tab.ui.cancel_tool_from_db.show()

    def on_tool_from_db_inserted(self, tool):
        with _history_step(self, _("Add tool from DB")):
            return ToolMilling._on_tool_from_db_inserted(self, tool)

    def _on_tool_from_db_inserted(self, tool):
        """
        Called from the Tools DB object through an App method when adding a tool from Tools Database
        :param tool: a dict with the tool data
        :return: None
        """

        self.ui_disconnect()
        self.units = self.app.app_units.upper()

        tooldia = float(tool['tooldia'])

        # construct a list of all 'tooluid' in the self.tools
        tool_uid_list = []
        for tooluid_key in self.target_obj.tools:
            tool_uid_item = int(tooluid_key)
            tool_uid_list.append(tool_uid_item)

        # find maximum from the temp_uid, add 1 and this is the new 'tooluid'
        if not tool_uid_list:
            max_uid = 0
        else:
            max_uid = max(tool_uid_list)
        self.tooluid = max_uid + 1

        tooldia = float('%.*f' % (self.decimals, tooldia))

        self.target_obj.tools.update({
            self.tooluid: {
                'tooldia': tooldia,
                'data': deepcopy(tool['data']),
                'solid_geometry': self.target_obj.solid_geometry
            }
        })

        self.target_obj.tools[self.tooluid]['data']['name'] = deepcopy(self.target_obj.obj_options['name'])

        # we do this HACK to make sure the tools attribute to be serialized is updated in the self.ser_attrs list
        try:
            self.target_obj.ser_attrs.remove('tools')
        except TypeError:
            pass
        self.target_obj.ser_attrs.append('tools')

        self.ui_connect()
        self.build_ui()

        # if there is no tool left in the Tools Table, enable the parameters appGUI
        if self.ui.tools_table_mill_geo.rowCount() != 0:
            self.ui.param_frame.setDisabled(False)

    def on_tool_edit(self, current_item):
        with _history_step(self, _("Edit tool")):
            return ToolMilling._on_tool_edit(self, current_item)

    def _on_tool_edit(self, current_item):
        self.ui_disconnect()

        current_row = current_item.row()
        try:
            dia = float(self.ui.tools_table_mill_geo.item(current_row, 1).text())
        except ValueError:
            # try to convert comma to decimal point. if it's still not working error message and return
            try:
                dia = float(self.ui.tools_table_mill_geo.item(current_row, 1).text().replace(',', '.'))
            except ValueError:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                return
        except AttributeError:
            self.ui_connect()
            return

        tool_dia = self.app.dec_format(dia, self.decimals)
        tooluid = int(self.ui.tools_table_mill_geo.item(current_row, 3).text())

        # update Tool dia
        self.target_obj.tools[tooluid]['tooldia'] = deepcopy(tool_dia)
        self.target_obj.tools[tooluid]['data']['tools_mill_tooldia'] = deepcopy(tool_dia)

        # update Cut Z if the tool has a V shape tool
        if self.ui.tool_shape_combo.get_value() == 5:   # 'V'
            self.on_update_cutz()

        try:
            self.target_obj.ser_attrs.remove('tools')
            self.target_obj.ser_attrs.append('tools')
        except (TypeError, ValueError):
            pass

        self.app.inform.emit('[success] %s' % _("Tool was edited in Tool Table."))
        self.ui_connect()
        self.build_ui_sig.emit()
        self.target_obj.build_ui()

    def on_tool_copy(self, all_tools=None):
        with _history_step(self, _("Copy tool")):
            return ToolMilling._on_tool_copy(self, all_tools)

    def _on_tool_copy(self, all_tools=None):
        self.ui_disconnect()

        # find the tool_uid maximum value in the self.tools
        uid_list = []
        for key in self.target_obj.tools:
            uid_list.append(int(key))
        try:
            max_uid = max(uid_list, key=int)
        except ValueError:
            max_uid = 0

        if all_tools is None:
            if self.ui.tools_table_mill_geo.selectedItems():
                for current_row in self.ui.tools_table_mill_geo.selectedItems():
                    # sometimes the header get selected, and it has row number -1
                    # we don't want to do anything with the header :)
                    if current_row.row() < 0:
                        continue
                    try:
                        tooluid_copy = int(self.ui.tools_table_mill_geo.item(current_row.row(), 3).text())
                        max_uid += 1
                        self.target_obj.tools[int(max_uid)] = deepcopy(self.target_obj.tools[tooluid_copy])
                    except AttributeError:
                        self.app.inform.emit('[WARNING_NOTCL] %s' % _("Failed. Select a tool to copy."))
                        self.ui_connect()
                        self.build_ui_sig.emit()
                        return
                    except Exception as e:
                        self.app.log.error("on_tool_copy() --> " + str(e))
                # deselect the table
                # self.ui.tools_table_mill_geo.clearSelection()
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Failed. Select a tool to copy."))
                self.ui_connect()
                self.build_ui_sig.emit()
                return
        else:
            # we copy all tools in tools_table_mill_geo
            try:
                temp_tools = deepcopy(self.target_obj.tools)
                max_uid += 1
                for tooluid in temp_tools:
                    self.target_obj.tools[int(max_uid)] = deepcopy(temp_tools[tooluid])
                temp_tools.clear()
            except Exception as e:
                self.app.log.error("on_tool_copy() --> " + str(e))

        # we do this HACK to make sure the tools attribute to be serialized is updated in the self.ser_attrs list
        try:
            self.target_obj.ser_attrs.remove('tools')
        except ValueError:
            pass
        self.target_obj.ser_attrs.append('tools')

        self.ui_connect()
        self.build_ui_sig.emit()
        self.app.inform.emit('[success] %s' % _("Tool was copied in Tool Table."))

    def on_tool_delete(self, all_tools=None):
        with _history_step(self, _("Delete tool")):
            return ToolMilling._on_tool_delete(self, all_tools)

    def _on_tool_delete(self, all_tools=None):
        self.ui_disconnect()

        if all_tools is None:
            if self.ui.tools_table_mill_geo.selectedItems():
                for current_row in self.ui.tools_table_mill_geo.selectedItems():
                    # sometimes the header get selected, and it has row number -1
                    # we don't want to do anything with the header :)
                    if current_row.row() < 0:
                        continue
                    try:
                        tooluid_del = int(self.ui.tools_table_mill_geo.item(current_row.row(), 3).text())

                        temp_tools = deepcopy(self.target_obj.tools)
                        for tooluid_key in self.target_obj.tools:
                            if int(tooluid_key) == tooluid_del:
                                # if the "self.tools" has only one tool, and we delete it then we move the
                                # solid_geometry as a property of the object otherwise there will be nothing to hold it
                                if len(self.target_obj.tools) == 1:
                                    self.target_obj.solid_geometry = deepcopy(
                                        self.target_obj.tools[tooluid_key]['solid_geometry']
                                    )
                                temp_tools.pop(tooluid_del, None)
                        self.target_obj.tools = deepcopy(temp_tools)
                        temp_tools.clear()
                    except AttributeError:
                        self.app.inform.emit('[WARNING_NOTCL] %s' % _("Failed. Select a tool to delete."))
                        self.ui_connect()
                        self.build_ui_sig.emit()
                        return
                    except Exception as e:
                        self.app.log.error("on_tool_delete() --> " + str(e))
                # deselect the table
                # self.ui.tools_table_mill_geo.clearSelection()
            else:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _("Failed. Select a tool to delete."))
                self.ui_connect()
                self.build_ui_sig.emit()
                return
        else:
            # we delete all tools in tools_table_mill_geo
            self.target_obj.tools.clear()

        self.app.plot_all()

        # we do this HACK to make sure the tools attribute to be serialized is updated in the self.ser_attrs list
        try:
            self.target_obj.ser_attrs.remove('tools')
        except TypeError:
            pass
        self.target_obj.ser_attrs.append('tools')

        self.ui_connect()

        self.build_ui()
        self.target_obj.build_ui()
        self.app.inform.emit('[success] %s' % _("Tool was deleted in Tool Table."))

        obj_active = self.target_obj
        # if the object was MultiGeo, and now it has no tool at all (therefore no geometry)
        # we make it back SingleGeo
        if self.ui.tools_table_mill_geo.rowCount() <= 0:
            obj_active.multigeo = False
            obj_active.obj_options['xmin'] = 0
            obj_active.obj_options['ymin'] = 0
            obj_active.obj_options['xmax'] = 0
            obj_active.obj_options['ymax'] = 0

        if obj_active.multigeo is True:
            try:
                xmin, ymin, xmax, ymax = obj_active.bounds()
                obj_active.obj_options['xmin'] = xmin
                obj_active.obj_options['ymin'] = ymin
                obj_active.obj_options['xmax'] = xmax
                obj_active.obj_options['ymax'] = ymax
            except Exception:
                obj_active.obj_options['xmin'] = 0
                obj_active.obj_options['ymin'] = 0
                obj_active.obj_options['xmax'] = 0
                obj_active.obj_options['ymax'] = 0

        # if there is no tool left in the Tools Table, disable the parameters appGUI
        if self.ui.tools_table_mill_geo.rowCount() == 0:
            self.ui.param_frame.setDisabled(True)

    def generate_milling_drills(self, tools=None, outname=None, tooldia=None, plot=False, use_thread=False):
        """
        Will generate a Geometry Object allowing to cut a drill hole instead of drilling it.

        Note: This method is a good template for generic operations as
        it takes its options from parameters or otherwise from the
        object's options and returns a (success, msg) tuple as feedback
        for shell operations.

        :param tools:       A list of tools where the drills are to be milled or a string: "all"
        :type tools:
        :param outname:     the name of the resulting Geometry object
        :type outname:      str
        :param tooldia:     the tool diameter to be used in creation of the milling path (Geometry Object)
        :type tooldia:      float
        :param plot:        if to plot the resulting object
        :type plot:         bool
        :param use_thread:  if to use threading for creation of the Geometry object
        :type use_thread:   bool
        :return:            Success/failure condition tuple (bool, str).
        :rtype:             tuple
        """

        # Get the tools from the list. These are keys
        # to self.tools
        if tools is None:
            tools = self.get_selected_tools_list()

        if outname is None:
            outname = self.target_obj.obj_options["name"] + "_mill"

        if tooldia is None:
            tooldia = self.ui.tooldia_entry.get_value()

        # Sort tools by diameter. items() -> [('name', diameter), ...]
        # sorted_tools = sorted(list(self.tools.items()), key=lambda tl: tl[1]) # no longer works in Python3

        sort = []
        for k, v in self.target_obj.tools.items():
            sort.append((k, v['tooldia']))
        sorted_tools = sorted(sort, key=lambda t1: t1[1])

        if tools == "all":
            tools = [i[0] for i in sorted_tools]  # List if ordered tool names.
            self.app.log.debug("Tools 'all' and sorted are: %s" % str(tools))

        if len(tools) == 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Please select one or more tools from the list and try again."))
            return False, "Error: No tools."

        for tool in tools:
            if tooldia > self.target_obj.tools[tool]["tooldia"]:
                mseg = '[ERROR_NOTCL] %s %s: %s' % (_("Milling tool for DRILLS is larger than hole size. Cancelled."),
                                                    _("Tool"),
                                                    str(tool))
                self.app.inform.emit(mseg)
                return False, "Error: Milling tool is larger than hole."

        def geo_init(geo_obj, app_obj):
            """

            :param geo_obj:     New object
            :type geo_obj:      GeometryObject
            :param app_obj:     App
            :type app_obj:      FlatCAMApp.App
            :return:
            :rtype:
            """
            assert geo_obj.kind == 'geometry', "Initializer expected a GeometryObject, got %s" % type(geo_obj)

            # ## Add properties to the object

            geo_obj.obj_options['type'] = 'Excellon Geometry'
            geo_obj.obj_options["tools_mill_tooldia"] = str(tooldia)
            app_defaults = getattr(app_obj, "defaults", None) or AppDefaults.factory_defaults
            geo_obj.obj_options["multidepth"] = app_obj.options.get(
                "tools_mill_multidepth",
                app_defaults.get("tools_mill_multidepth", AppDefaults.factory_defaults.get("tools_mill_multidepth")))
            geo_obj.solid_geometry = MillingGen.milling_drills_geometry(self.target_obj.tools, tools, tooldia)

            if not geo_obj.solid_geometry:
                return "fail"

        if use_thread:
            def geo_thread(a_obj):
                self.new_object("geometry", outname, geo_init, source=self.target_obj, plot=plot)

            # Create a promise with the new name
            self.app.collection.promise(outname)

            # Send to worker
            self.app.worker_task.emit({'fcn': geo_thread, 'params': [self.app]})
        else:
            self.new_object("geometry", outname, geo_init, source=self.target_obj, plot=plot)

        return True, ""

    def generate_milling_slots(self, tools=None, outname=None, tooldia=None, plot=False, use_thread=False):
        """
        Will generate a Geometry Object allowing to cut/mill a slot hole.

        Note: This method is a good template for generic operations as
        it takes its options from parameters or otherwise from the
        object's options and returns a (success, msg) tuple as feedback
        for shell operations.

        :param tools:       A list of tools where the drills are to be milled or a string: "all"
        :type tools:
        :param outname:     the name of the resulting Geometry object
        :type outname:      str
        :param tooldia:     the tool diameter to be used in creation of the milling path (Geometry Object)
        :type tooldia:      float
        :param plot:        if to plot the resulting object
        :type plot:         bool
        :param use_thread:  if to use threading for creation of the Geometry object
        :type use_thread:   bool
        :return:            Success/failure condition tuple (bool, str).
        :rtype:             tuple
        """

        # Get the tools from the list. These are keys
        # to self.tools
        if tools is None:
            tools = self.get_selected_tools_list()

        if outname is None:
            outname = self.target_obj.obj_options["name"] + "_mill"

        if tooldia is None:
            tooldia = float(self.target_obj.obj_options["slot_tooldia"])

        # Sort tools by diameter. items() -> [('name', diameter), ...]
        # sorted_tools = sorted(list(self.tools.items()), key=lambda tl: tl[1]) # no longer works in Python3

        sort = []
        for k, v in self.target_obj.tools.items():
            sort.append((k, v['tooldia']))
        sorted_tools = sorted(sort, key=lambda t1: t1[1])

        if tools == "all":
            tools = [i[0] for i in sorted_tools]  # List if ordered tool names.
            self.app.log.debug("Tools 'all' and sorted are: %s" % str(tools))

        if len(tools) == 0:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Please select one or more tools from the list and try again."))
            return False, "Error: No tools."

        for tool in tools:
            if not self.target_obj.tools[tool]['slots']:
                # No slots for this tool
                continue

            # I add the 0.0001 value to account for the rounding error in converting from IN to MM and reverse
            adj_toolstable_tooldia = float('%.*f' % (self.decimals, float(tooldia)))
            adj_file_tooldia = float('%.*f' % (self.decimals, float(self.target_obj.tools[tool]["tooldia"])))
            if adj_toolstable_tooldia > adj_file_tooldia + 0.0001:
                self.app.inform.emit('[ERROR_NOTCL] %s' %
                                     _("Milling tool for SLOTS is larger than hole size. Cancelled."))
                return False, "Error: Milling tool is larger than hole."

        def geo_init(geo_obj, app_obj):
            assert geo_obj.kind == 'geometry', "Initializer expected a GeometryObject, got %s" % type(geo_obj)

            # ## Add properties to the object

            geo_obj.obj_options['type'] = 'Excellon Geometry'
            geo_obj.obj_options["tools_mill_tooldia"] = str(tooldia)
            app_defaults = getattr(app_obj, "defaults", None) or AppDefaults.factory_defaults
            geo_obj.obj_options["tools_mill_multidepth"] = app_obj.options.get(
                "tools_mill_multidepth",
                app_defaults.get("tools_mill_multidepth", AppDefaults.factory_defaults.get("tools_mill_multidepth")))
            geo_obj.solid_geometry = MillingGen.milling_slots_geometry(
                self.target_obj.tools, tools, tooldia, self.decimals, self.geo_steps_per_circle,
                line_string=LineString)
            if not geo_obj.solid_geometry:
                return "fail"

        if use_thread:
            def geo_thread(a_obj):
                self.new_object("geometry", outname + '_slot', geo_init, source=self.target_obj, plot=plot)

            # Create a promise with the new name
            self.app.collection.promise(outname)

            # Send to worker
            self.app.worker_task.emit({'fcn': geo_thread, 'params': [self.app]})
        else:
            self.new_object("geometry", outname + '_slot', geo_init, source=self.target_obj, plot=plot)

        return True, ""

    def on_generate_cncjob_click(self):
        self.app.delete_selection_shape()

        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return "Could not retrieve object: %s with error: %s" % (self.obj_name, str(e))

        if self.target_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s.' % _("Object not found"))
            return

        if self.target_obj.kind == 'geometry':
            self.on_generate_cnc_from_geo()
        elif self.target_obj.kind == 'excellon':
            self.on_generate_cnc_from_exc()

    def on_generate_cnc_from_exc(self):
        self.app.log.debug("Generating CNCJob from milling Excellon ...")

        self.sel_tools.clear()

        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return "Could not retrieve object: %s with error: %s" % (self.obj_name, str(e))

        if self.target_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(self.obj_name)))
            return

        try:
            if self.target_obj.special_group:
                msg = '[WARNING_NOTCL] %s %s %s.' % \
                      (
                          _("This Geometry can't be processed because it is"),
                          str(self.target_obj.special_group),
                          _("Geometry")
                      )
                self.app.inform.emit(msg)
                return
        except AttributeError:
            pass

        # test to see if we have tools available in the tool table
        if self.ui.tools_table_mill_exc.selectedItems():
            for x in self.ui.tools_table_mill_exc.selectedItems():
                tooluid = int(self.ui.tools_table_mill_exc.item(x.row(), 3).text())

                for tooluid_key, tooluid_value in self.target_obj.tools.items():
                    if int(tooluid_key) == tooluid:
                        self.sel_tools.update({
                            tooluid: deepcopy(tooluid_value)
                        })

            self.paint_excellon_cncjpb()

        elif self.ui.tools_table_mill_geo.rowCount() == 3:
            tooluid = int(self.ui.tools_table_mill_exc.item(0, 3).text())

            for tooluid_key, tooluid_value in self.target_obj.tools.items():
                if int(tooluid_key) == tooluid:
                    self.sel_tools.update({
                        tooluid: deepcopy(tooluid_value)
                    })
            self.paint_excellon_cncjpb()
            # self.ui.tools_table_mill_geo.clearSelection()
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed. No tool selected in the tool table ..."))

    def paint_excellon_cncjpb(self):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        new_obj = self._prepare_excellon_paint_object()
        tools_dict = self.sel_tools
        circle_steps = self.app.options.get(
            'geometry_circle_steps', app_defaults.get(
                'geometry_circle_steps', AppDefaults.factory_defaults.get('geometry_circle_steps')))

        for tool in tools_dict:
            total_geometry = self._paint_excellon_tool_geometry(tools_dict[tool], circle_steps)
            if total_geometry is None:
                continue
            mill_dia = tools_dict[tool]['data']['tools_mill_milling_dia']
            tools_dict[tool]['data']['tools_mill_tooldia'] = mill_dia
            tools_dict[tool]['tooldia'] = mill_dia
            new_obj.tools[tool] = {
                'tooldia':          mill_dia,
                'data':             deepcopy(self.target_obj.tools[tool]['data']),
                'solid_geometry':   deepcopy(total_geometry)
            }
            new_obj.tools[tool]['data']['tools_mill_tooldia'] = mill_dia
            new_obj.tools[tool]['data']['seg_x'] = self.app.options.get(
                'geometry_seg_x', app_defaults.get('geometry_seg_x', AppDefaults.factory_defaults.get('geometry_seg_x')))
            new_obj.tools[tool]['data']['seg_y'] = self.app.options.get(
                'geometry_seg_y', app_defaults.get('geometry_seg_y', AppDefaults.factory_defaults.get('geometry_seg_y')))

        self.generate_cnc_job_handler(geo_obj=new_obj, tools_dict=new_obj.tools, disable_offset=True)

    def _prepare_excellon_paint_object(self):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        outname = "%s_%s" % (self.target_obj.obj_options["name"], 'exc_cnc')
        new_obj = HybridGeoExc(app=self.app)
        new_obj.obj_options = dict()
        for opt, val in self.target_obj.obj_options.items():
            new_obj.obj_options[opt] = val
        new_obj.obj_options['name'] = outname
        new_obj.units = self.app.options.get(
            "units", app_defaults.get("units", AppDefaults.factory_defaults.get("units")))
        kind = 'geometry'
        for option in self.app.options:
            if option.find(kind + "_") == 0:
                oname = option[len(kind) + 1:]
                new_obj.obj_options[oname] = self.app.options.get(
                    option, app_defaults.get(option, AppDefaults.factory_defaults.get(option)))
        return new_obj

    def _paint_excellon_tool_geometry(self, tool, circle_steps):
        data = tool['data']
        mill_dia = data['tools_mill_milling_dia']
        over = data['tools_mill_milling_overlap'] / 100
        conn = data['tools_mill_milling_connect']
        total_paint_geo = MillingGen.excellon_paint_polygons(tool, line_string=LineString)
        if not total_paint_geo:
            return

        geo_len = len(total_paint_geo)
        old_disp_number = 0
        total_geometry = []
        has_geometry = False
        for pol_nr, pp in enumerate(total_paint_geo, 1):
            QtWidgets.QApplication.processEvents()
            if self.app.abort_flag:
                raise grace
            geo_res = MillingGen.clear_excellon_polygon(
                pp, mill_dia, over, conn, circle_steps, self.clear_polygon_seed)
            if geo_res:
                has_geometry = True
                # Retain paths, not every feature's RTree index, until the tool finishes.
                total_geometry.extend(geo_res.get_objects())
            disp_number = int(np.interp(pol_nr, [0, geo_len], [0, 100]))
            if old_disp_number < disp_number <= 100:
                self.app.proc_container.update_view_text(' %d%%' % disp_number)
                old_disp_number = disp_number
        if not has_geometry:
            self.app.log.debug("The tools does not have a suitable geometry for milling.")
            return
        return [g for g in total_geometry if g and not g.is_empty]

    def on_generate_cnc_from_geo(self):
        self.app.log.debug("Generating CNCJob from Geometry ...")

        self.sel_tools.clear()

        self.obj_name = self.ui.object_combo.currentText()

        # Get source object.
        try:
            self.target_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(self.obj_name)))
            return "Could not retrieve object: %s with error: %s" % (self.obj_name, str(e))

        if self.target_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(self.obj_name)))
            return

        try:
            if self.target_obj.special_group:
                msg = '[WARNING_NOTCL] %s %s %s.' % \
                      (
                          _("This Geometry can't be processed because it is"),
                          str(self.target_obj.special_group),
                          _("Geometry")
                      )
                self.app.inform.emit(msg)
                return
        except AttributeError:
            pass

        # test to see if we have tools available in the tool table
        if self.ui.tools_table_mill_geo.selectedItems():
            # Execute in visible row order, including any explicit user reordering.
            rows = sorted(set(x.row() for x in self.ui.tools_table_mill_geo.selectedItems()))
            for row in rows:
                tooluid = int(self.ui.tools_table_mill_geo.item(row, 3).text())

                for tooluid_key, tooluid_value in self.target_obj.tools.items():
                    if int(tooluid_key) == tooluid:
                        self.sel_tools.update({
                            tooluid: deepcopy_keep_geometry(tooluid_value)
                        })

            self.generate_cnc_job_handler()
            # self.ui.tools_table_mill_geo.clearSelection()

        elif self.ui.tools_table_mill_geo.rowCount() == 1:
            tooluid = int(self.ui.tools_table_mill_geo.item(0, 3).text())

            for tooluid_key, tooluid_value in self.target_obj.tools.items():
                if int(tooluid_key) == tooluid:
                    self.sel_tools.update({
                        tooluid: deepcopy_keep_geometry(tooluid_value)
                    })
            self.generate_cnc_job_handler()
            # self.ui.tools_table_mill_geo.clearSelection()
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed. No tool selected in the tool table ..."))

        # for tooluid_key in list(self.sel_tools.keys()):
        #     # Tooldia update
        #     tooldia_val = self.app.dec_format(
        #         float(self.sel_tools[tooluid_key]['data']['tools_mill_tooldia']), self.decimals)
        #     print(tooldia_val)

    def generate_cnc_job_handler(self, geo_obj=None, outname=None, tools_dict=None, tools_in_use=None,
                                 seg_x=None, seg_y=None, toolchange=None, plot=True, use_thread=True,
                                 disable_offset=False, from_tcl=False):
        """
        Creates a multi-tool CNCJob out of this Geometry object.
        The actual work is done by the target CNCJobObject object's
        `generate_from_geometry_2()` method.

        :param geo_obj:         a Geometry object that is used as the parameter for this function
        :param toolchange:
        :param outname:
        :param tools_dict:      a dictionary that holds the whole data needed to create the Gcode
                                (including the solid_geometry)
        :param tools_in_use:    the tools that are used, needed by some preprocessors
        :type  tools_in_use     list of lists, each list in the list is made out of row elements of tools table from GUI
        :param seg_x:            number of segments on the X axis, for auto-levelling
        :param seg_y:            number of segments on the Y axis, for auto-levelling
        :param plot:            if True the generated object will be plotted; if False will not be plotted
        :param use_thread:      if True use threading
        :param disable_offset:  If True then the set offset for each tool will not be used
        :param from_tcl:        If True then the method is called by a Tcl command which does not use the UI
        :return:                None
        """

        self.app.log.debug("ToolMilling.generate_cnc_job_handler()")
        context = self._capture_cnc_job_context(
            geo_obj, outname, tools_dict, seg_x, seg_y, toolchange, disable_offset, from_tcl)
        if context is None:
            return
        return self._submit_cnc_job_creation(context, plot, use_thread)

    def _form_tool_data(self, obj, tooluid):
        """
        The tool data that the form shows. For a Geometry made by an older app version it is a copy with the missing
        options resolved as the CNC job resolves them; the tool data of the object is not changed.
        """
        tool = obj.tools[tooluid]
        if getattr(obj, 'kind', None) != 'geometry':
            return tool['data']
        tool = dict(tool, data=dict(tool['data']))
        # the CNC job gives the warning for a saved preprocessor that is not available
        self._complete_milling_tool_data({tooluid: tool}, tool_pp_used=False, warn=False)
        return tool['data']

    def _complete_milling_tool_data(self, tools_dict, tool_pp_used, warn=True):
        """Resolve missing legacy settings before the CNC job reads the tool data."""
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        missing_pp = set()
        for tool in tools_dict.values():
            data = tool['data']
            for key in AppDefaults.factory_defaults:
                if not key.startswith('tools_mill_') or key in data:
                    continue
                found, value = legacy_mill_value(tool, key)
                if found and key == 'tools_mill_ppname_g' and value not in self.app.preprocessors:
                    # a saved preprocessor that this app does not have (deleted, or a user preprocessor that is not
                    # installed) counts as absent
                    found = False
                    if warn and value not in missing_pp:
                        missing_pp.add(value)
                        self.app.log.warning("ToolMilling: the saved preprocessor %s is not available" % str(value))
                        if tool_pp_used:
                            self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (
                                _("The saved preprocessor is not available, the one from Preferences is used"), value))
                data[key] = value if found else deepcopy(self.app.options.get(
                    key, app_defaults.get(key, AppDefaults.factory_defaults.get(key))))

    def _capture_cnc_job_context(self, geo_obj, outname, tools_dict, seg_x, seg_y,
                                 toolchange, disable_offset, from_tcl):
        """Resolve GUI inputs on the submitting thread; keep the caller's tool storage shared."""
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        geo_obj = geo_obj if geo_obj is not None else self.target_obj
        source_obj = self.target_obj if isinstance(geo_obj, HybridGeoExc) else geo_obj

        # use the name of the first tool selected in self.tools_table_mill_geo which has the diameter passed as tool_dia
        outname = "%s_%s" % (geo_obj.obj_options["name"], 'cnc') if outname is None else outname

        tools_dict = self.sel_tools if tools_dict is None else tools_dict
        # Tcl jobs can reach this entry without opening the plugin. Multi-geometry plugin jobs use the form's
        # preprocessor, so only warn here when the resolved tool preprocessor will be used.
        self._complete_milling_tool_data(tools_dict, tool_pp_used=from_tcl or not geo_obj.multigeo)

        if not geo_obj.tools:
            seg_x = seg_x if seg_x is not None else float(geo_obj.obj_options['seg_x'])
            seg_y = seg_y if seg_y is not None else float(geo_obj.obj_options['seg_y'])
        else:
            tools_list = list(geo_obj.tools.keys())
            # the seg_x and seg_y values are the same for all tools os we just take the values from the first tool
            sel_tool = tools_list[0]
            data_dict = geo_obj.tools[sel_tool]['data']
            try:
                seg_x = data_dict['seg_x']
            except KeyError:
                try:
                    seg_x = data_dict['geometry_seg_x']
                except KeyError:
                    try:
                        seg_x = geo_obj.obj_options['seg_x']
                    except KeyError:
                        seg_x = self.app.options.get(
                            'geometry_seg_x',
                            app_defaults.get('geometry_seg_x', AppDefaults.factory_defaults.get('geometry_seg_x')))
            try:
                seg_y = data_dict['seg_y']
            except KeyError:
                try:
                    seg_y = data_dict['geometry_seg_y']
                except KeyError:
                    try:
                        seg_y = geo_obj.obj_options['seg_y']
                    except KeyError:
                        seg_y = self.app.options.get(
                            'geometry_seg_y',
                            app_defaults.get('geometry_seg_y', AppDefaults.factory_defaults.get('geometry_seg_y')))

        try:
            xmin = geo_obj.obj_options['xmin']
            ymin = geo_obj.obj_options['ymin']
            xmax = geo_obj.obj_options['xmax']
            ymax = geo_obj.obj_options['ymax']
        except Exception as e:
            self.app.log.error("FlatCAMObj.GeometryObject.mtool_gen_cncjob() --> %s\n" % str(e))

            msg = '[ERROR] %s' % _("An internal error has occurred. See shell.\n")
            msg += '%s' % str(e)
            msg += traceback.format_exc()
            self.app.inform.emit(msg)
            return

        options = {}
        for key in ('tools_mill_spindledir', 'cncjob_coords_decimals', 'cncjob_fr_decimals',
                    'global_tolerance', 'tools_mill_toolchange'):
            options[key] = self.app.options.get(
                key, app_defaults.get(key, AppDefaults.factory_defaults.get(key)))

        if toolchange is None:
            toolchange = options['tools_mill_toolchange'] if from_tcl else self.ui.toolchange_cb.get_value()
        overrides = {}
        if not from_tcl:
            fields = {'tools_mill_offset_value': 'offset_entry'}
            if geo_obj.multigeo:
                fields.update({
                    'tools_mill_toolchangez': 'toolchangez_entry',
                    'tools_mill_toolchangexy': 'toolchangexy_entry',
                    'tools_mill_endz': 'endz_entry', 'tools_mill_endxy': 'endxy_entry',
                    'tools_mill_z_p_depth': 'pdepth_entry', 'tools_mill_feedrate_probe': 'feedrate_probe_entry',
                    'tools_mill_area_exclusion': 'exclusion_cb', 'tools_mill_area_shape': 'area_shape_radio',
                    'tools_mill_area_strategy': 'strategy_radio', 'tools_mill_area_overz': 'over_z_entry',
                    'tools_mill_ppname_g': 'pp_geo_name_cb'})
            for key, widget in fields.items():
                if key == 'tools_mill_offset_value' and not any(
                        tool['data']['tools_mill_offset_type'] == 3 for tool in tools_dict.values()):
                    continue
                try:
                    overrides[key] = deepcopy(getattr(self.ui, widget).get_value())
                except AttributeError:
                    overrides[key] = False if key == 'tools_mill_area_exclusion' else deepcopy(
                        self.app.options.get(key, app_defaults.get(key, AppDefaults.factory_defaults.get(key))))

        return {
            'geo_obj': geo_obj, 'source_obj': source_obj, 'outname': outname, 'tools_dict': tools_dict,
            'multigeo': geo_obj.multigeo, 'used_tools': list(tools_dict),
            'bounds': {'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax},
            'seg_x': seg_x, 'seg_y': seg_y, 'toolchange': toolchange,
            'disable_offset': disable_offset, 'from_tcl': from_tcl,
            'overrides': overrides, 'options': options, 'decimals': self.decimals,
            'circle_steps': getattr(self, 'circle_steps', None),
            'units': self.units,
            'geo_options': {key: geo_obj.obj_options[key] for key in
                            ('tools_mill_z_p_depth', 'tools_mill_feedrate_probe', 'tools_mill_optimization_type')
                            if key in geo_obj.obj_options}}

    def _initialize_single_geometry_cnc_job(self, new_cncjob_obj, app_obj, context):
        self.app.log.debug("Creating a CNCJob out of a single-geometry")
        assert new_cncjob_obj.kind == 'cncjob', "Initializer expected a CNCJobObject, got %s" % type(new_cncjob_obj)
        geo_obj, tools_dict = context['geo_obj'], context['tools_dict']
        new_cncjob_obj.obj_options.update(context['bounds'])
        new_cncjob_obj.multitool = True
        new_cncjob_obj.multigeo = False
        new_cncjob_obj.tools.clear()
        new_cncjob_obj.seg_x = context['seg_x']
        new_cncjob_obj.seg_y = context['seg_y']
        new_cncjob_obj.z_p_depth = float(context['geo_options']['tools_mill_z_p_depth'])
        new_cncjob_obj.feedrate_probe = float(context['geo_options']['tools_mill_feedrate_probe'])
        used_tools = context['used_tools']
        new_cncjob_obj.used_tools = used_tools
        total_gcode = ''
        for tool_cnt, tool_uid_key in enumerate(used_tools, 1):
            data = tools_dict[tool_uid_key]['data']
            dia_cnc_dict = deepcopy_keep_geometry(tools_dict[tool_uid_key])
            tooldia_val = app_obj.dec_format(float(data['tools_mill_tooldia']), context['decimals'])
            dia_cnc_dict['data']['tools_mill_tooldia'] = tooldia_val
            if "optimization_type" not in data:
                data['tools_mill_optimization_type'] = context['geo_options']['tools_mill_optimization_type']

            offset_type = dia_cnc_dict['data']['tools_mill_offset_type']
            tool_offset = MillingGen.milling_offset(offset_type, tooldia_val, 0.0)
            if offset_type == 3:
                offset_value = data['tools_mill_offset_value'] if context['from_tcl'] else \
                    context['overrides']['tools_mill_offset_value']
                try:
                    offset_value = float(offset_value)
                except ValueError:
                    try:
                        offset_value = float(offset_value.replace(',', '.'))
                    except ValueError:
                        app_obj.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                        return
                if offset_value:
                    tool_offset = MillingGen.milling_offset(offset_type, tooldia_val, offset_value)
                else:
                    app_obj.inform.emit(
                        '[WARNING] %s' % _("Tool Offset is selected in Tool Table but no value is provided.\n"
                                           "Add a Tool Offset or change the Offset Type."))
                    return
            if context['disable_offset'] is True:
                tool_offset = 0.0
            dia_cnc_dict['data']['tools_mill_offset_value'] = tool_offset
            tool_solid_geometry = geo_obj.solid_geometry
            new_cncjob_obj.coords_decimals = context['options']['cncjob_coords_decimals']
            new_cncjob_obj.fr_decimals = context['options']['cncjob_fr_decimals']
            new_cncjob_obj.obj_options['tooldia'] = tooldia_val
            new_cncjob_obj.obj_options['type'] = 'Geometry'
            new_cncjob_obj.obj_options['tool_dia'] = tooldia_val

            glob_tol = float(context['options']['global_tolerance'])
            tol = glob_tol / 20 if context['units'].lower() == 'in' else glob_tol
            # append=False: the returned G-code (and the parsed one below) holds only this tool
            # on failure the result is the bare 'fail' string, not a (gcode, start_gcode) pair
            gen = new_cncjob_obj.generate_from_geometry_2(
                geo_obj, append=False, tooldia=tooldia_val, offset=tool_offset, tolerance=tol,
                z_cut=data['tools_mill_cutz'], z_move=data['tools_mill_travelz'],
                feedrate=data['tools_mill_feedrate'], feedrate_z=data['tools_mill_feedrate_z'],
                feedrate_rapid=data['tools_mill_feedrate_rapid'], spindlespeed=data['tools_mill_spindlespeed'],
                spindle_dir=context['options']['tools_mill_spindledir'],
                dwell=data['tools_mill_dwell'], dwelltime=data['tools_mill_dwelltime'],
                laser_min_power=data['tools_mill_min_power'], laser_on_code=data['tools_mill_laser_on'],
                multidepth=data['tools_mill_multidepth'], depthpercut=data['tools_mill_depthperpass'],
                extracut=data['tools_mill_extracut'], extracut_length=data['tools_mill_extracut_length'],
                startz=data['tools_mill_startz'], endz=data['tools_mill_endz'], endxy=data['tools_mill_endxy'],
                toolchange=data['tools_mill_toolchange'], toolchangez=data['tools_mill_toolchangez'],
                toolchangexy=data['tools_mill_toolchangexy'], pp_geometry_name=data['tools_mill_ppname_g'],
                tool_no=tool_cnt, is_first=tool_uid_key == used_tools[0])
            if gen == 'fail':
                self.app.log.debug("GeometryObject.mtool_gen_cncjob() --> generate_from_geometry2() failed")
                return 'fail'
            res, start_gcode = gen
            dia_cnc_dict['gcode'] = res
            if start_gcode != '':
                new_cncjob_obj.gc_start = start_gcode
            total_gcode += res
            self.app.inform.emit('[success] %s' % _("G-Code parsing in progress..."))
            dia_cnc_dict['gcode_parsed'] = new_cncjob_obj.gcode_parse(tool_data=data)
            app_obj.inform.emit('[success] %s' % _("G-Code parsing finished..."))
            try:
                dia_cnc_dict['solid_geometry'] = tool_solid_geometry
                app_obj.inform.emit('[success] %s...' % _("Finished G-Code processing"))
            except Exception as er:
                app_obj.inform.emit('[ERROR] %s: %s' % (_("G-Code processing failed with error"), str(er)))
            new_cncjob_obj.tools.update({tool_uid_key: deepcopy_keep_geometry(dia_cnc_dict)})
            dia_cnc_dict.clear()
        # the job itself keeps the G-code of all the tools, as before
        new_cncjob_obj.gcode = total_gcode
        if len(used_tools) > 1:
            new_cncjob_obj.gcode_parse(tool_data=data)
        new_cncjob_obj.source_file = new_cncjob_obj.gc_start + total_gcode

    def _initialize_multi_geometry_cnc_job(self, new_cncjob_obj, app_obj, context):
        self.app.log.debug("Creating a CNCJob out of a multi-geometry")
        assert new_cncjob_obj.kind == 'cncjob', "Initializer expected a CNCJobObject, got %s" % type(new_cncjob_obj)
        geo_obj, tools_dict = context['geo_obj'], context['tools_dict']
        new_cncjob_obj.obj_options.update(context['bounds'])
        new_cncjob_obj.multitool = True
        new_cncjob_obj.multigeo = True
        new_cncjob_obj.tools.clear()
        new_cncjob_obj.seg_x = context['seg_x']
        new_cncjob_obj.seg_y = context['seg_y']
        new_cncjob_obj.z_p_depth = float(context['geo_options']['tools_mill_z_p_depth'])
        new_cncjob_obj.feedrate_probe = float(context['geo_options']['tools_mill_feedrate_probe'])

        if not geo_obj.solid_geometry:
            if all(tool['solid_geometry'] is None for tool in geo_obj.tools.values()):
                app_obj.inform.emit('[ERROR_NOTCL] %s...' % _('Cancelled. Empty file, it has no geometry'))
                return 'fail'
        new_cncjob_obj.tools.update(tools_dict)
        used_tools = context['used_tools']
        new_cncjob_obj.used_tools = used_tools
        total_gcode = ''
        for tool_uid_key in used_tools:
            data = tools_dict[tool_uid_key]['data']
            dia_cnc_dict = deepcopy_keep_geometry(tools_dict[tool_uid_key])
            tooldia_val = app_obj.dec_format(float(data['tools_mill_tooldia']), context['decimals'])
            dia_cnc_dict['data']['tools_mill_tooldia'] = tooldia_val
            if "optimization_type" not in data:
                data['tools_mill_optimization_type'] = context['geo_options']['tools_mill_optimization_type']

            if data['tools_mill_job_type'] == 3:   # Polishing
                self.app.log.debug("Painting the polished area ...")
                margin = data['tools_mill_polish_margin']
                overlap = data['tools_mill_polish_overlap'] / 100
                paint_method = data['tools_mill_polish_method']
                bounds = context['bounds']
                bbox = MillingGen.polishing_area(bounds, margin, make_box=box)
                try:
                    QtWidgets.QApplication.processEvents()
                    if self.app.abort_flag:
                        raise grace
                    paint_geo = MillingGen.polishing_geometry(
                        bbox, tooldia_val, context['circle_steps'], overlap, paint_method,
                        self.clear_polygon_shrink, self.clear_polygon_seed, self.clear_polygon_lines)
                    if paint_geo is None:
                        self.app.inform.emit('[ERROR_NOTCL] %s' % _('Geometry could not be painted completely'))
                        return
                except grace:
                    return "fail"
                except Exception as ero:
                    self.app.log.error("Could not Paint the polygons. %s" % str(ero))
                    mssg = '[ERROR] %s\n%s' % (_("Could not do Paint. Try a different combination of parameters. "
                                                 "Or a different method of Paint"), str(ero))
                    self.app.inform.emit(mssg)
                    return
                tools_dict[tool_uid_key]['solid_geometry'] = paint_geo
                self.app.log.debug("Finished painting the polished area ...")

            # Keep the original shared-storage updates after the per-tool copy and polishing.
            data.update({key: value for key, value in context['overrides'].items()
                         if key != 'tools_mill_offset_value'})
            offset_type = dia_cnc_dict['data']['tools_mill_offset_type']
            tool_offset = MillingGen.milling_offset(offset_type, tooldia_val, 0.0)
            if offset_type == 3:
                offset_value = data['tools_mill_offset_value'] if context['from_tcl'] else \
                    context['overrides']['tools_mill_offset_value']
                if offset_value:
                    tool_offset = MillingGen.milling_offset(offset_type, tooldia_val, offset_value)
                else:
                    self.app.inform.emit('[WARNING] %s' %
                                         _("Tool Offset is selected in Tool Table but "
                                           "no value is provided.\n"
                                           "Add a Tool Offset or change the Offset Type."))
                    return
            if context['disable_offset'] is True:
                tool_offset = 0.0
            dia_cnc_dict['data']['tools_mill_offset_value'] = tool_offset
            data['tools_mill_offset_value'] = tool_offset
            tool_solid_geometry = geo_obj.tools[tool_uid_key]['solid_geometry']
            new_cncjob_obj.coords_decimals = context['options']['cncjob_coords_decimals']
            new_cncjob_obj.fr_decimals = context['options']['cncjob_fr_decimals']
            new_cncjob_obj.obj_options['tooldia'] = tooldia_val
            new_cncjob_obj.obj_options['type'] = 'Geometry'
            new_cncjob_obj.obj_options['tool_dia'] = tooldia_val
            glob_tol = float(context['options']['global_tolerance'])
            tol = glob_tol / 20 if context['units'].lower() == 'in' else glob_tol
            gen = new_cncjob_obj.geometry_tool_gcode_gen(
                tool_uid_key, tools_dict, first_pt=(0, 0), last_pt=data['tools_mill_endxy'],
                tolerance=tol, is_first=tool_uid_key == used_tools[0],
                is_last=tool_uid_key == used_tools[-1], toolchange=context['toolchange'],
                use_ui=not context['from_tcl'])
            if gen == 'fail':
                self.app.log.debug("ToolMilling.generate_cnc_job_handler() --> "
                                   "Failed to generate GCode for tool: %s" % tool_uid_key)
                return 'fail'
            res, start_gcode = gen
            dia_cnc_dict['gcode'] = res
            total_gcode += res
            if start_gcode != '':
                new_cncjob_obj.gc_start = start_gcode
            app_obj.inform.emit('[success] %s' % _("G-Code parsing in progress..."))
            dia_cnc_dict['gcode_parsed'] = new_cncjob_obj.gcode_parse(tool_data=data)
            app_obj.inform.emit('[success] %s' % _("G-Code parsing finished..."))
            try:
                dia_cnc_dict['solid_geometry'] = deepcopy_keep_geometry(tool_solid_geometry)
                app_obj.inform.emit('[success] %s...' % _("Finished G-Code processing"))
            except Exception as ee:
                app_obj.inform.emit('[ERROR] %s: %s' % (_("G-Code processing failed with error"), str(ee)))
            new_cncjob_obj.tools.update({tool_uid_key: deepcopy_keep_geometry(dia_cnc_dict)})
            dia_cnc_dict.clear()
        new_cncjob_obj.source_file = total_gcode

    def _submit_cnc_job_creation(self, context, plot, use_thread):
        initializer = self._initialize_multi_geometry_cnc_job if context['multigeo'] else \
            self._initialize_single_geometry_cnc_job

        def job_init(new_cncjob_obj, app_obj):
            return initializer(new_cncjob_obj, app_obj, context)

        def create_job():
            return self.new_object("cncjob", context['outname'], job_init,
                                   source=context['source_obj'], from_tcl=context['from_tcl'],
                                   plot=plot, autoselected=True)

        if use_thread:
            def job_thread(a_obj):
                with self.app.proc_container.new('%s...' % _("Generating")):
                    ret_value = create_job()
                if ret_value != 'fail':
                    a_obj.inform.emit('[success] %s: %s' % (_("CNCjob created"), context['outname']))

            self.app.collection.promise(context['outname'])
            self.app.worker_task.emit({'fcn': job_thread, 'params': [self.app]})
        else:
            ret_val = create_job()
            if ret_val != 'fail':
                self.app.inform.emit('[success] %s: %s' % (_("CNCjob created"), context['outname']))
            return 'fail' if ret_val == 'fail' or ret_val is False else None

    def on_pp_changed(self):
        current_pp = self.ui.pp_geo_name_cb.get_value()
        self.ui.on_pp_changed(current_pp, self.ui.level.isChecked())

    def on_plot_cb_click(self):
        self.target_obj.plot()

        self.ui_disconnect()
        cb_flag = self.ui.plot_cb.isChecked()
        for row in range(self.ui.tools_table_mill_geo.rowCount()):
            table_cb = self.ui.tools_table_mill_geo.cellWidget(row, 4)
            if cb_flag:
                table_cb.setChecked(True)
            else:
                table_cb.setChecked(False)
        self.ui_connect()

    def on_plot_cb_click_table(self):
        # self.ui.cnc_tools_table.cellWidget(row, 2).widget().setCheckState(QtCore.Qt.Unchecked)
        self.ui_disconnect()
        # cw = self.sender()
        # cw_index = self.ui.tools_table_mill_geo.indexAt(cw.pos())
        # cw_row = cw_index.row()
        check_row = 0

        self.target_obj.shapes.clear(update=True)

        for tooluid_key in self.target_obj.tools:
            solid_geometry = self.target_obj.tools[tooluid_key]['solid_geometry']

            # find the geo_plugin_table row associated with the tooluid_key
            for row in range(self.ui.tools_table_mill_geo.rowCount()):
                tooluid_item = int(self.ui.tools_table_mill_geo.item(row, 3).text())
                if tooluid_item == int(tooluid_key):
                    check_row = row
                    break

            if self.ui.tools_table_mill_geo.cellWidget(check_row, 4).isChecked():
                try:
                    color = self.target_obj.tools[tooluid_key]['data']['override_color']
                    self.target_obj.plot_element(element=solid_geometry, visible=True, color=color)
                except KeyError:
                    self.target_obj.plot_element(element=solid_geometry, visible=True)
        self.target_obj.shapes.redraw()

        # make sure that the general plot is disabled if one of the row plots are disabled and
        # if all the row plots are enabled also enable the general plot checkbox
        cb_cnt = 0
        total_row = self.ui.tools_table_mill_geo.rowCount()
        for row in range(total_row):
            if self.ui.tools_table_mill_geo.cellWidget(row, 4).isChecked():
                cb_cnt += 1
            else:
                cb_cnt -= 1
        # if cb_cnt == total_row:
        #     self.ui.plot_cb.setChecked(True)
        # elif cb_cnt == 0:
        #     self.ui.plot_cb.setChecked(False)
        self.ui_connect()

    def on_key_press(self, event):
        # modifiers = QtWidgets.QApplication.keyboardModifiers()

        # events out of the self.app.collection view (it's about Project Tab) are of type int
        if isinstance(event, int):
            key = event
        # events from the GUI are of type QKeyEvent
        elif isinstance(event, QtGui.QKeyEvent):
            key = event.key()

        # events from Vispy are of type KeyEvent
        else:
            key = event.key

        if key == QtCore.Qt.Key.Key_Escape or key == 'Escape':
            self.points = []
            self.poly_drawn = False
            self.delete_moving_selection_shape()
            self.delete_tool_selection_shape()

    def on_add_area_click(self):
        shape_button = self.ui.area_shape_radio
        overz_button = self.ui.over_z_entry
        strategy_radio = self.ui.strategy_radio
        cnc_button = self.ui.generate_cnc_button
        solid_geo = self.target_obj.solid_geometry
        obj_type = self.target_obj.kind

        self.app.exc_areas.on_add_area_click(
            shape_button=shape_button, overz_button=overz_button, cnc_button=cnc_button, strategy_radio=strategy_radio,
            solid_geo=solid_geo, obj_type=obj_type)

    def on_clear_area_click(self):
        if not self.app.exc_areas.exclusion_areas_storage:
            self.app.inform.emit("[WARNING_NOTCL] %s" % _("Delete failed. There are no exclusion areas to delete."))
            return

        self.app.exc_areas.on_clear_area_click()
        self.app.exc_areas.e_shape_modified.emit()

    def on_delete_sel_areas(self):
        sel_model = self.ui.exclusion_table.selectionModel()
        sel_indexes = sel_model.selectedIndexes()

        # it will iterate over all indexes which means all items in all columns too, but I'm interested only on rows
        # so the duplicate rows will not be added
        sel_rows = set()
        for idx in sel_indexes:
            sel_rows.add(idx.row())

        if not sel_rows:
            self.app.inform.emit("[WARNING_NOTCL] %s" % _("Delete failed. Nothing is selected."))
            return

        self.app.exc_areas.delete_sel_shapes(idxs=list(sel_rows))
        self.app.exc_areas.e_shape_modified.emit()

    def on_copy_exclusion_area_coords(self):
        sel_model = self.ui.exclusion_table.selectionModel()
        sel_indexes = sel_model.selectedIndexes()

        # it will iterate over all indexes which means all items in all columns too, but I'm interested only on rows
        # so the duplicate rows will not be added
        sel_rows = set()
        for idx in sel_indexes:
            sel_rows.add(idx.row())

        if len(sel_rows) != 1:
            self.app.inform.emit("[WARNING_NOTCL] %s" % _("Only one selected row is allowed."))
            return

        row_idx = list(sel_rows)[0]
        poly = self.app.exc_areas.exclusion_areas_storage[row_idx]['shape']
        poly_coords = list(poly.exterior.coords)

        self.app.clipboard.setText(str(poly_coords))
        self.app.inform.emit('[success] %s' % _("Copied to clipboard."))

    def draw_sel_shape(self):
        sel_model = self.ui.exclusion_table.selectionModel()
        sel_indexes = sel_model.selectedIndexes()

        # it will iterate over all indexes which means all items in all columns too, but I'm interested only on rows
        sel_rows = set()
        for idx in sel_indexes:
            sel_rows.add(idx.row())

        self.delete_sel_shape()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        face = self.app.options.get(
            'global_sel_fill', app_defaults.get('global_sel_fill', AppDefaults.factory_defaults.get('global_sel_fill')))[:-2] \
            + str(hex(int(0.2 * 255)))[2:]
        outline = self.app.options.get(
            'global_sel_line', app_defaults.get('global_sel_line', AppDefaults.factory_defaults.get('global_sel_line')))[:-2] \
            + str(hex(int(0.8 * 255)))[2:]

        for row in sel_rows:
            sel_rect = self.app.exc_areas.exclusion_areas_storage[row]['shape']
            self.app.sel_shapes.add(sel_rect, color=outline, face_color=face, update=True, layer=0, tolerance=None)
        self.app.sel_shapes.redraw()

    def clear_selection(self):
        self.app.delete_selection_shape()
        # self.ui.exclusion_table.clearSelection()

    def delete_sel_shape(self):
        self.app.delete_selection_shape()

    def update_exclusion_table(self):
        self.exclusion_area_cb_is_checked = True if self.ui.exclusion_cb.isChecked() else False

        self.build_ui()
        self.ui.exclusion_cb.set_value(self.exclusion_area_cb_is_checked)

    def on_strategy(self, val):
        if val == 'around':
            self.ui.over_z_label.setDisabled(True)
            self.ui.over_z_entry.setDisabled(True)
        else:
            self.ui.over_z_label.setDisabled(False)
            self.ui.over_z_entry.setDisabled(False)

    def exclusion_table_toggle_all(self):
        """
        will toggle the selection of all rows in Exclusion Areas table

        :return:
        """
        sel_model = self.ui.exclusion_table.selectionModel()
        sel_indexes = sel_model.selectedIndexes()

        # it will iterate over all indexes which means all items in all columns too, but I'm interested only on rows
        sel_rows = set()
        for idx in sel_indexes:
            sel_rows.add(idx.row())

        if sel_rows:
            self.ui.exclusion_table.clearSelection()
            self.delete_sel_shape()
        else:
            self.ui.exclusion_table.selectAll()
            self.draw_sel_shape()

    def on_exclusion_table_overz(self, current_item):
        self.ui_disconnect()

        current_row = current_item.row()
        try:
            d = float(self.ui.exclusion_table.item(current_row, 3).text())
        except ValueError:
            # try to convert comma to decimal point. if it's still not working error message and return
            try:
                d = float(self.ui.exclusion_table.item(current_row, 3).text().replace(',', '.'))
            except ValueError:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                return
        except AttributeError:
            self.ui_connect()
            return

        overz = self.app.dec_format(d, self.decimals)
        idx = int(self.ui.exclusion_table.item(current_row, 0).text())

        for area_dict in self.app.exc_areas.exclusion_areas_storage:
            if area_dict['idx'] == idx:
                area_dict['overz'] = overz

        self.app.inform.emit('[success] %s' % _("Value edited in Exclusion Table."))
        self.ui_connect()
        self.build_ui_sig.emit()

    def on_exclusion_table_strategy(self):
        cw = self.sender()
        cw_index = self.ui.exclusion_table.indexAt(cw.pos())
        cw_row = cw_index.row()
        idx = int(self.ui.exclusion_table.item(cw_row, 0).text())

        for area_dict in self.app.exc_areas.exclusion_areas_storage:
            if area_dict['idx'] == idx:
                strategy = self.ui.exclusion_table.cellWidget(cw_row, 2).currentIndex()
                area_dict['strategy'] = "around" if strategy == 0 else 'overz'

        self.app.inform.emit('[success] %s' % _("Value edited in Exclusion Table."))
        self.ui_connect()
        self.build_ui_sig.emit()

    def reset_fields(self):
        self.ui.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
