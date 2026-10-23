# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 09/27/2019                                         #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from appObjects import GerberObject
from defaults import AppDefaults
from appPlugins.ToolRulesCheck import RulesCheckGen
from appPlugins.ToolRulesCheck.RulesCheckUI import RulesUI, render_report

import logging
from copy import deepcopy

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class RulesCheck(AppTool):

    tool_finished = QtCore.pyqtSignal(list)

    def __init__(self, app):
        self.decimals = app.decimals

        AppTool.__init__(self, app)

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = RulesUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # list to hold the temporary objects
        self.objs = []

        # final name for the panel object
        self.outname = ""

        # flag to signal that the constraint was activated
        self.constrain_flag = False

        # Multiprocessing Process Pool
        self.pool = self.app.pool
        self.results = None

        self.decimals = 4

    # def on_object_loaded(self, index, row):
    #     print(index.internalPointer().child_items[row].obj.obj_options['name'], index.data())

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolRulesCheck()")

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

        super().run()
        self.set_tool_ui()

        self.app.ui.notebook.setTabText(2, _("Check Rules"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+R', **kwargs)

    def connect_signals_at_init(self):
        self.ui.copper_t_cb.stateChanged.connect(lambda st: self.ui.copper_t_object.setDisabled(not st))
        self.ui.copper_b_cb.stateChanged.connect(lambda st: self.ui.copper_b_object.setDisabled(not st))

        self.ui.sm_t_cb.stateChanged.connect(lambda st: self.ui.sm_t_object.setDisabled(not st))
        self.ui.sm_b_cb.stateChanged.connect(lambda st: self.ui.sm_b_object.setDisabled(not st))

        self.ui.ss_t_cb.stateChanged.connect(lambda st: self.ui.ss_t_object.setDisabled(not st))
        self.ui.ss_b_cb.stateChanged.connect(lambda st: self.ui.ss_b_object.setDisabled(not st))

        self.ui.out_cb.stateChanged.connect(lambda st: self.ui.outline_object.setDisabled(not st))

        self.ui.e1_cb.stateChanged.connect(lambda st: self.ui.e1_object.setDisabled(not st))
        self.ui.e2_cb.stateChanged.connect(lambda st: self.ui.e2_object.setDisabled(not st))

        self.ui.run_button.clicked.connect(self.execute)

        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        # Custom Signals
        self.tool_finished.connect(self.on_tool_finished)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = RulesUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # all object combobox default as disabled
        self.ui.copper_t_object.setDisabled(True)
        self.ui.copper_b_object.setDisabled(True)

        self.ui.sm_t_object.setDisabled(True)
        self.ui.sm_b_object.setDisabled(True)

        self.ui.ss_t_object.setDisabled(True)
        self.ui.ss_b_object.setDisabled(True)

        self.ui.outline_object.setDisabled(True)

        self.ui.e1_object.setDisabled(True)
        self.ui.e2_object.setDisabled(True)

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.ui.trace_size_cb.set_value(self.app.options.get(
            "tools_cr_trace_size", app_defaults.get("tools_cr_trace_size", AppDefaults.factory_defaults.get("tools_cr_trace_size"))))
        self.ui.trace_size_entry.set_value(float(self.app.options.get(
            "tools_cr_trace_size_val", app_defaults.get("tools_cr_trace_size_val", AppDefaults.factory_defaults.get("tools_cr_trace_size_val")))))
        self.ui.clearance_copper2copper_cb.set_value(self.app.options.get(
            "tools_cr_c2c", app_defaults.get("tools_cr_c2c", AppDefaults.factory_defaults.get("tools_cr_c2c"))))
        self.ui.clearance_copper2copper_entry.set_value(float(self.app.options.get(
            "tools_cr_c2c_val", app_defaults.get("tools_cr_c2c_val", AppDefaults.factory_defaults.get("tools_cr_c2c_val")))))
        self.ui.clearance_copper2ol_cb.set_value(self.app.options.get(
            "tools_cr_c2o", app_defaults.get("tools_cr_c2o", AppDefaults.factory_defaults.get("tools_cr_c2o"))))
        self.ui.clearance_copper2ol_entry.set_value(float(self.app.options.get(
            "tools_cr_c2o_val", app_defaults.get("tools_cr_c2o_val", AppDefaults.factory_defaults.get("tools_cr_c2o_val")))))
        self.ui.clearance_silk2silk_cb.set_value(self.app.options.get(
            "tools_cr_s2s", app_defaults.get("tools_cr_s2s", AppDefaults.factory_defaults.get("tools_cr_s2s"))))
        self.ui.clearance_silk2silk_entry.set_value(float(self.app.options.get(
            "tools_cr_s2s_val", app_defaults.get("tools_cr_s2s_val", AppDefaults.factory_defaults.get("tools_cr_s2s_val")))))
        self.ui.clearance_silk2sm_cb.set_value(self.app.options.get(
            "tools_cr_s2sm", app_defaults.get("tools_cr_s2sm", AppDefaults.factory_defaults.get("tools_cr_s2sm"))))
        self.ui.clearance_silk2sm_entry.set_value(float(self.app.options.get(
            "tools_cr_s2sm_val", app_defaults.get("tools_cr_s2sm_val", AppDefaults.factory_defaults.get("tools_cr_s2sm_val")))))
        self.ui.clearance_silk2ol_cb.set_value(self.app.options.get(
            "tools_cr_s2o", app_defaults.get("tools_cr_s2o", AppDefaults.factory_defaults.get("tools_cr_s2o"))))
        self.ui.clearance_silk2ol_entry.set_value(float(self.app.options.get(
            "tools_cr_s2o_val", app_defaults.get("tools_cr_s2o_val", AppDefaults.factory_defaults.get("tools_cr_s2o_val")))))
        self.ui.clearance_sm2sm_cb.set_value(self.app.options.get(
            "tools_cr_sm2sm", app_defaults.get("tools_cr_sm2sm", AppDefaults.factory_defaults.get("tools_cr_sm2sm"))))
        self.ui.clearance_sm2sm_entry.set_value(float(self.app.options.get(
            "tools_cr_sm2sm_val", app_defaults.get("tools_cr_sm2sm_val", AppDefaults.factory_defaults.get("tools_cr_sm2sm_val")))))
        self.ui.ring_integrity_cb.set_value(self.app.options.get(
            "tools_cr_ri", app_defaults.get("tools_cr_ri", AppDefaults.factory_defaults.get("tools_cr_ri"))))
        self.ui.ring_integrity_entry.set_value(float(self.app.options.get(
            "tools_cr_ri_val", app_defaults.get("tools_cr_ri_val", AppDefaults.factory_defaults.get("tools_cr_ri_val")))))
        self.ui.clearance_d2d_cb.set_value(self.app.options.get(
            "tools_cr_h2h", app_defaults.get("tools_cr_h2h", AppDefaults.factory_defaults.get("tools_cr_h2h"))))
        self.ui.clearance_d2d_entry.set_value(float(self.app.options.get(
            "tools_cr_h2h_val", app_defaults.get("tools_cr_h2h_val", AppDefaults.factory_defaults.get("tools_cr_h2h_val")))))
        self.ui.drill_size_cb.set_value(self.app.options.get(
            "tools_cr_dh", app_defaults.get("tools_cr_dh", AppDefaults.factory_defaults.get("tools_cr_dh"))))
        self.ui.drill_size_entry.set_value(float(self.app.options.get(
            "tools_cr_dh_val", app_defaults.get("tools_cr_dh_val", AppDefaults.factory_defaults.get("tools_cr_dh_val")))))

        self.reset_fields()

    @staticmethod
    def check_inside_gerber_clearance(gerber_obj, size, rule):
        return RulesCheckGen.check_inside_gerber_clearance(gerber_obj, size, rule)

    @staticmethod
    def check_gerber_clearance(gerber_list: list[GerberObject], size, rule):
        return RulesCheckGen.check_gerber_clearance(gerber_list, size, rule)

    @staticmethod
    def check_holes_size(elements, size):
        return RulesCheckGen.check_holes_size(elements, size, _("Hole Size"))

    @staticmethod
    def check_holes_clearance(elements, size):
        return RulesCheckGen.check_holes_clearance(elements, size, _("Hole to Hole Clearance"))

    @staticmethod
    def check_traces_size(elements, size):
        return RulesCheckGen.check_traces_size(elements, size, _("Trace Size"))

    @staticmethod
    def check_gerber_annular_ring(obj_list, size, rule):
        return RulesCheckGen.check_gerber_annular_ring(obj_list, size, rule)

    def execute(self):
        self.results = []

        self.app.log.debug("RuleCheck() executing")

        def worker_job(app_obj):
            # self.app.proc_container.new(_("Working..."))
            self.app.proc_container.view.set_busy('%s' % _("Working..."))

            # RULE: Check Trace Size
            if self.ui.trace_size_cb.get_value():
                copper_list = []
                copper_name_1 = self.ui.copper_t_object.currentText()
                if copper_name_1 != '' and self.ui.copper_t_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(copper_name_1),
                        'apertures': deepcopy(app_obj.collection.get_by_name(copper_name_1).tools)
                    }
                    copper_list.append(elem_dict)

                copper_name_2 = self.ui.copper_b_object.currentText()
                if copper_name_2 != '' and self.ui.copper_b_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(copper_name_2),
                        'apertures': deepcopy(app_obj.collection.get_by_name(copper_name_2).tools)
                    }
                    copper_list.append(elem_dict)

                trace_size = float(self.ui.trace_size_entry.get_value())
                self.results.append(self.pool.apply_async(self.check_traces_size, args=(copper_list, trace_size)))

            # RULE: Check Copper to Copper Clearance
            if self.ui.clearance_copper2copper_cb.get_value():

                try:
                    copper_copper_clearance = float(self.ui.clearance_copper2copper_entry.get_value())
                except Exception as e:
                    self.app.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    self.app.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Copper to Copper clearance"),
                        _("Value is not valid.")))
                    return

                if self.ui.copper_t_cb.get_value():
                    copper_t_obj = self.ui.copper_t_object.currentText()
                    copper_t_dict = {}

                    if copper_t_obj != '':
                        copper_t_dict['name'] = deepcopy(copper_t_obj)
                        copper_t_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_t_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(copper_t_dict,
                                                                        copper_copper_clearance,
                                                                        _("TOP -> Copper to Copper clearance"))))
                if self.ui.copper_b_cb.get_value():
                    copper_b_obj = self.ui.copper_b_object.currentText()
                    copper_b_dict = {}
                    if copper_b_obj != '':
                        copper_b_dict['name'] = deepcopy(copper_b_obj)
                        copper_b_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_b_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(copper_b_dict,
                                                                        copper_copper_clearance,
                                                                        _("BOTTOM -> Copper to Copper clearance"))))

                if self.ui.copper_t_cb.get_value() is False and self.ui.copper_b_cb.get_value() is False:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Copper to Copper clearance"),
                        _("At least one Gerber object has to be selected for this rule but none is selected.")))
                    return

            # RULE: Check Copper to Outline Clearance
            if self.ui.clearance_copper2ol_cb.get_value() and self.ui.out_cb.get_value():
                top_dict = {}
                bottom_dict = {}
                outline_dict = {}

                copper_top = self.ui.copper_t_object.currentText()
                if copper_top != '' and self.ui.copper_t_cb.get_value():
                    top_dict['name'] = deepcopy(copper_top)
                    top_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_top).tools)

                copper_bottom = self.ui.copper_b_object.currentText()
                if copper_bottom != '' and self.ui.copper_b_cb.get_value():
                    bottom_dict['name'] = deepcopy(copper_bottom)
                    bottom_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_bottom).tools)

                copper_outline = self.ui.outline_object.currentText()
                if copper_outline != '' and self.ui.out_cb.get_value():
                    outline_dict['name'] = deepcopy(copper_outline)
                    outline_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_outline).tools)

                try:
                    copper_outline_clearance = float(self.ui.clearance_copper2ol_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Copper to Outline clearance"),
                        _("Value is not valid.")))
                    return

                if not top_dict and not bottom_dict or not outline_dict:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Copper to Outline clearance"),
                        _("One of the copper Gerber objects or the Outline Gerber object is not valid.")))
                    return
                objs = []
                if top_dict:
                    objs.append(top_dict)
                if bottom_dict:
                    objs.append(bottom_dict)

                if outline_dict:
                    objs.append(outline_dict)
                else:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Copper to Outline clearance"),
                        _("Outline Gerber object presence is mandatory for this rule but it is not selected.")))
                    return

                self.results.append(self.pool.apply_async(self.check_gerber_clearance,
                                                          args=(objs,
                                                                copper_outline_clearance,
                                                                _("Copper to Outline clearance"))))

            # RULE: Check Silk to Silk Clearance
            if self.ui.clearance_silk2silk_cb.get_value():
                silk_dict = {}

                try:
                    silk_silk_clearance = float(self.ui.clearance_silk2silk_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Silk clearance"),
                        _("Value is not valid.")))
                    return

                if self.ui.ss_t_cb.get_value():
                    silk_obj = self.ui.ss_t_object.currentText()
                    if silk_obj != '':
                        silk_dict['name'] = deepcopy(silk_obj)
                        silk_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(silk_dict,
                                                                        silk_silk_clearance,
                                                                        _("TOP -> Silk to Silk clearance"))))
                if self.ui.ss_b_cb.get_value():
                    silk_obj = self.ui.ss_b_object.currentText()
                    if silk_obj != '':
                        silk_dict['name'] = deepcopy(silk_obj)
                        silk_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(silk_dict,
                                                                        silk_silk_clearance,
                                                                        _("BOTTOM -> Silk to Silk clearance"))))

                if self.ui.ss_t_cb.get_value() is False and self.ui.ss_b_cb.get_value() is False:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Silk clearance"),
                        _("At least one Gerber object has to be selected for this rule but none is selected.")))
                    return

            # RULE: Check Silk to Solder Mask Clearance
            if self.ui.clearance_silk2sm_cb.get_value():
                silk_t_dict = {}
                sm_t_dict = {}
                silk_b_dict = {}
                sm_b_dict = {}

                top_ss = False
                bottom_ss = False
                top_sm = False
                bottom_sm = False

                silk_top = self.ui.ss_t_object.currentText()
                if silk_top != '' and self.ui.ss_t_cb.get_value():
                    silk_t_dict['name'] = deepcopy(silk_top)
                    silk_t_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_top).tools)
                    top_ss = True

                silk_bottom = self.ui.ss_b_object.currentText()
                if silk_bottom != '' and self.ui.ss_b_cb.get_value():
                    silk_b_dict['name'] = deepcopy(silk_bottom)
                    silk_b_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_bottom).tools)
                    bottom_ss = True

                sm_top = self.ui.sm_t_object.currentText()
                if sm_top != '' and self.ui.sm_t_cb.get_value():
                    sm_t_dict['name'] = deepcopy(sm_top)
                    sm_t_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(sm_top).tools)
                    top_sm = True

                sm_bottom = self.ui.sm_b_object.currentText()
                if sm_bottom != '' and self.ui.sm_b_cb.get_value():
                    sm_b_dict['name'] = deepcopy(sm_bottom)
                    sm_b_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(sm_bottom).tools)
                    bottom_sm = True

                try:
                    silk_sm_clearance = float(self.ui.clearance_silk2sm_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Solder Mask Clearance"),
                        _("Value is not valid.")))
                    return

                if (not silk_t_dict and not silk_b_dict) or (not sm_t_dict and not sm_b_dict):
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Solder Mask Clearance"),
                        _("One or more of the Gerber objects is not valid.")))
                    return

                if top_ss is True and top_sm is True:
                    objs = [silk_t_dict, sm_t_dict]
                    self.results.append(self.pool.apply_async(self.check_gerber_clearance,
                                                              args=(objs,
                                                                    silk_sm_clearance,
                                                                    _("TOP -> Silk to Solder Mask Clearance"))))
                elif bottom_ss is True and bottom_sm is True:
                    objs = [silk_b_dict, sm_b_dict]
                    self.results.append(self.pool.apply_async(self.check_gerber_clearance,
                                                              args=(objs,
                                                                    silk_sm_clearance,
                                                                    _("BOTTOM -> Silk to Solder Mask Clearance"))))
                else:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Solder Mask Clearance"),
                        _("Both Silk and Solder Mask Gerber objects has to be either both Top or both Bottom.")))
                    return

            # RULE: Check Silk to Outline Clearance
            if self.ui.clearance_silk2ol_cb.get_value():
                top_dict = {}
                bottom_dict = {}
                outline_dict = {}

                silk_top = self.ui.ss_t_object.currentText()
                if silk_top != '' and self.ui.ss_t_cb.get_value():
                    top_dict['name'] = deepcopy(silk_top)
                    top_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_top).tools)

                silk_bottom = self.ui.ss_b_object.currentText()
                if silk_bottom != '' and self.ui.ss_b_cb.get_value():
                    bottom_dict['name'] = deepcopy(silk_bottom)
                    bottom_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(silk_bottom).tools)

                copper_outline = self.ui.outline_object.currentText()
                if copper_outline != '' and self.ui.out_cb.get_value():
                    outline_dict['name'] = deepcopy(copper_outline)
                    outline_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_outline).tools)

                try:
                    copper_outline_clearance = float(self.ui.clearance_copper2ol_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Outline Clearance"),
                        _("Value is not valid.")))
                    return

                if not top_dict and not bottom_dict or not outline_dict:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Outline Clearance"),
                        _("One of the Silk Gerber objects or the Outline Gerber object is not valid.")))
                    return

                objs = []
                if top_dict:
                    objs.append(top_dict)
                if bottom_dict:
                    objs.append(bottom_dict)

                if outline_dict:
                    objs.append(outline_dict)
                else:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Silk to Outline Clearance"),
                        _("Outline Gerber object presence is mandatory for this rule but it is not selected.")))
                    return

                self.results.append(self.pool.apply_async(self.check_gerber_clearance,
                                                          args=(objs,
                                                                copper_outline_clearance,
                                                                _("Silk to Outline Clearance"))))

            # RULE: Check Minimum Solder Mask Sliver
            if self.ui.clearance_silk2silk_cb.get_value():
                sm_dict = {}

                try:
                    sm_sm_clearance = float(self.ui.clearance_sm2sm_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Minimum Solder Mask Sliver"),
                        _("Value is not valid.")))
                    return

                if self.ui.sm_t_cb.get_value():
                    solder_obj = self.ui.sm_t_object.currentText()
                    if solder_obj != '':
                        sm_dict['name'] = deepcopy(solder_obj)
                        sm_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(solder_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(sm_dict,
                                                                        sm_sm_clearance,
                                                                        _("TOP -> Minimum Solder Mask Sliver"))))
                if self.ui.sm_b_cb.get_value():
                    solder_obj = self.ui.sm_b_object.currentText()
                    if solder_obj != '':
                        sm_dict['name'] = deepcopy(solder_obj)
                        sm_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(solder_obj).tools)

                        self.results.append(self.pool.apply_async(self.check_inside_gerber_clearance,
                                                                  args=(sm_dict,
                                                                        sm_sm_clearance,
                                                                        _("BOTTOM -> Minimum Solder Mask Sliver"))))

                if self.ui.sm_t_cb.get_value() is False and self.ui.sm_b_cb.get_value() is False:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Minimum Solder Mask Sliver"),
                        _("At least one Gerber object has to be selected for this rule but none is selected.")))
                    return

            # RULE: Check Minimum Annular Ring
            if self.ui.ring_integrity_cb.get_value():
                top_dict = {}
                bottom_dict = {}
                exc_1_dict = {}
                exc_2_dict = {}

                copper_top = self.ui.copper_t_object.currentText()
                if copper_top != '' and self.ui.copper_t_cb.get_value():
                    top_dict['name'] = deepcopy(copper_top)
                    top_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_top).tools)

                copper_bottom = self.ui.copper_b_object.currentText()
                if copper_bottom != '' and self.ui.copper_b_cb.get_value():
                    bottom_dict['name'] = deepcopy(copper_bottom)
                    bottom_dict['apertures'] = deepcopy(app_obj.collection.get_by_name(copper_bottom).tools)

                excellon_1 = self.ui.e1_object.currentText()
                if excellon_1 != '' and self.ui.e1_cb.get_value():
                    exc_1_dict['name'] = deepcopy(excellon_1)
                    exc_1_dict['tools'] = deepcopy(
                        app_obj.collection.get_by_name(excellon_1).tools)

                excellon_2 = self.ui.e2_object.currentText()
                if excellon_2 != '' and self.ui.e2_cb.get_value():
                    exc_2_dict['name'] = deepcopy(excellon_2)
                    exc_2_dict['tools'] = deepcopy(
                        app_obj.collection.get_by_name(excellon_2).tools)

                try:
                    ring_val = float(self.ui.ring_integrity_entry.get_value())
                except Exception as e:
                    app_obj.log.error("RulesCheck.execute.worker_job() --> %s" % str(e))
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Minimum Annular Ring"),
                        _("Value is not valid.")))
                    return

                if (not top_dict and not bottom_dict) or (not exc_1_dict and not exc_2_dict):
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Minimum Annular Ring"),
                        _("One of the Copper Gerber objects or the Excellon objects is not valid.")))
                    return

                objs = []
                if top_dict:
                    objs.append(top_dict)
                elif bottom_dict:
                    objs.append(bottom_dict)

                if exc_1_dict:
                    objs.append(exc_1_dict)
                elif exc_2_dict:
                    objs.append(exc_2_dict)
                else:
                    app_obj.inform.emit('[ERROR_NOTCL] %s. %s' % (
                        _("Minimum Annular Ring"),
                        _("Excellon object presence is mandatory for this rule but none is selected.")))
                    return

                self.results.append(self.pool.apply_async(self.check_gerber_annular_ring,
                                                          args=(objs,
                                                                ring_val,
                                                                _("Minimum Annular Ring"))))

            # RULE: Check Hole to Hole Clearance
            if self.ui.clearance_d2d_cb.get_value():
                exc_list = []
                exc_name_1 = self.ui.e1_object.currentText()
                if exc_name_1 != '' and self.ui.e1_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(exc_name_1),
                        'tools': deepcopy(app_obj.collection.get_by_name(exc_name_1).tools)
                    }
                    exc_list.append(elem_dict)

                exc_name_2 = self.ui.e2_object.currentText()
                if exc_name_2 != '' and self.ui.e2_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(exc_name_2),
                        'tools': deepcopy(app_obj.collection.get_by_name(exc_name_2).tools)
                    }
                    exc_list.append(elem_dict)

                hole_clearance = float(self.ui.clearance_d2d_entry.get_value())
                self.results.append(self.pool.apply_async(self.check_holes_clearance, args=(exc_list, hole_clearance)))

            # RULE: Check Holes Size
            if self.ui.drill_size_cb.get_value():
                exc_list = []
                exc_name_1 = self.ui.e1_object.currentText()
                if exc_name_1 != '' and self.ui.e1_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(exc_name_1),
                        'tools': deepcopy(app_obj.collection.get_by_name(exc_name_1).tools)
                    }
                    exc_list.append(elem_dict)

                exc_name_2 = self.ui.e2_object.currentText()
                if exc_name_2 != '' and self.ui.e2_cb.get_value():
                    elem_dict = {
                        'name': deepcopy(exc_name_2),
                        'tools': deepcopy(app_obj.collection.get_by_name(exc_name_2).tools)
                    }
                    exc_list.append(elem_dict)

                drill_size = float(self.ui.drill_size_entry.get_value())
                self.results.append(self.pool.apply_async(self.check_holes_size, args=(exc_list, drill_size)))

            output = []
            for p in self.results:
                output.append(p.get())

            self.tool_finished.emit(output)
            app_obj.proc_container.view.set_idle()

            self.app.log.debug("RuleCheck() finished")

        self.app.worker_task.emit({'fcn': worker_job, 'params': [self.app]})

    def on_tool_finished(self, res):
        def init(new_obj, app_obj):
            new_obj.source_file = render_report(res, self.decimals)
            new_obj.read_only = True

        self.new_object('document', name='Rules_check_results', initialize=init, plot=False)

    def reset_fields(self):
        # self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        # self.box_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        pass
