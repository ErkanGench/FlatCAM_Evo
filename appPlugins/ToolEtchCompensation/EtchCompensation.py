# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 2/14/2020                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from defaults import AppDefaults
from camlib import flatten_shapely_geometry
from appCommon.SafeEval import safe_eval
from appPlugins.ToolEtchCompensation.EtchCompensationUI import EtchUI
from appPlugins.ToolEtchCompensation.EtchCompensationGen import compensate_geometry
import appPlugins.ToolEtchCompensation as etch_plugin

import logging
from copy import deepcopy

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolEtchCompensation(AppTool):

    def __init__(self, app):
        self.app = app
        self.decimals = self.app.decimals

        AppTool.__init__(self, app)

        self.ui = etch_plugin.EtchUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='', **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolEtchCompensation()")
        self.app.log.debug("ToolEtchCompensation() is running ...")

        if toggle:
            # if the splitter is hidden, display it
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

            found_idx = None
            for idx in range(self.app.ui.notebook.count()):
                if self.app.ui.notebook.widget(idx).objectName() == "plugin_tab":
                    found_idx = idx
                    break
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
                self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)

            try:
                if self.app.ui.plugin_scroll_area.widget().objectName() == self.pluginName and found_idx:
                    if not self.app.ui.notebook.currentWidget() is self.app.ui.plugin_tab:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.plugin_tab)
                    else:
                        self.app.ui.notebook.setCurrentWidget(self.app.ui.properties_tab)
                        self.app.ui.notebook.removeTab(2)
                        if not self.app.collection.get_list():
                            self.app.ui.splitter.setSizes([0, 1])
            except AttributeError:
                pass
        else:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])

        super().run()
        self.set_tool_ui()
        self.app.ui.notebook.setTabText(2, _("Etch Compensation"))

    def connect_signals_at_init(self):
        self.ui.compensate_btn.clicked.connect(self.on_compensate)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)
        self.ui.ratio_radio.activated_custom.connect(self.on_ratio_change)
        self.ui.oz_entry.textChanged.connect(self.on_oz_conversion)
        self.ui.mils_entry.textChanged.connect(self.on_mils_conversion)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = etch_plugin.EtchUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.ui.thick_entry.set_value(18.0)
        self.ui.ratio_radio.set_value('factor')

        obj = self.app.collection.get_active()
        if obj and obj.kind == 'gerber':
            obj_name = obj.obj_options['name']
            self.ui.gerber_combo.set_value(obj_name)

    def on_ratio_change(self, val):
        self.ui.on_ratio_change(val)

    def on_oz_conversion(self, txt):
        try:
            val = safe_eval(txt)
            # oz thickness to mils, then mils to microns
            val *= 34.798
        except Exception:
            self.ui.oz_to_um_entry.set_value('')
            return
        self.ui.oz_to_um_entry.set_value(val, self.decimals)

    def on_mils_conversion(self, txt):
        try:
            val = safe_eval(txt)
            val *= 25.4
        except Exception:
            self.ui.mils_to_um_entry.set_value('')
            return
        self.ui.mils_to_um_entry.set_value(val, self.decimals)

    def on_compensate(self):
        self.app.log.debug("ToolEtchCompensation.on_compensate()")

        ratio_type = self.ui.ratio_radio.get_value()
        thickness = self.ui.thick_entry.get_value() / 1000     # in microns

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        grb_circle_steps = int(self.app.options.get(
            "gerber_circle_steps",
            app_defaults.get("gerber_circle_steps", AppDefaults.factory_defaults.get("gerber_circle_steps"))
        ))
        obj_name = self.ui.gerber_combo.currentText()
        outname = obj_name + "_comp"

        try:
            grb_obj = self.app.collection.get_by_name(obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), str(obj_name)))
            return "Could not retrieve object: %s with error: %s" % (obj_name, str(e))

        if grb_obj is None:
            if obj_name == '':
                obj_name = 'None'
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(obj_name)))
            return

        if ratio_type == 'factor':
            factor_value = self.ui.factor_entry.get_value()
            if factor_value is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Missing parameter value."))
                return
            etch_factor = 1 / factor_value
            offset = thickness / etch_factor
        elif ratio_type == 'etch_list':
            etchant = self.ui.etchants_combo.get_value()
            if etchant == "CuCl2":
                etch_factor = 0.33
            else:
                etch_factor = 0.25
            offset = thickness / etch_factor
        else:
            offset_value = self.ui.offset_entry.get_value()
            if offset_value is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Missing parameter value."))
                return
            offset = offset_value / 1000   # in microns

        if offset == 0:
            return

        grb_obj.solid_geometry = flatten_shapely_geometry(grb_obj.solid_geometry)
        new_solid_geometry, new_apertures = compensate_geometry(
            grb_obj.solid_geometry, grb_obj.tools, offset, grb_circle_steps)

        new_options = {}
        for opt in grb_obj.obj_options:
            new_options[opt] = deepcopy(grb_obj.obj_options[opt])

        def init_func(new_obj, app_obj):
            new_obj.obj_options.update(new_options)
            new_obj.obj_options['name'] = outname
            new_obj.fill_color = deepcopy(grb_obj.fill_color)
            new_obj.outline_color = deepcopy(grb_obj.outline_color)
            new_obj.tools = deepcopy(new_apertures)
            new_obj.solid_geometry = deepcopy(new_solid_geometry)
            new_obj.regenerate_source(name=outname)

        self.new_object('gerber', outname, init_func, source=grb_obj)

    def reset_fields(self):
        self.ui.gerber_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))

    @staticmethod
    def poly2rings(poly):
        return [poly.exterior] + [interior for interior in poly.interiors]
