# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea
from appPlugins.ToolImage.ImageUI import ImageUI
from appPlugins.ToolImage import ImageGen
import appPlugins.ToolImage as image_plugin

from copy import deepcopy
from PIL import Image
import numpy as np
import os

from shapely import LineString, MultiLineString, Polygon, MultiPolygon
from shapely.affinity import scale, translate
from shapely.geometry import shape

import gettext
import appTranslation as fcTranslate
import builtins

from rasterio import open as rasterio_open
from rasterio.features import shapes
from appCommon.imagetrace import trace, PRESETS, PRESET_NAMES, CURVE_MODES
from appParsers.SVG import svg_to_shapes, SvgImportError
from defaults import AppDefaults

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ToolImage(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)
        self.app = app
        self.decimals = self.app.decimals
        self.filename = None

        self.ui = image_plugin.ImageUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolImage()")

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
        self.app.ui.notebook.setTabText(2, _("Image Import"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, **kwargs)

    def connect_signals_at_init(self):
        self.ui.load_button.clicked.connect(self.on_load_image)
        self.ui.import_button.clicked.connect(lambda: self.on_file_importimage())
        self.ui.image_type.activated_custom.connect(self.ui.on_image_type)

    def set_tool_ui(self):
        self.filename = None
        self.clear_ui(self.layout)
        self.ui = image_plugin.ImageUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.ui.dpi_entry.set_value(96)
        self.ui.image_type.set_value('black')
        self.ui.on_image_type(val=self.ui.image_type.get_value())
        self.ui.min_area_entry.set_value(0.3)
        self.ui.import_mode_radio.set_value('raster')
        self.ui.on_import_image_mode(val=self.ui.import_mode_radio.get_value())
        self.ui.control_radio.set_value('presets')
        self.ui.on_tracing_control_radio(val=self.ui.control_radio.get_value())
        self.ui.mask_bw_entry.set_value(250)
        self.ui.mask_r_entry.set_value(250)
        self.ui.mask_g_entry.set_value(250)
        self.ui.mask_b_entry.set_value(250)
        self.ui.threshold_entry.set_value(128)
        self.ui.presets_combo.set_value(0)
        self.ui.on_preset_changed(0)

    def on_load_image(self):
        _filter = "Image Files(*.BMP *.PNG *.JPG *.JPEG);;" \
                  "Bitmap File (*.BMP);;" \
                  "PNG File (*.PNG);;" \
                  "Jpeg File (*.JPG);;" \
                  "All Files (*.*)"
        try:
            filename, _f = QtWidgets.QFileDialog.getOpenFileName(caption=_("Load Image"),
                                                                 directory=self.app.get_last_folder(), filter=_filter)
        except TypeError:
            filename, _f = QtWidgets.QFileDialog.getOpenFileName(caption=_("Load Image"), filter=_filter)

        filename = str(filename)
        if not filename:
            self.app.inform.emit(_("Cancelled."))
            return

        self.filename = None
        self.ui.import_button.setEnabled(False)
        try:
            with Image.open(filename) as image:
                image.load()
                image_dpi = image.info.get('dpi', 0)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as err:
            self.ui.load_status.color = 'red'
            self.ui.load_status.setToolTip('%s\n%s' % (filename, str(err)))
            self.app.log.error("ToolImage.on_load_image() -> %s" % str(err))
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Failed to load image"), str(err)))
            return

        try:
            dpi = float(image_dpi[0] if isinstance(image_dpi, (tuple, list)) else image_dpi)
            if np.isfinite(dpi) and 1 <= round(dpi) <= self.ui.dpi_entry.maximum():
                self.ui.dpi_entry.set_value(round(dpi))
        except (TypeError, ValueError, IndexError, OverflowError):
            pass

        self.filename = filename
        self.ui.load_status.color = 'green'
        self.ui.load_status.setToolTip(filename)
        self.ui.import_button.setEnabled(True)

    def on_file_importimage(self, threaded=True):
        """Create an object from the loaded image using the current parameters."""
        self.app.log.debug("on_file_importimage()")
        filename = self.filename
        if not filename:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Load an image first."))
            return

        import_mode = self.ui.import_mode_radio.get_value()
        trace_options = PRESETS[PRESET_NAMES[self.ui.presets_combo.get_value()]] \
            if self.ui.control_radio.get_value() == 'presets' else self.get_tracing_options()
        type_obj = self.ui.tf_type_obj_combo.get_value()
        dpi = self.ui.dpi_entry.get_value()
        mode = self.ui.image_type.get_value()
        min_area = self.ui.min_area_entry.get_value()
        mask = [self.ui.mask_bw_entry.get_value(), self.ui.mask_r_entry.get_value(),
                self.ui.mask_g_entry.get_value(), self.ui.mask_b_entry.get_value()]

        if import_mode == 'trace':
            # Preserve the legacy package-level monkeypatch target.
            try:
                svg_text = image_plugin.trace(filename, black_white=(mode == 'black'),
                                 threshold=self.ui.threshold_entry.get_value(), options=trace_options)
            except ImportError as err:
                self.app.log.error("ToolImage.on_file_importimage() -> %s" % str(err))
                self.app.inform.emit('[ERROR_NOTCL] %s' % str(err))
                return
        else:
            svg_text = None
        if threaded is True:
            self.app.worker_task.emit({'fcn': self.import_image,
                                       'params': [filename, import_mode, type_obj, dpi, mode, mask, svg_text, min_area]})
        else:
            self.import_image(filename, import_mode, type_obj, dpi, mode, mask, svg_text, min_area)

    def import_image(self, filename, import_mode='raster', o_type=_("Geometry"), dpi=96, mode='black',
                     mask=None, svg_text=None, min_area=0.0, outname=None, silent=False):
        """Import image geometry, register the object, and record the recent file."""
        self.app.defaults.report_usage("import_image()")
        if not os.path.exists(filename):
            if silent:
                self.app.log.debug("File no longer available.")
            else:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("File no longer available."))
            return

        if mask is None:
            mask = [250, 250, 250, 250]
        if o_type is None or o_type == _("Geometry"):
            obj_type = "geometry"
        elif o_type == _("Gerber"):
            obj_type = "gerber"
        else:
            if silent is False:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Only Geometry and Gerber objects are supported"))
            return

        def obj_init(geo_obj, app_obj):
            app_obj.log.debug("ToolImage.import_image() -> importing image as: %s" % obj_type.capitalize())
            if import_mode == 'raster':
                image_geo = self.import_image_handler(filename, units=units, dpi=dpi, mode=mode, mask=mask)
            else:
                image_geo = self.import_image_as_trace_handler(svg_text=svg_text, obj_type=obj_type, units=units,
                                                               dpi=dpi)

            if not image_geo:
                app_obj.log.debug("ToolImage.import_image() -> empty geometry.")
                return 'fail'
            if image_geo == 'fail':
                if silent is False:
                    app_obj.inform.emit("[ERROR_NOTCL] %s" % _("Failed."))
                return "fail"

            geo_obj.multigeo = False
            geo_obj.multitool = False
            geo_obj.solid_geometry = list(self.flatten_list(image_geo))
            geo_obj.solid_geometry = [p for p in geo_obj.solid_geometry if p and p.is_valid and p.area >= min_area]

            if obj_type == 'geometry':
                app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
                tooldia = float(self.app.options.get(
                    "tools_mill_tooldia", app_defaults.get("tools_mill_tooldia", AppDefaults.factory_defaults.get("tools_mill_tooldia"))))
                tooldia = float('%.*f' % (self.decimals, tooldia))
                new_data = {k: v for k, v in self.app.options.items()}
                geo_obj.tools.update({
                    1: {'tooldia': tooldia, 'data': deepcopy(new_data),
                        'solid_geometry': deepcopy(geo_obj.solid_geometry)}
                })
                geo_obj.tools[1]['data']['name'] = name
                if svg_text is not None:
                    geo_obj.source_file = svg_text
                else:
                    geo_obj.regenerate_source()
            else:
                if 0 not in geo_obj.tools:
                    geo_obj.tools[0] = {'type': 'REG', 'size': 0.0, 'geometry': []}
                try:
                    w_geo = geo_obj.solid_geometry.geoms if \
                        isinstance(geo_obj.solid_geometry, (MultiLineString, MultiPolygon)) else geo_obj.solid_geometry
                    for pol in w_geo:
                        new_el = {'solid': pol, 'follow': LineString(pol.exterior.coords)}
                        geo_obj.tools[0]['geometry'].append(new_el)
                except TypeError:
                    new_el = {
                        'solid': geo_obj.solid_geometry,
                        'follow': LineString(geo_obj.solid_geometry.exterior.coords) if
                        isinstance(geo_obj.solid_geometry, Polygon) else geo_obj.solid_geometry
                    }
                    geo_obj.tools[0]['geometry'].append(new_el)
                geo_obj.regenerate_source()

        with self.app.proc_container.new('%s ...' % _("Importing")):
            name = outname or filename.split('/')[-1].split('\\')[-1]
            units = self.app.app_units
            res = self.new_object(obj_type, name, obj_init)
            if res == 'fail':
                self.app.inform.emit("[ERROR_NOTCL] %s" % _("Failed."))
                return
            self.app.file_opened.emit("image", filename)
            if silent is False:
                self.app.inform.emit('[success] %s: %s' % (_("Opened"), filename))

    def import_image_handler(self, filename, flip=True, units='MM', dpi=96, mode='black', mask=None):
        """Import masked raster shapes in application units."""
        geos = ImageGen.import_raster(filename, flip=flip, units=units, dpi=dpi, mode=mode, mask=mask,
                                     raster_opener=image_plugin.rasterio_open)
        if mode == 'black':
            self.app.log.debug("Image import as monochrome.")
        else:
            thresholds = mask if mask is not None else [128, 128, 128, 128]
            self.app.log.debug("Image import as colored. Thresholds are: R = %s , G = %s, B = %s" %
                               (str(thresholds[1]), str(thresholds[2]), str(thresholds[3])))
        return geos

    def import_image_as_trace_handler(self, svg_text, obj_type, flip=True, units='MM', dpi=96):
        """Parse traced SVG pixels, then scale to application units."""
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        res = self.app.options.get(
            'geometry_circle_steps', app_defaults.get('geometry_circle_steps', AppDefaults.factory_defaults.get('geometry_circle_steps')))
        try:
            geos = image_plugin.svg_to_shapes(svg_text, obj_type, units=units, resolution=res, flip=flip, app=self.app,
                                 user_units=True)
        except SvgImportError as e:
            self.app.log.error("ToolImage.import_image_as_trace_handler(). %s" % str(e))
            return 'fail'
        self.app.log.debug("ToolImage.import_image_as_trace_handler(). Finished parsing the SVG geometry.")
        return ImageGen.scale_geometry(geos, units=units, dpi=dpi)

    def get_tracing_options(self):
        return {
            'mode': CURVE_MODES[self.ui.curve_combo.get_value()],
            'filter_speckle': self.ui.speckle_entry.get_value(),
            'color_precision': self.ui.color_precision_entry.get_value(),
            'layer_difference': self.ui.layer_diff_entry.get_value(),
            'corner_threshold': self.ui.corner_entry.get_value(),
            'length_threshold': self.ui.length_entry.get_value(),
            'splice_threshold': self.ui.splice_entry.get_value()
        }

    def flatten_list(self, obj_list):
        yield from ImageGen.flatten_list(obj_list)
