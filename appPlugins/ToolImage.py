# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtGui
from appTool import AppTool
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCComboBox2, \
    RadioSet, FCDoubleSpinner, FCSpinner

from copy import deepcopy
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

        # #############################################################################
        # ######################### Tool GUI ##########################################
        # #############################################################################
        self.ui = ImageUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolImage()")

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

        self.app.ui.notebook.setTabText(2, _("Image Import"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, **kwargs)

    def connect_signals_at_init(self):
        # ## Signals
        self.ui.import_button.clicked.connect(lambda: self.on_file_importimage())
        self.ui.image_type.activated_custom.connect(self.ui.on_image_type)

    def set_tool_ui(self):
        self.clear_ui(self.layout)
        self.ui = ImageUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls(has_source=False)
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        # ## Initialize form
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
        # the Options start from the selected preset
        self.ui.presets_combo.set_value(0)
        self.ui.on_preset_changed(0)

    def on_file_importimage(self, threaded=True):
        """
        Callback for menu item File->Import IMAGE.

        :return: None
        """

        self.app.log.debug("on_file_importimage()")

        import_mode = self.ui.import_mode_radio.get_value()
        trace_options = PRESETS[PRESET_NAMES[self.ui.presets_combo.get_value()]] \
            if self.ui.control_radio.get_value() == 'presets' else self.get_tracing_options()
        type_obj = self.ui.tf_type_obj_combo.get_value()
        dpi = self.ui.dpi_entry.get_value()
        mode = self.ui.image_type.get_value()
        min_area = self.ui.min_area_entry.get_value()

        _filter = "Image Files(*.BMP *.PNG *.JPG *.JPEG);;" \
                  "Bitmap File (*.BMP);;" \
                  "PNG File (*.PNG);;" \
                  "Jpeg File (*.JPG);;" \
                  "All Files (*.*)"
        try:
            filename, _f = QtWidgets.QFileDialog.getOpenFileName(caption=_("Import IMAGE"),
                                                                 directory=self.app.get_last_folder(), filter=_filter)
        except TypeError:
            filename, _f = QtWidgets.QFileDialog.getOpenFileName(caption=_("Import IMAGE"), filter=_filter)

        filename = str(filename)

        mask = [
            self.ui.mask_bw_entry.get_value(),
            self.ui.mask_r_entry.get_value(),
            self.ui.mask_g_entry.get_value(),
            self.ui.mask_b_entry.get_value()
        ]

        if filename == "":
            self.app.inform.emit(_("Cancelled."))
        else:
            if import_mode == 'trace':
                # there are thread issues so I process this outside
                try:
                    svg_text = trace(filename, black_white=(mode == 'black'),
                                     threshold=self.ui.threshold_entry.get_value(), options=trace_options)
                except ImportError as err:
                    self.app.log.error("ToolImage.on_file_importimage() -> %s" % str(err))
                    self.app.inform.emit('[ERROR_NOTCL] %s' % str(err))
                    return
            else:
                svg_text = None
            if threaded is True:
                self.app.worker_task.emit({'fcn': self.import_image,
                                           'params': [
                                               filename, import_mode, type_obj, dpi, mode, mask, svg_text, min_area]
                                           })
            else:
                self.import_image(filename, import_mode, type_obj, dpi, mode, mask, svg_text, min_area)

    def import_image(self, filename, import_mode='raster', o_type=_("Geometry"), dpi=96, mode='black',
                     mask=None, svg_text=None, min_area=0.0, outname=None, silent=False):
        """
        Adds a new Geometry Object to the projects and populates
        it with shapes extracted from the SVG file.

        :param filename:        Path to the SVG file.
        :param import_mode:     The kind of image import to be done: 'raster' or 'trace'
        :param o_type:          type of FlatCAM object
        :param dpi:             dot per inch
        :param mode:            black or color
        :param mask:            dictate the level of detail
        :param svg_text:        a SVG string only for when tracing
        :param outname:         name for the resulting file
        :param min_area:        the minimum area for the imported polygons for them to be kept
        :param silent:          bool: if False then there are no messages issued to GUI
        :return:
        """

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
            else:   # 'trace'
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

            # flatten the geo_obj.solid_geometry list
            geo_obj.solid_geometry = list(self.flatten_list(image_geo))
            geo_obj.solid_geometry = [p for p in geo_obj.solid_geometry if p and p.is_valid and p.area >= min_area]

            if obj_type == 'geometry':
                app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
                tooldia = float(self.app.options.get(
                    "tools_mill_tooldia", app_defaults.get("tools_mill_tooldia", AppDefaults.factory_defaults.get("tools_mill_tooldia"))))
                tooldia = float('%.*f' % (self.decimals, tooldia))

                new_data = {k: v for k, v in self.app.options.items()}

                geo_obj.tools.update({
                    1: {
                        'tooldia': tooldia,
                        'data': deepcopy(new_data),
                        'solid_geometry': deepcopy(geo_obj.solid_geometry)
                    }
                })

                geo_obj.tools[1]['data']['name'] = name
                if svg_text is not None:
                    geo_obj.source_file = svg_text
                else:
                    geo_obj.regenerate_source()
            else:   # 'gerber'
                if 0 not in geo_obj.tools:
                    geo_obj.tools[0] = {
                        'type': 'REG',
                        'size': 0.0,
                        'geometry': []
                    }

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

            # Object name
            name = outname or filename.split('/')[-1].split('\\')[-1]
            units = self.app.app_units

            res = self.new_object(obj_type, name, obj_init)
            if res == 'fail':
                self.app.inform.emit("[ERROR_NOTCL] %s" % _("Failed."))
                return
            # Register recent file
            self.app.file_opened.emit("image", filename)

            # GUI feedback
            if silent is False:
                self.app.inform.emit('[success] %s: %s' % (_("Opened"), filename))

    def import_image_handler(self, filename, flip=True, units='MM', dpi=96, mode='black', mask=None):
        """
        Imports shapes from an IMAGE file into the object's geometry.

        :param filename:    Path to the IMAGE file.
        :type filename:     str
        :param flip:        Flip the object vertically.
        :type flip:         bool
        :param units:       App units
        :type units:        str
        :param dpi:         dots per inch on the imported image
        :param mode:        how to import the image: as 'black' or 'color'
        :type mode:         str
        :param mask:        level of detail for the import
        :return:            None
        """
        if mask is None:
            mask = [128, 128, 128, 128]

        scale_factor = 25.4 / dpi if units.lower() == 'mm' else 1 / dpi

        geos = []
        unscaled_geos = []

        with rasterio_open(filename) as src:
            # if filename.lower().rpartition('.')[-1] == 'bmp':
            #     red = green = blue = src.read(1)
            #     print("BMP")
            # elif filename.lower().rpartition('.')[-1] == 'png':
            #     red, green, blue, alpha = src.read()
            # elif filename.lower().rpartition('.')[-1] == 'jpg':
            #     red, green, blue = src.read()

            red = green = blue = src.read(1)

            try:
                green = src.read(2)
            except Exception:
                pass

            try:
                blue = src.read(3)
            except Exception:
                pass

        if mode == 'black':
            mask_setting = red <= mask[0]
            total = red
            self.app.log.debug("Image import as monochrome.")
        else:
            mask_setting = (red <= mask[1]) + (green <= mask[2]) + (blue <= mask[3])
            total = np.zeros(red.shape, dtype=np.float32)
            for band in red, green, blue:
                total += band
            total /= 3
            self.app.log.debug("Image import as colored. Thresholds are: R = %s , G = %s, B = %s" %
                               (str(mask[1]), str(mask[2]), str(mask[3])))

        for geom, val in shapes(total, mask=mask_setting):
            unscaled_geos.append(shape(geom))

        for g in unscaled_geos:
            geos.append(scale(g, scale_factor, scale_factor, origin=(0, 0)))

        if flip:
            geos = [translate(scale(g, 1.0, -1.0, origin=(0, 0))) for g in geos]

        return geos

    def import_image_as_trace_handler(self, svg_text, obj_type, flip=True, units='MM', dpi=96):
        """
        Imports shapes from an IMAGE file into the object's geometry.

        :param svg_text:    A SVG text object
        :type svg_text:     str
        :param obj_type:    the way the image is imported. As: 'gerber' or 'geometry' objects
        :type obj_type:     str
        :param flip:        Flip the object vertically.
        :type flip:         bool
        :param units:       App units
        :type units:        str
        :param dpi:         dots per inch on the imported image
        :return:            None
        """

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        res = self.app.options.get(
            'geometry_circle_steps', app_defaults.get('geometry_circle_steps', AppDefaults.factory_defaults.get('geometry_circle_steps')))

        # The vtracer SVG is in pixels: ask for raw user units (flip = plain mirror y -> -y), the dpi scaling is below
        try:
            geos = svg_to_shapes(svg_text, obj_type, units=units, resolution=res, flip=flip, app=self.app,
                                 user_units=True)
        except SvgImportError as e:
            self.app.log.error("ToolImage.import_image_as_trace_handler(). %s" % str(e))
            return 'fail'
        self.app.log.debug("ToolImage.import_image_as_trace_handler(). Finished parsing the SVG geometry.")

        scale_factor = 25.4 / dpi if units.lower() == 'mm' else 1 / dpi
        geos = [translate(scale(g, scale_factor, scale_factor, origin=(0, 0))) for g in geos]

        return geos

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
        for item in obj_list:
            if hasattr(item, '__iter__') and not isinstance(item, (str, bytes)):
                yield from self.flatten_list(item)
            else:
                yield item


class ImageUI:

    pluginName = _("Image Import")

    def __init__(self, layout, app):
        self.app = app
        self.decimals = self.app.decimals
        self.layout = layout

        # ## Title
        title_label = FCLabel("%s" % self.pluginName, size=16, bold=True)
        self.layout.addWidget(title_label)

        self.param_lbl = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.layout.addWidget(self.param_lbl)
        # #############################################################################################################
        # ######################################## Parameters #########################################################
        # #############################################################################################################
        # add a frame and inside add a grid box layout.
        par_frame = FCFrame()
        self.layout.addWidget(par_frame)

        par_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(par_grid)

        # Type of object to create for the image
        self.tf_type_obj_combo_label = FCLabel('%s:' % _("Object Type"))
        self.tf_type_obj_combo_label.setToolTip(
            _("Specify the type of object to create from the image.\n"
              "It can be of type: Gerber or Geometry.")

        )

        self.tf_type_obj_combo = FCComboBox()
        self.tf_type_obj_combo.addItems([_("Gerber"), _("Geometry")])
        self.tf_type_obj_combo.setItemIcon(0, QtGui.QIcon(self.app.resource_location + "/flatcam_icon16.png"))
        self.tf_type_obj_combo.setItemIcon(1, QtGui.QIcon(self.app.resource_location + "/geometry16.png"))

        par_grid.addWidget(self.tf_type_obj_combo_label, 0, 0)
        par_grid.addWidget(self.tf_type_obj_combo, 0, 1, 1, 2)

        # DPI value of the imported image
        self.dpi_entry = FCSpinner()
        self.dpi_entry.set_range(0, 99999)
        self.dpi_label = FCLabel('%s:' % _("DPI value"))
        self.dpi_label.setToolTip(_("Specify a DPI value for the image."))
        par_grid.addWidget(self.dpi_label, 2, 0)
        par_grid.addWidget(self.dpi_entry, 2, 1, 1, 2)

        # Area
        area_lbl = FCLabel('%s' % _("Area:"), bold=True)
        area_lbl.setToolTip(
            _("Polygons inside the image with less area are discarded.")
        )
        self.min_area_entry = FCDoubleSpinner()
        self.min_area_entry.set_range(0.0000, 10000.0000)
        self.min_area_entry.setSingleStep(0.1)
        self.min_area_entry.set_value(0.0)
        a_units = _("mm") if self.app.app_units == 'MM' else _("in")
        area_units_lbl = FCLabel('%s<sup>2</sup>' % a_units)

        par_grid.addWidget(area_lbl, 4, 0)
        par_grid.addWidget(self.min_area_entry, 4, 1)
        par_grid.addWidget(area_units_lbl, 4, 2)

        # The import Mode
        self.import_mode_lbl = FCLabel('%s:' % _('Mode'), color='red', bold=True)
        self.import_mode_lbl.setToolTip(
            _("Choose a method for the image interpretation.\n"
              "B/W means a black & white image. Color means a colored image.")
        )

        self.import_mode_radio = RadioSet([
            {'label': 'Raster', 'value': 'raster'},
            {'label': 'Tracing', 'value': 'trace'}
        ])

        mod_grid = GLay(v_spacing=5, h_spacing=3)
        self.layout.addLayout(mod_grid)

        mod_grid.addWidget(self.import_mode_lbl, 0, 0)
        mod_grid.addWidget(self.import_mode_radio, 0, 1)

        # Type of image interpretation
        self.image_type_label = FCLabel('%s:' % _('Type'), bold=True)
        self.image_type_label.setToolTip(
            _("Choose a method for the image interpretation.\n"
              "B/W means a black & white image. Color means a colored image.")
        )

        self.image_type = RadioSet([{'label': 'B/W', 'value': 'black'},
                                    {'label': 'Color', 'value': 'color'}])

        mod_grid.addWidget(self.image_type_label, 6, 0)
        mod_grid.addWidget(self.image_type, 6, 1, 1, 2)

        # #############################################################################################################
        # ######################################## Raster Mode ########################################################
        # #############################################################################################################
        # add a frame and inside add a grid box layout.
        self.raster_frame = FCFrame()
        self.layout.addWidget(self.raster_frame)

        raster_grid = GLay(v_spacing=5, h_spacing=3)
        self.raster_frame.setLayout(raster_grid)

        self.detail_label = FCLabel("%s:" % _('Level of detail'), bold=True)
        raster_grid.addWidget(self.detail_label, 0, 0, 1, 2)

        # Mask value of the imported image when image monochrome
        self.mask_bw_entry = FCSpinner()
        self.mask_bw_entry.set_range(0, 255)

        self.mask_bw_label = FCLabel("%s <b>B/W</b>:" % _('Mask value'))
        self.mask_bw_label.setToolTip(
            _("Mask for monochrome image.\n"
              "Takes values between [0 ... 255].\n"
              "Decides the level of details to include\n"
              "in the resulting geometry.\n"
              "0 means no detail and 255 means everything \n"
              "(which is totally black).")
        )
        raster_grid.addWidget(self.mask_bw_label, 2, 0)
        raster_grid.addWidget(self.mask_bw_entry, 2, 1)

        # Mask value of the imported image for RED color when image color
        self.mask_r_entry = FCSpinner()
        self.mask_r_entry.set_range(0, 255)

        self.mask_r_label = FCLabel("%s <b>R:</b>" % _('Mask value'))
        self.mask_r_label.setToolTip(
            _("Mask for RED color.\n"
              "Takes values between [0 ... 255].\n"
              "Decides the level of details to include\n"
              "in the resulting geometry.")
        )
        raster_grid.addWidget(self.mask_r_label, 4, 0)
        raster_grid.addWidget(self.mask_r_entry, 4, 1)

        # Mask value of the imported image for GREEN color when image color
        self.mask_g_entry = FCSpinner()
        self.mask_g_entry.set_range(0, 255)

        self.mask_g_label = FCLabel("%s <b>G:</b>" % _('Mask value'))
        self.mask_g_label.setToolTip(
            _("Mask for GREEN color.\n"
              "Takes values between [0 ... 255].\n"
              "Decides the level of details to include\n"
              "in the resulting geometry.")
        )
        raster_grid.addWidget(self.mask_g_label, 6, 0)
        raster_grid.addWidget(self.mask_g_entry, 6, 1)

        # Mask value of the imported image for BLUE color when image color
        self.mask_b_entry = FCSpinner()
        self.mask_b_entry.set_range(0, 255)

        self.mask_b_label = FCLabel("%s <b>B:</b>" % _('Mask value'))
        self.mask_b_label.setToolTip(
            _("Mask for BLUE color.\n"
              "Takes values between [0 ... 255].\n"
              "Decides the level of details to include\n"
              "in the resulting geometry.")
        )
        raster_grid.addWidget(self.mask_b_label, 8, 0)
        raster_grid.addWidget(self.mask_b_entry, 8, 1)

        # #############################################################################################################
        # ######################################## Tracing Mode #######################################################
        # #############################################################################################################
        # add a frame and inside add a grid box layout.
        self.trace_frame = FCFrame()
        self.layout.addWidget(self.trace_frame)

        trace_grid = GLay(v_spacing=5, h_spacing=3)
        self.trace_frame.setLayout(trace_grid)

        # B/W Threshold
        self.threshold_lbl = FCLabel('%s:' % _("Threshold"))
        self.threshold_lbl.setToolTip(
            _("B/W only.\n"
              "A pixel darker than this value [0 ... 255] is traced.")
        )
        self.threshold_entry = FCSpinner()
        self.threshold_entry.set_range(0, 255)
        self.threshold_entry.setSingleStep(1)

        trace_grid.addWidget(self.threshold_lbl, 0, 0)
        trace_grid.addWidget(self.threshold_entry, 0, 1)

        # Options Control Mode
        self.control_lbl = FCLabel('%s:' % _('Control'), color='indigo', bold=True)
        self.control_lbl.setToolTip(
            _("Tracing control.")
        )

        self.control_radio = RadioSet([
            {'label': _("Presets"), 'value': 'presets'},
            {'label': _("Options"), 'value': 'options'}
        ])

        trace_grid.addWidget(self.control_lbl, 1, 0)
        trace_grid.addWidget(self.control_radio, 1, 1)

        # --------------------------------------------------
        # Presets Frame
        # --------------------------------------------------
        self.preset_frame = QtWidgets.QFrame()
        self.preset_frame.setContentsMargins(0, 0, 0, 0)
        trace_grid.addWidget(self.preset_frame, 2, 0, 1, 2)

        preset_grid = GLay(v_spacing=5, h_spacing=3)
        preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_frame.setLayout(preset_grid)

        # Presets
        self.presets_lbl = FCLabel('%s:' % _('Presets'))
        self.presets_lbl.setToolTip(
            _("Options presets to control the tracing.\n"
              "- Default: straight segments, good for PCB artwork\n"
              "- Detailed: keeps small features and more colors\n"
              "- Smooth: curves, for logos and drawings\n"
              "- Photo: removes noise, for photographs")
        )

        # the order of the items is the order of PRESET_NAMES
        self.presets_combo = FCComboBox2()
        self.presets_combo.addItems([_("Default"), _("Detailed"), _("Smooth"), _("Photo")])
        preset_grid.addWidget(self.presets_lbl, 0, 0)
        preset_grid.addWidget(self.presets_combo, 0, 1)

        # --------------------------------------------------
        # Options Frame
        # --------------------------------------------------
        self.options_frame = QtWidgets.QFrame()
        self.options_frame.setContentsMargins(0, 0, 0, 0)
        trace_grid.addWidget(self.options_frame, 4, 0, 1, 2)

        options_grid = GLay(v_spacing=5, h_spacing=3)
        options_grid.setContentsMargins(0, 0, 0, 0)
        self.options_frame.setLayout(options_grid)

        # Curve Fitting
        self.curve_lbl = FCLabel('%s:' % _("Curve"))
        self.curve_lbl.setToolTip(
            _("How the outlines are made.\n"
              "- Polygon: straight segments\n"
              "- Spline: smooth curves\n"
              "- Pixel: the pixel edges, without fitting")
        )
        # the order of the items is the order of CURVE_MODES
        self.curve_combo = FCComboBox2()
        self.curve_combo.addItems([_("Polygon"), _("Spline"), _("Pixel")])

        options_grid.addWidget(self.curve_lbl, 0, 0)
        options_grid.addWidget(self.curve_combo, 0, 1)

        # Filter Speckle
        self.speckle_lbl = FCLabel('%s:' % _("Filter Speckle"))
        self.speckle_lbl.setToolTip(
            _("Patches smaller than this size (in pixels) are discarded.")
        )
        self.speckle_entry = FCSpinner()
        self.speckle_entry.set_range(0, 128)
        self.speckle_entry.setSingleStep(1)

        options_grid.addWidget(self.speckle_lbl, 2, 0)
        options_grid.addWidget(self.speckle_entry, 2, 1)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        options_grid.addWidget(separator_line, 4, 0, 1, 2)

        # Colors Section
        self.colors_lbl = FCLabel('%s' % _("Colors"), bold=True)
        self.colors_lbl.setToolTip(
            _("Color only.")
        )
        options_grid.addWidget(self.colors_lbl, 6, 0, 1, 2)

        # Color Precision
        self.color_precision_lbl = FCLabel('%s:' % _("Precision"))
        self.color_precision_lbl.setToolTip(
            _("Number of significant bits of each RGB channel [1 ... 8].\n"
              "Lower values merge more colors.")
        )
        self.color_precision_entry = FCSpinner()
        self.color_precision_entry.set_range(1, 8)
        self.color_precision_entry.setSingleStep(1)

        options_grid.addWidget(self.color_precision_lbl, 8, 0)
        options_grid.addWidget(self.color_precision_entry, 8, 1)

        # Gradient Step
        self.layer_diff_lbl = FCLabel('%s:' % _("Gradient Step"))
        self.layer_diff_lbl.setToolTip(
            _("Color difference between the layers of a gradient [0 ... 255].\n"
              "Higher values make fewer layers.")
        )
        self.layer_diff_entry = FCSpinner()
        self.layer_diff_entry.set_range(0, 255)
        self.layer_diff_entry.setSingleStep(1)

        options_grid.addWidget(self.layer_diff_lbl, 10, 0)
        options_grid.addWidget(self.layer_diff_entry, 10, 1)

        separator_line = QtWidgets.QFrame()
        separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        options_grid.addWidget(separator_line, 12, 0, 1, 2)

        # Spline Section
        self.spline_lbl = FCLabel('%s' % _("Spline"), bold=True)
        self.spline_lbl.setToolTip(
            _("Spline curve only.")
        )
        options_grid.addWidget(self.spline_lbl, 14, 0, 1, 2)

        # Corner Threshold
        self.corner_lbl = FCLabel('%s:' % _("Corner"))
        self.corner_lbl.setToolTip(
            _("Minimum angle (in degrees) to be considered a corner.")
        )
        self.corner_entry = FCSpinner()
        self.corner_entry.set_range(0, 180)
        self.corner_entry.setSingleStep(1)

        options_grid.addWidget(self.corner_lbl, 16, 0)
        options_grid.addWidget(self.corner_entry, 16, 1)

        # Segment Length
        self.length_lbl = FCLabel('%s:' % _("Segment Length"))
        self.length_lbl.setToolTip(
            _("Curves are subdivided into segments of this length [3.5 ... 10].\n"
              "Lower values make more segments.")
        )
        self.length_entry = FCDoubleSpinner()
        self.length_entry.set_precision(1)
        self.length_entry.set_range(3.5, 10.0)
        self.length_entry.setSingleStep(0.5)

        options_grid.addWidget(self.length_lbl, 18, 0)
        options_grid.addWidget(self.length_entry, 18, 1)

        # Splice Threshold
        self.splice_lbl = FCLabel('%s:' % _("Splice"))
        self.splice_lbl.setToolTip(
            _("Minimum angle displacement (in degrees) to splice a spline.")
        )
        self.splice_entry = FCSpinner()
        self.splice_entry.set_range(0, 180)
        self.splice_entry.setSingleStep(1)

        options_grid.addWidget(self.splice_lbl, 20, 0)
        options_grid.addWidget(self.splice_entry, 20, 1)

        GLay.set_common_column_size([par_grid, mod_grid, raster_grid, trace_grid, preset_grid, options_grid], 0)

        # Buttons
        self.import_button = FCButton(_("Import image"))
        self.import_button.setIcon(QtGui.QIcon(self.app.resource_location + '/image32.png'))
        self.import_button.setToolTip(
            _("Open a image of raster type and then import it in FlatCAM.")
        )
        self.layout.addWidget(self.import_button)

        self.layout.addStretch(1)

        # #################################### FINSIHED GUI ###########################
        # #############################################################################

        # Signals
        self.import_mode_radio.activated_custom.connect(self.on_import_image_mode)
        self.control_radio.activated_custom.connect(self.on_tracing_control_radio)
        self.presets_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.curve_combo.currentIndexChanged.connect(self.on_curve_mode)

    def on_image_type(self, val):
        # tracing: the threshold is for B/W, the color options are for Color
        is_color = val == 'color'
        self.threshold_lbl.setDisabled(is_color)
        self.threshold_entry.setDisabled(is_color)
        for wdg in (self.colors_lbl, self.color_precision_lbl, self.color_precision_entry, self.layer_diff_lbl,
                    self.layer_diff_entry):
            wdg.setDisabled(not is_color)

        if val == 'color':
            self.mask_r_label.setDisabled(False)
            self.mask_r_entry.setDisabled(False)
            self.mask_g_label.setDisabled(False)
            self.mask_g_entry.setDisabled(False)
            self.mask_b_label.setDisabled(False)
            self.mask_b_entry.setDisabled(False)

            self.mask_bw_label.setDisabled(True)
            self.mask_bw_entry.setDisabled(True)
        else:
            self.mask_r_label.setDisabled(True)
            self.mask_r_entry.setDisabled(True)
            self.mask_g_label.setDisabled(True)
            self.mask_g_entry.setDisabled(True)
            self.mask_b_label.setDisabled(True)
            self.mask_b_entry.setDisabled(True)

            self.mask_bw_label.setDisabled(False)
            self.mask_bw_entry.setDisabled(False)

    def on_import_image_mode(self, val):
        if val == 'raster':
            self.raster_frame.show()
            self.trace_frame.hide()
        else:
            self.raster_frame.hide()
            self.trace_frame.show()

    def on_tracing_control_radio(self, val):
        if val == 'presets':
            self.preset_frame.show()
            self.options_frame.hide()
        else:
            self.preset_frame.hide()
            self.options_frame.show()

    def on_preset_changed(self, idx):
        # copy the preset into the Options, so the Options start from it
        opt = PRESETS[PRESET_NAMES[idx]]
        self.curve_combo.set_value(CURVE_MODES.index(opt['mode']))
        self.speckle_entry.set_value(opt['filter_speckle'])
        self.color_precision_entry.set_value(opt['color_precision'])
        self.layer_diff_entry.set_value(opt['layer_difference'])
        self.corner_entry.set_value(opt['corner_threshold'])
        self.length_entry.set_value(opt['length_threshold'])
        self.splice_entry.set_value(opt['splice_threshold'])
        self.on_curve_mode(self.curve_combo.get_value())

    def on_curve_mode(self, idx):
        is_spline = CURVE_MODES[idx] == 'spline'
        for wdg in (self.spline_lbl, self.corner_lbl, self.corner_entry, self.length_lbl, self.length_entry,
                    self.splice_lbl, self.splice_entry):
            wdg.setDisabled(not is_spline)
