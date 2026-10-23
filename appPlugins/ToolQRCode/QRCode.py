# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 10/24/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets
from appTool import AppTool
from defaults import AppDefaults
from appGUI.GUIElements import VerticalScrollArea, FCFileSaveDialog
from appHandlers.appHistory import history_of
from appParsers.SVG import svg_to_shapes, SvgImportError
from appPlugins.ToolQRCode.QRCodeUI import QRcodeUI
from appPlugins.ToolQRCode import QRCodeGen

import logging
from copy import deepcopy
from io import StringIO, BytesIO
from shapely import MultiPolygon, box
import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class QRCode(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)
        self.app = app
        self.canvas = self.app.plotcanvas
        self.decimals = self.app.decimals
        self.units = ''
        self.ui = QRcodeUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()
        self.grb_object = None
        self.box_poly = None
        self.proc = None
        self.origin = (0, 0)
        self.shapes = self.app.sel_shapes
        self.qrcode_geometry = MultiPolygon()
        self.qrcode_utility_geometry = MultiPolygon()
        self.old_back_color = ''

    def run(self, toggle=True):
        self.app.defaults.report_usage("QRCode()")
        if toggle:
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
        self.app.ui.notebook.setTabText(2, _("QRCode"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+Q', **kwargs)

    def connect_signals_at_init(self):
        self.ui.level.toggled.connect(self.on_level_changed)
        self.ui.qrcode_button.clicked.connect(self.execute)
        self.ui.export_png_button.clicked.connect(self.export_png_file)
        self.ui.export_svg_button.clicked.connect(self.export_svg_file)
        self.ui.fill_color_entry.editingFinished.connect(self.on_qrcode_fill_color_entry)
        self.ui.fill_color_button.clicked.connect(self.on_qrcode_fill_color_button)
        self.ui.back_color_entry.editingFinished.connect(self.on_qrcode_back_color_entry)
        self.ui.back_color_button.clicked.connect(self.on_qrcode_back_color_button)
        self.ui.transparent_cb.stateChanged.connect(self.on_transparent_back_color)
        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    def set_tool_ui(self):
        self.units = self.app.app_units
        self.clear_ui(self.layout)
        self.ui = QRcodeUI(layout=self.layout, app=self.app)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()
        self.ui.border_size_entry.set_value(4)
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        app_option = lambda key: self.app.options.get(
            key, app_defaults.get(key, AppDefaults.factory_defaults.get(key)))
        self.ui.version_entry.set_value(int(app_option("tools_qrcode_version")))
        self.ui.error_radio.set_value(app_option("tools_qrcode_error"))
        self.ui.bsize_entry.set_value(int(app_option("tools_qrcode_box_size")))
        self.ui.border_size_entry.set_value(int(app_option("tools_qrcode_border_size")))
        self.ui.pol_radio.set_value(app_option("tools_qrcode_polarity"))
        self.ui.bb_radio.set_value(app_option("tools_qrcode_rounded"))
        self.ui.text_data.set_value(app_option("tools_qrcode_qrdata"))
        self.ui.fill_color_entry.set_value(app_option('tools_qrcode_fill_color'))
        self.ui.fill_color_button.setStyleSheet("background-color:%s;" %
                                                str(app_option('tools_qrcode_fill_color'))[:7])
        self.ui.back_color_entry.set_value(app_option('tools_qrcode_back_color'))
        self.ui.back_color_button.setStyleSheet("background-color:%s;" %
                                                str(app_option('tools_qrcode_back_color'))[:7])
        obj = self.app.collection.get_active()
        if obj and obj.kind == 'gerber':
            self.ui.grb_object_combo.set_value(obj.obj_options['name'])
        self.change_level(app_option("global_app_level"))

    def change_level(self, level):
        if level == 'a':
            self.ui.level.setChecked(True)
        else:
            self.ui.level.setChecked(False)
        self.on_level_changed(self.ui.level.isChecked())

    def on_level_changed(self, checked):
        self.ui.on_level_changed(checked)

    def execute(self):
        text_data = self.ui.text_data.get_value()
        if text_data == '':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Cancelled. There is no QRCode Data in the text box."))
            return
        selection_index = self.ui.grb_object_combo.currentIndex()
        model_index = self.app.collection.index(selection_index, 0, self.ui.grb_object_combo.rootModelIndex())
        try:
            self.grb_object = model_index.internalPointer().obj
        except Exception as e:
            self.app.log.error("QRCode.execute() --> %s" % str(e))
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("There is no Gerber object loaded ..."))
            return
        self.app.plotcanvas.graph_event_connect('mouse_move', self.on_mouse_move)
        self.app.plotcanvas.graph_event_connect('mouse_release', self.on_mouse_release)
        self.app.plotcanvas.graph_event_connect('key_release', self.on_key_release)
        version = self.ui.version_entry.get_value()
        error = self.ui.error_radio.get_value()
        box_size = self.ui.bsize_entry.get_value()
        border = self.ui.border_size_entry.get_value()

        def job_thread_qr(app_obj):
            with self.app.proc_container.new('%s...' % _("Working")) as self.proc:
                img = QRCodeGen.make_qr_image(text_data, version, error, box_size, border, 'fragment')
                svg_file = BytesIO()
                img.save(svg_file)
                svg_text = StringIO(svg_file.getvalue().decode('UTF-8'))
                svg_geometry = self.convert_svg_to_geo(svg_text, units=self.units)
                self.qrcode_geometry = deepcopy(svg_geometry)
                self.qrcode_utility_geometry = QRCodeGen.utility_geometry(svg_geometry)
                try:
                    a, b, c, d = self.qrcode_utility_geometry.bounds
                    self.box_poly = box(minx=a, miny=b, maxx=c, maxy=d)
                except Exception as ee:
                    self.app.log.error("QRCode.make() bounds error --> %s" % str(ee))
                app_obj.call_source = 'qrcode_tool'
                app_obj.inform.emit(_("Click on the DESTINATION point ..."))
        self.app.worker_task.emit({'fcn': job_thread_qr, 'params': [self.app]})

    def make(self, pos):
        self.on_exit()
        with history_of(self.app).snapshot(_("QRCode"), [self.grb_object]):
            self._write_qrcode(pos)
        self.replot(obj=self.grb_object)
        self.app.inform.emit('[success] %s' % _("QRCode Tool done."))

    def _write_qrcode(self, pos):
        """Apply the model output within the history snapshot and regenerate the Gerber source."""
        solid_geometry, tools = QRCodeGen.insert_geometry(
            self.grb_object.solid_geometry, self.grb_object.tools, self.qrcode_geometry,
            self.qrcode_utility_geometry, pos, self.ui.border_size_entry.get_value(),
            self.ui.bsize_entry.get_value(), self.ui.bb_radio.get_value(), self.ui.pol_radio.get_value())
        self.grb_object.solid_geometry = solid_geometry
        self.grb_object.tools = tools
        try:
            a, b, c, d = self.grb_object.bounds()
            self.grb_object.obj_options['xmin'] = a
            self.grb_object.obj_options['ymin'] = b
            self.grb_object.obj_options['xmax'] = c
            self.grb_object.obj_options['ymax'] = d
        except Exception as e:
            self.app.log.error("QRCode.make() bounds error --> %s" % str(e))
        self.grb_object.regenerate_source()

    def draw_utility_geo(self, pos):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        app_option = lambda key: self.app.options.get(
            key, app_defaults.get(key, AppDefaults.factory_defaults.get(key)))
        offset_geo = QRCodeGen.preview_geometry(self.qrcode_geometry, self.qrcode_utility_geometry,
                                                self.box_poly, pos, app_option("tools_qrcode_sel_limit"))
        for shp in offset_geo:
            self.shapes.add(shp, color='#0000FFAF', update=False, layer=0, tolerance=None)
        self.shapes.redraw()

    def delete_utility_geo(self):
        self.shapes.clear(update=True)

    def on_mouse_move(self, event):
        event_pos = event.pos
        try:
            x = float(event_pos[0])
            y = float(event_pos[1])
        except TypeError:
            return
        pos_canvas = self.app.plotcanvas.translate_coords((x, y))
        if self.app.grid_status():
            pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
        else:
            pos = pos_canvas
        dx = pos[0] - self.origin[0]
        dy = pos[1] - self.origin[1]
        self.shapes.clear()
        self.draw_utility_geo((dx, dy))

    def on_mouse_release(self, event):
        event_pos = event.pos
        if event.button == 1:
            pos_canvas = self.app.plotcanvas.translate_coords(event_pos)
            self.delete_utility_geo()
            if self.app.grid_status():
                pos = self.app.geo_editor.snap(pos_canvas[0], pos_canvas[1])
            else:
                pos = pos_canvas
            dx = pos[0] - self.origin[0]
            dy = pos[1] - self.origin[1]
            self.make(pos=(dx, dy))

    def on_key_release(self, event):
        pass

    def convert_svg_to_geo(self, filename, object_type=None, flip=True, units='MM'):
        self.app.log.debug("QRCode.import_svg()")
        units = self.app.app_units if units is None else units
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        app_option = lambda key: self.app.options.get(
            key, app_defaults.get(key, AppDefaults.factory_defaults.get(key)))
        res = app_option('geometry_circle_steps')
        source = filename.getvalue() if hasattr(filename, 'getvalue') else filename
        try:
            geos = svg_to_shapes(source, object_type, units=units, resolution=res, flip=flip, app=self.app)
        except SvgImportError as e:
            self.app.log.error("QRCode.import_svg(). %s" % str(e))
            return []
        self.app.log.debug("QRCode.import_svg(). Finished parsing the SVG geometry.")
        return list(self.flatten_list(geos))

    def flatten_list(self, geo_list):
        yield from QRCodeGen.flatten_list(geo_list)

    def replot(self, obj):
        def worker_task():
            with self.app.proc_container.new('%s ...' % _("Plotting")):
                obj.plot()
        self.app.worker_task.emit({'fcn': worker_task, 'params': []})

    def on_exit(self):
        self.app.plotcanvas.graph_event_disconnect('mouse_move', self.on_mouse_move)
        self.app.plotcanvas.graph_event_disconnect('mouse_release', self.on_mouse_release)
        self.app.plotcanvas.graph_event_disconnect('key_release', self.on_key_release)
        self.delete_utility_geo()
        self.app.call_source = 'app'

    def export_png_file(self):
        text_data = self.ui.text_data.get_value()
        if text_data == '':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Cancelled. There is no QRCode Data in the text box."))
            return 'fail'
        version = self.ui.version_entry.get_value()
        error = self.ui.error_radio.get_value()
        box_size = self.ui.bsize_entry.get_value()
        border = self.ui.border_size_entry.get_value()
        fill_color = self.ui.fill_color_entry.get_value()
        back_color = self.ui.back_color_entry.get_value()

        def job_thread_qr_png(app_obj, fname):
            img = QRCodeGen.make_qr_image(text_data, version, error, box_size, border, 'png', fill_color, back_color)
            img.save(fname)
            app_obj.call_source = 'qrcode_tool'

        name = 'qr_code'
        _filter = "PNG File (*.png);;All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export PNG"), directory=self.app.get_last_save_folder() + '/' + str(name) + '_png',
                ext_filter=_filter)
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(caption=_("Export PNG"), ext_filter=_filter)
        filename = str(filename)
        if filename == "":
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
            return
        else:
            self.app.worker_task.emit({'fcn': job_thread_qr_png, 'params': [self.app, filename]})

    def export_svg_file(self):
        text_data = self.ui.text_data.get_value()
        if text_data == '':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Cancelled. There is no QRCode Data in the text box."))
            return 'fail'
        version = self.ui.version_entry.get_value()
        error = self.ui.error_radio.get_value()
        box_size = self.ui.bsize_entry.get_value()
        border = self.ui.border_size_entry.get_value()
        fill_color = self.ui.fill_color_entry.get_value()
        back_color = self.ui.back_color_entry.get_value()

        def job_thread_qr_svg(app_obj, fname):
            img = QRCodeGen.make_qr_image(text_data, version, error, box_size, border, 'svg', fill_color, back_color)
            img.save(fname)
            app_obj.call_source = 'qrcode_tool'

        name = 'qr_code'
        _filter = "SVG File (*.svg);;All Files (*.*)"
        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=_("Export SVG"), directory=self.app.get_last_save_folder() + '/' + str(name) + '_svg',
                ext_filter=_filter)
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(caption=_("Export SVG"), ext_filter=_filter)
        filename = str(filename)
        if filename == "":
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
            return
        else:
            self.app.worker_task.emit({'fcn': job_thread_qr_svg, 'params': [self.app, filename]})

    def on_qrcode_fill_color_entry(self):
        self.ui.on_qrcode_fill_color_entry()

    def on_qrcode_fill_color_button(self):
        self.ui.on_qrcode_fill_color_button()

    def on_qrcode_back_color_entry(self):
        self.ui.on_qrcode_back_color_entry()

    def on_qrcode_back_color_button(self):
        self.ui.on_qrcode_back_color_button()

    def on_transparent_back_color(self, state):
        if state:
            self.old_back_color = self.ui.back_color_entry.get_value()
        self.ui.on_transparent_back_color(state, self.old_back_color)
