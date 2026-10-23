# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 1/10/2020                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCCheckBox
from defaults import AppDefaults
from appPlugins.ToolExtract.ExtractUI import ExtractUI
from appPlugins.ToolExtract import ExtractGen

import logging
from copy import deepcopy

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class ToolExtract(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.app = app
        self.decimals = self.app.decimals

        # store here the old object name
        self.old_name = ''

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = ExtractUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def on_object_combo_changed(self):
        extract_plugin_found = False
        for idx in range(self.app.ui.notebook.count()):
            if self.app.ui.notebook.tabText(idx) == _("Extract"):
                extract_plugin_found = True
                break

        if extract_plugin_found is False:
            return

        # get the Gerber file who is the source of the punched Gerber
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())

        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            return

        if self.old_name != '':
            old_obj = self.app.collection.get_by_name(self.old_name)
            if old_obj:
                old_obj.clear_plot_apertures()
                old_obj.mark_shapes.enabled = False

        # enable mark shapes
        if grb_obj:
            grb_obj.mark_shapes.enabled = True

            # create storage for shapes
            for ap_code in grb_obj.tools:
                grb_obj.mark_shapes_storage[ap_code] = []

            self.old_name = grb_obj.obj_options['name']

        self.build_tool_ui()

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+E', **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("Extract Drills()")

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
        self.build_tool_ui()

        # trigger this once at plugin launch
        self.on_object_combo_changed()

    def connect_signals_at_init(self):
        # ## Signals
        self.ui.method_radio.activated_custom.connect(self.on_extract_drills_method_changed)

        self.ui.circular_cb.stateChanged.connect(
            lambda state:
            self.ui.circular_ring_entry.setDisabled(False) if state else self.ui.circular_ring_entry.setDisabled(True)
        )

        self.ui.oblong_cb.stateChanged.connect(
            lambda state:
            self.ui.oblong_ring_entry.setDisabled(False) if state else self.ui.oblong_ring_entry.setDisabled(True)
        )

        self.ui.square_cb.stateChanged.connect(
            lambda state:
            self.ui.square_ring_entry.setDisabled(False) if state else self.ui.square_ring_entry.setDisabled(True)
        )

        self.ui.rectangular_cb.stateChanged.connect(
            lambda state:
            self.ui.rectangular_ring_entry.setDisabled(False) if state else
            self.ui.rectangular_ring_entry.setDisabled(True)
        )

        self.ui.other_cb.stateChanged.connect(
            lambda state:
            self.ui.other_ring_entry.setDisabled(False) if state else self.ui.other_ring_entry.setDisabled(True)
        )

        self.ui.e_drills_button.clicked.connect(self.on_extract_drills_click)
        self.ui.e_sm_button.clicked.connect(self.on_extract_soldermask_click)
        self.ui.e_cut_button.clicked.connect(self.on_extract_cutout_click)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

        self.ui.circular_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.oblong_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.square_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.rectangular_cb.stateChanged.connect(self.build_tool_ui)
        self.ui.other_cb.stateChanged.connect(self.build_tool_ui)

        self.ui.gerber_object_combo.currentIndexChanged.connect(self.on_object_combo_changed)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = ExtractUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.reset_fields()

        self.ui_disconnect()
        self.ui_connect()
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        self.ui.method_radio.set_value(self.app.options.get(
            "tools_extract_hole_type",
            app_defaults.get("tools_extract_hole_type", AppDefaults.factory_defaults.get("tools_extract_hole_type"))
        ))

        self.ui.dia_entry.set_value(float(self.app.options.get(
            "tools_extract_hole_fixed_dia",
            app_defaults.get("tools_extract_hole_fixed_dia", AppDefaults.factory_defaults.get("tools_extract_hole_fixed_dia"))
        )))

        self.ui.circular_ring_entry.set_value(float(self.app.options.get(
            "tools_extract_circular_ring",
            app_defaults.get("tools_extract_circular_ring", AppDefaults.factory_defaults.get("tools_extract_circular_ring"))
        )))
        self.ui.oblong_ring_entry.set_value(float(self.app.options.get(
            "tools_extract_oblong_ring",
            app_defaults.get("tools_extract_oblong_ring", AppDefaults.factory_defaults.get("tools_extract_oblong_ring"))
        )))
        self.ui.square_ring_entry.set_value(float(self.app.options.get(
            "tools_extract_square_ring",
            app_defaults.get("tools_extract_square_ring", AppDefaults.factory_defaults.get("tools_extract_square_ring"))
        )))
        self.ui.rectangular_ring_entry.set_value(float(self.app.options.get(
            "tools_extract_rectangular_ring",
            app_defaults.get("tools_extract_rectangular_ring", AppDefaults.factory_defaults.get("tools_extract_rectangular_ring"))
        )))
        self.ui.other_ring_entry.set_value(float(self.app.options.get(
            "tools_extract_others_ring",
            app_defaults.get("tools_extract_others_ring", AppDefaults.factory_defaults.get("tools_extract_others_ring"))
        )))

        self.ui.circular_cb.set_value(self.app.options.get(
            "tools_extract_circular",
            app_defaults.get("tools_extract_circular", AppDefaults.factory_defaults.get("tools_extract_circular"))
        ))
        self.ui.oblong_cb.set_value(self.app.options.get(
            "tools_extract_oblong",
            app_defaults.get("tools_extract_oblong", AppDefaults.factory_defaults.get("tools_extract_oblong"))
        ))
        self.ui.square_cb.set_value(self.app.options.get(
            "tools_extract_square",
            app_defaults.get("tools_extract_square", AppDefaults.factory_defaults.get("tools_extract_square"))
        ))
        self.ui.rectangular_cb.set_value(self.app.options.get(
            "tools_extract_rectangular",
            app_defaults.get("tools_extract_rectangular", AppDefaults.factory_defaults.get("tools_extract_rectangular"))
        ))
        self.ui.other_cb.set_value(self.app.options.get(
            "tools_extract_others",
            app_defaults.get("tools_extract_others", AppDefaults.factory_defaults.get("tools_extract_others"))
        ))

        self.ui.factor_entry.set_value(float(self.app.options.get(
            "tools_extract_hole_prop_factor",
            app_defaults.get("tools_extract_hole_prop_factor", AppDefaults.factory_defaults.get("tools_extract_hole_prop_factor"))
        )))

        # Extract Soldermask
        self.ui.clearance_entry.set_value(float(self.app.options.get(
            "tools_extract_sm_clearance",
            app_defaults.get("tools_extract_sm_clearance", AppDefaults.factory_defaults.get("tools_extract_sm_clearance"))
        )))

        # Extract Cutout
        self.ui.margin_cut_entry.set_value(float(self.app.options.get(
            "tools_extract_cut_margin",
            app_defaults.get("tools_extract_cut_margin", AppDefaults.factory_defaults.get("tools_extract_cut_margin"))
        )))
        self.ui.thick_cut_entry.set_value(float(self.app.options.get(
            "tools_extract_cut_thickness",
            app_defaults.get("tools_extract_cut_thickness", AppDefaults.factory_defaults.get("tools_extract_cut_thickness"))
        )))

        # SELECT THE CURRENT OBJECT
        obj = self.app.collection.get_active()
        if obj:
            if obj.kind == 'gerber':
                obj_name = obj.obj_options['name']
                self.ui.gerber_object_combo.set_value(obj_name)
        else:
            # take first available Gerber file, if any
            available_gerber_list = [o for o in self.app.collection.get_list() if o.kind == 'gerber']
            if available_gerber_list:
                obj_name = available_gerber_list[0].obj_options['name']
                self.ui.gerber_object_combo.set_value(obj_name)

        self.app.ui.notebook.setTabText(2, _("Extract"))

    def build_tool_ui(self):
        self.ui_disconnect()

        # reset table
        # self.ui.apertures_table.clear()   # this deletes the headers/tooltips too ... not nice!
        self.ui.apertures_table.setRowCount(0)

        # get the Gerber file who is the source of the punched Gerber
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        obj = None

        try:
            obj = model_index.internalPointer().obj
            sort = [int(k) for k in obj.tools.keys()]
            sorted_apertures = sorted(sort)
        except Exception:
            # no object loaded
            sorted_apertures = []

        self.ui.populate_apertures(obj.tools if obj is not None else {}, sorted_apertures)

        # make sure you clear the Gerber aperture markings when the table is rebuilt
        # get the Gerber file who is the source of the punched Gerber
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())
        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            self.ui_connect()
            return
        grb_obj.clear_plot_apertures()

        self.ui_connect()

    def ui_connect(self):
        self.ui.all_cb.stateChanged.connect(self.on_select_all)

        # Mark Checkboxes
        for row in range(self.ui.apertures_table.rowCount()):
            try:
                wdg = self.ui.apertures_table.cellWidget(row, 3)
                assert isinstance(wdg, FCCheckBox)
                wdg.clicked.disconnect()
            except (TypeError, AttributeError):
                pass
            wdg = self.ui.apertures_table.cellWidget(row, 3)
            assert isinstance(wdg, FCCheckBox)
            wdg.stateChanged.connect(self.on_mark_cb_click_table)

    def ui_disconnect(self):
        try:
            self.ui.all_cb.stateChanged.disconnect()
        except (AttributeError, TypeError):
            pass

        # Mark Checkboxes
        for row in range(self.ui.apertures_table.rowCount()):
            try:
                wdg = self.ui.apertures_table.cellWidget(row, 3)
                assert isinstance(wdg, FCCheckBox)
                wdg.stateChanged.disconnect()
            except (TypeError, AttributeError):
                pass

    def on_select_all(self, state):
        self.ui_disconnect()
        if state:
            self.ui.circular_cb.setChecked(True)
            self.ui.oblong_cb.setChecked(True)
            self.ui.square_cb.setChecked(True)
            self.ui.rectangular_cb.setChecked(True)
            self.ui.other_cb.setChecked(True)
        else:
            self.ui.circular_cb.setChecked(False)
            self.ui.oblong_cb.setChecked(False)
            self.ui.square_cb.setChecked(False)
            self.ui.rectangular_cb.setChecked(False)
            self.ui.other_cb.setChecked(False)

    def on_extract_drills_click(self):
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())

        try:
            fcobj = model_index.internalPointer().obj
        except Exception:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return
        outname = "%s_%s" % (fcobj.obj_options['name'].rpartition('.')[0], _("extracted"))

        # selected codes in the apertures UI table
        sel_g_tools = [int(it.text()) for it in self.ui.apertures_table.selectedItems()]

        mode = self.ui.method_radio.get_value()
        if mode == 'fixed':
            tools = self.fixed_dia_mode(gerber_tools=fcobj.tools, sel_tools=sel_g_tools)
        elif mode == 'ring':
            tools = self.ring_mode(gerber_tools=fcobj.tools, sel_tools=sel_g_tools)
        else:   # proportional
            tools = self.proportional_mode(gerber_tools=fcobj.tools, sel_tools=sel_g_tools)

        if not tools:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
            return

        def obj_init(obj_inst, app_inst):
            obj_inst.tools = deepcopy(tools)
            obj_inst.create_geometry()
            obj_inst.regenerate_source(name=outname)

        with self.app.proc_container.new('%s...' % _("Working")):
            self.clear_aperture_marking()

            try:
                self.new_object("excellon", outname, obj_init, source=fcobj, autoselected=False)
            except Exception as e:
                self.app.log.error("Error on Extracted Excellon object creation: %s" % str(e))
                return

    def fixed_dia_mode(self, gerber_tools, sel_tools):
        tools = ExtractGen.fixed_drills(
            gerber_tools, sel_tools, self.ui.dia_entry.get_value(), self.decimals,
            self.ui.circular_cb.get_value(), self.ui.oblong_cb.get_value(), self.ui.square_cb.get_value(),
            self.ui.rectangular_cb.get_value(), self.ui.other_cb.get_value())
        if not tools:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No drills extracted. Try different parameters."))
            return
        return tools

    def ring_mode(self, gerber_tools, sel_tools):
        tools = ExtractGen.sized_drills(
            gerber_tools, sel_tools, 'ring', self.decimals, self.app.dec_format,
            (self.ui.circular_cb.get_value(), self.ui.oblong_cb.get_value(), self.ui.square_cb.get_value(),
             self.ui.rectangular_cb.get_value(), self.ui.other_cb.get_value()),
            (self.ui.circular_ring_entry.get_value(), self.ui.oblong_ring_entry.get_value(),
             self.ui.square_ring_entry.get_value(), self.ui.rectangular_ring_entry.get_value(),
             self.ui.other_ring_entry.get_value()))
        if not tools:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No drills extracted. Try different parameters."))
            return
        return tools

    def proportional_mode(self, gerber_tools, sel_tools):
        tools = ExtractGen.sized_drills(
            gerber_tools, sel_tools, 'prop', self.decimals, self.app.dec_format,
            (self.ui.circular_cb.get_value(), self.ui.oblong_cb.get_value(), self.ui.square_cb.get_value(),
             self.ui.rectangular_cb.get_value(), self.ui.other_cb.get_value()),
            self.ui.factor_entry.get_value() / 100.0)
        if not tools:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No drills extracted. Try different parameters."))
            return
        return tools

    def on_extract_soldermask_click(self):
        clearance = self.ui.clearance_entry.get_value()

        circ = self.ui.circular_cb.get_value()
        oblong = self.ui.oblong_cb.get_value()
        square = self.ui.square_cb.get_value()
        rect = self.ui.rectangular_cb.get_value()
        other = self.ui.other_cb.get_value()

        allowed_apertures = []
        if circ:
            allowed_apertures.append('C')
        if oblong:
            allowed_apertures.append('O')
        if square or rect:
            allowed_apertures.append('R')
        if other:
            allowed_apertures.append('AM')
            allowed_apertures.append('P')

        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())

        try:
            obj = model_index.internalPointer().obj
        except Exception:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return
        outname = '%s_esm' % obj.obj_options['name'].rpartition('.')[0]

        selected = [int(it.text()) for it in self.ui.apertures_table.selectedItems()]
        result = ExtractGen.soldermask(
            obj.tools, selected, allowed_apertures, square, rect, clearance, self.decimals)
        if result is None:
            self.app.inform.emit('[ERROR_NOTCL] %s %s' % (_("Failed."), _("No soldermask extracted.")))
            return
        new_apertures, new_solid_geometry, new_follow_geometry = result

        def obj_init(new_obj, app_obj):
            new_obj.multitool = False
            new_obj.multigeo = False
            new_obj.follow = False
            new_obj.tools = deepcopy(new_apertures)
            new_obj.solid_geometry = deepcopy(new_solid_geometry)
            new_obj.follow_geometry = deepcopy(new_follow_geometry)

            try:
                new_obj.regenerate_source(name=outname)
            except (AttributeError, TypeError):
                pass

        with self.app.proc_container.new('%s...' % _("Working")):
            try:
                self.new_object("gerber", outname, obj_init, source=obj, autoselected=False)
            except Exception as e:
                self.app.log.error("Error on Extracted Soldermask Gerber object creation: %s" % str(e))
                return

    def on_extract_cutout_click(self):
        margin = self.ui.margin_cut_entry.get_value()
        thickness = self.ui.thick_cut_entry.get_value()

        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())

        try:
            obj = model_index.internalPointer().obj
        except Exception:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("No object is selected."))
            return

        outname = '%s_ecut' % obj.obj_options['name'].rpartition('.')[0]

        try:
            result = ExtractGen.cutout(obj.solid_geometry, margin, thickness)
        except Exception as e:
            self.app.log.error("ToolExtrct.on_extrct_cutout_click() -> %s" % str(e))
            self.app.inform.emit('[ERROR_NOTCL] %s %s' % (_("Failed."), _("No cutout extracted.")))
            return

        if result is None:
            self.app.inform.emit('[ERROR_NOTCL] %s %s' % (_("Failed."), _("No cutout extracted.")))
            return
        new_apertures, new_geo_solid, new_geo_follow = result

        def obj_init(new_obj, app_obj):
            new_obj.multitool = False
            new_obj.multigeo = False
            new_obj.follow = False
            new_obj.tools = deepcopy(new_apertures)
            new_obj.solid_geometry = [deepcopy(new_geo_solid)]
            new_obj.follow_geometry = [deepcopy(new_geo_follow)]

            try:
                new_obj.regenerate_source(name=outname)
            except (AttributeError, TypeError):
                pass

        with self.app.proc_container.new('%s...' % _("Working")):
            try:
                self.new_object("gerber", outname, obj_init, source=obj)
            except Exception as e:
                self.app.log.error("Error on Extracted Cutout Gerber object creation: %s" % str(e))
                return

    def on_extract_drills_method_changed(self, val):
        ExtractUI.set_drill_method(self.ui, val)

    def on_mark_cb_click_table(self):
        """
        Will mark aperture geometries on canvas or delete the markings depending on the checkbox state
        :return:
        """

        try:
            cw = self.sender()
            cw_index = self.ui.apertures_table.indexAt(cw.pos())
            cw_row = cw_index.row()
        except AttributeError:
            cw_row = 0
        except TypeError:
            return

        try:
            aperture = int(self.ui.apertures_table.item(cw_row, 0).text())
        except AttributeError:
            return

        # get the Gerber file who is the source of the punched Gerber
        selection_index = self.ui.gerber_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.gerber_object_combo.rootModelIndex())

        try:
            grb_obj = model_index.internalPointer().obj
        except Exception:
            return

        wdg = self.ui.apertures_table.cellWidget(cw_row, 3)
        assert isinstance(wdg, FCCheckBox)
        if wdg.isChecked():
            # self.plot_aperture(color='#2d4606bf', marked_aperture=aperture, visible=True)
            app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
            color = self.app.options.get(
                'global_sel_draw_color',
                app_defaults.get('global_sel_draw_color', AppDefaults.factory_defaults.get('global_sel_draw_color'))
            )
            color = (color + 'AA') if len(color) == 7 else (color[:-2] + 'AA')
            grb_obj.plot_aperture(color=color, marked_aperture=aperture, visible=True, run_thread=True)
        else:
            grb_obj.clear_plot_apertures(aperture=aperture)

    def on_plugin_cleanup(self):
        self.reset_fields()

    def clear_aperture_marking(self):
        """
        Will clear all aperture markings after creating an Excellon object with extracted drill holes

        :return:
        :rtype:
        """

        for row in range(self.ui.apertures_table.rowCount()):
            wdg = self.ui.apertures_table.cellWidget(row, 3)
            assert isinstance(wdg, FCCheckBox)
            wdg.set_value(False)

    def reset_fields(self):
        self.ui.gerber_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ui.gerber_object_combo.setCurrentIndex(0)
        self.clear_aperture_marking()
