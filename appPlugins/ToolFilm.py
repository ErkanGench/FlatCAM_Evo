# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 3/10/2019                                          #
# MIT Licence                                              #
# ##########################################################

from PyQt6 import QtWidgets, QtCore, QtGui
from appTool import AppTool
from defaults import AppDefaults
from appGUI.GUIElements import VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox, \
    FCComboBox2, RadioSet, FCDoubleSpinner, FCSpinner, FCFileSaveDialog, OptionalHideInputSection

from camlib import flatten_shapely_geometry

import logging
import math
import re

from shapely import LineString, Point, Polygon, LinearRing
from shapely.affinity import scale, skew
from shapely.ops import unary_union

import gettext
import appTranslation as fcTranslate
import builtins

from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPM
from reportlab.lib.units import inch, mm
from reportlab.lib.pagesizes import landscape, portrait

from svglib.svglib import svg2rlg
from io import StringIO

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class Film(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)

        self.decimals = self.app.decimals
        self.units = self.app.app_units

        # #############################################################################################################
        # ######################################## Tool GUI ###########################################################
        # #############################################################################################################
        self.ui = FilmUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName

        # #############################################################################################################
        # #####################################    Signals     ########################################################
        # #############################################################################################################
        self.connect_signals_at_init()
        # #############################################################################################################

        self.screen_dpi = 96

    def app_option(self, key):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        return self.app.options.get(key, app_defaults.get(key, AppDefaults.factory_defaults.get(key)))

    def on_type_obj_index_changed(self, val):
        obj_type = 2 if val == 'geo' else 0
        self.ui.tf_object_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.tf_object_combo.setCurrentIndex(0)
        self.ui.tf_object_combo.obj_type = {
            "grb": "gerber", "geo": "geometry"
        }[self.ui.tf_type_obj_combo.get_value()]

    def on_type_box_index_changed(self, val):
        obj_type = 2 if val == 'geo' else 0
        self.ui.tf_box_combo.setRootModelIndex(self.app.collection.index(obj_type, 0, QtCore.QModelIndex()))
        self.ui.tf_box_combo.setCurrentIndex(0)
        self.ui.tf_box_combo.obj_type = {
            "grb": "gerber", "geo": "geometry"
        }[self.ui.tf_type_box_combo.get_value()]

    def on_object_selection_changed(self, current, previous):
        found_idx = None
        for tab_idx in range(self.app.ui.notebook.count()):
            if self.app.ui.notebook.tabText(tab_idx) == self.ui.pluginName:
                found_idx = True
                break

        if found_idx:
            try:
                name = current.indexes()[0].internalPointer().obj.obj_options['name']
                kind = current.indexes()[0].internalPointer().obj.kind

                if kind in ['gerber', 'geometry']:
                    obj_type = {'gerber': 'grb', 'geometry': 'geo'}[kind]
                    self.ui.tf_type_obj_combo.set_value(obj_type)
                    self.ui.tf_type_box_combo.set_value(obj_type)

                    self.ui.tf_object_combo.set_value(name)
                    self.ui.tf_box_combo.set_value(name)
            except Exception:
                pass

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolFilm()")

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

        self.app.ui.notebook.setTabText(2, _("Film"))

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut='Alt+L', **kwargs)

    def connect_signals_at_init(self):
        # #############################################################################
        # ############################ SIGNALS ########################################
        # #############################################################################
        self.ui.level.toggled.connect(self.on_level_changed)

        self.ui.film_object_button.clicked.connect(self.on_film_creation)
        self.ui.tf_type_obj_combo.activated_custom.connect(self.on_type_obj_index_changed)
        self.ui.tf_type_box_combo.activated_custom.connect(self.on_type_box_index_changed)

        self.ui.film_type.activated_custom.connect(self.ui.on_film_type)
        self.ui.source_punch.activated_custom.connect(self.ui.on_punch_source)
        self.ui.file_type_radio.activated_custom.connect(self.ui.on_file_type)

        self.app.proj_selection_changed.connect(self.on_object_selection_changed)

        self.ui.reset_button.clicked.connect(self.set_tool_ui)

    def set_tool_ui(self):

        self.clear_ui(self.layout)
        self.ui = FilmUI(layout=self.layout, app=self.app)
        self.add_object_creation_controls()
        self.pluginName = self.ui.pluginName
        self.connect_signals_at_init()

        self.reset_fields()

        app_option = self.app_option

        f_type = app_option("tools_film_polarity") or 'neg'
        self.ui.film_type.set_value(str(f_type))
        self.ui.on_film_type(val=f_type)

        b_entry = app_option("tools_film_boundary") or 0.0
        self.ui.boundary_entry.set_value(float(b_entry))

        scale_stroke_width = app_option("tools_film_scale_stroke") or 0.0
        self.ui.film_scale_stroke_entry.set_value(float(scale_stroke_width))

        self.ui.punch_cb.set_value(False)
        self.ui.source_punch.set_value('exc')

        self.ui.film_scale_cb.set_value(app_option("tools_film_scale_cb"))
        self.ui.film_scalex_entry.set_value(float(app_option("tools_film_scale_x_entry")))
        self.ui.film_scaley_entry.set_value(float(app_option("tools_film_scale_y_entry")))
        self.ui.scale_ref_combo.set_value(app_option("tools_film_scale_ref"))

        self.ui.film_skew_cb.set_value(app_option("tools_film_skew_cb"))
        self.ui.film_skew_type_combo.set_value(app_option("tools_film_skew_type"))
        self.ui.film_skewx_entry.set_value(float(app_option("tools_film_skew_x_entry")))
        self.ui.film_skewy_entry.set_value(float(app_option("tools_film_skew_y_entry")))
        self.ui.skew_ref_combo.set_value(app_option("tools_film_skew_ref"))

        self.ui.film_mirror_cb.set_value(app_option("tools_film_mirror_cb"))
        self.ui.film_mirror_axis.set_value(app_option("tools_film_mirror_axis_radio"))
        self.ui.file_type_radio.set_value(app_option("tools_film_file_type_radio"))
        self.ui.orientation_radio.set_value(app_option("tools_film_orientation"))
        self.ui.pagesize_combo.set_value(app_option("tools_film_pagesize"))

        self.ui.png_dpi_spinner.set_value(app_option("tools_film_png_dpi"))

        self.ui.convex_box_cb.set_value(app_option("tools_film_shape"))
        self.ui.rounded_cb.set_value(app_option("tools_film_rounded"))

        obj = self.app.collection.get_active()
        if obj:
            obj_name = obj.obj_options['name']
            if obj.kind == 'gerber':
                # run once to make sure that the obj_type attribute is updated in the FCComboBox
                self.ui.tf_type_obj_combo.set_value('grb')
                self.ui.tf_type_box_combo.set_value('grb')
                # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
                self.on_type_obj_index_changed(val='grb')
                self.on_type_box_index_changed(val='grb')

            elif obj.kind == 'geometry':
                # run once to make sure that the obj_type attribute is updated in the FCComboBox
                self.ui.tf_type_obj_combo.set_value('geo')
                self.ui.tf_type_box_combo.set_value('geo')
                # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
                self.on_type_obj_index_changed(val='geo')
                self.on_type_box_index_changed(val='geo')

            self.ui.tf_object_combo.set_value(obj_name)
            self.ui.tf_box_combo.set_value(obj_name)
        else:
            # run once to make sure that the obj_type attribute is updated in the FCComboBox
            self.ui.tf_type_obj_combo.set_value('grb')
            self.ui.tf_type_box_combo.set_value('grb')
            # run once to update the obj_type attribute in the FCCombobox so the last object is showed in cb
            self.on_type_obj_index_changed(val='grb')
            self.on_type_box_index_changed(val='grb')

        # Show/Hide Advanced Options
        app_mode = app_option("global_app_level")
        self.change_level(app_mode)

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
        if not checked:
            self.ui.level.setText('%s' % _('Beginner'))
            self.ui.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: green;
                                        }
                                        """)

            self.ui.film_adj_label.hide()
            self.ui.adj_frame.hide()

            self.ui.film_scale_cb.set_value(False)
            self.ui.film_skew_cb.set_value(False)
            self.ui.film_mirror_cb.set_value(False)
            self.ui.film_scale_stroke_entry.set_value(0.0)

        else:
            self.ui.level.setText('%s' % _('Advanced'))
            self.ui.level.setStyleSheet("""
                                        QToolButton
                                        {
                                            color: red;
                                        }
                                        """)

            self.ui.film_adj_label.show()
            self.ui.adj_frame.show()

            app_option = self.app_option

            self.ui.film_scale_cb.set_value(app_option("tools_film_scale_cb"))
            self.ui.film_skew_cb.set_value(app_option("tools_film_skew_cb"))
            self.ui.film_mirror_cb.set_value(app_option("tools_film_mirror_cb"))

            scale_stroke_width = app_option("tools_film_scale_stroke") or 0.0
            self.ui.film_scale_stroke_entry.set_value(float(scale_stroke_width))

    def on_film_creation(self):
        self.app.log.debug("ToolFilm.Film.on_film_creation() started ...")

        try:
            name = self.ui.tf_object_combo.currentText()
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s %s' %
                                 (_("No object is selected."), _("Load an object for Film and retry.")))
            return

        try:
            boxname = self.ui.tf_box_combo.currentText()
        except Exception:
            self.app.inform.emit('[ERROR_NOTCL] %s %s' %
                                 (_("No object is selected."), _("Load an object for Box and retry.")))
            return

        if name == '' or boxname == '':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object is selected."))
            return

        scale_stroke_width = float(self.ui.film_scale_stroke_entry.get_value())
        source = self.ui.source_punch.get_value()
        file_type = self.ui.file_type_radio.get_value()

        # #################################################################
        # ################ STARTING THE JOB ###############################
        # #################################################################

        self.app.inform.emit(_("Generating Film ..."))

        if self.ui.film_type.get_value() == "pos":

            if self.ui.punch_cb.get_value() is False:
                self.generate_positive_normal_film(name, boxname, factor=scale_stroke_width, ftype=file_type)
            else:
                self.generate_positive_punched_film(name, boxname, source, factor=scale_stroke_width, ftype=file_type)
        else:
            self.generate_negative_film(name, boxname, factor=scale_stroke_width, ftype=file_type)

    def read_transform_params(self):
        """
        Read the scale, skew and mirror settings from the UI.

        :return:    the keyword parameters for transform_geometry()
        :rtype:     dict
        """
        reference_list = ['center', 'bottomleft', 'topleft', 'bottomright', 'topright']

        params = {
            'scale_factor_x': None, 'scale_factor_y': None, 'scale_type': 0,
            'scale_reference': reference_list[int(self.ui.scale_ref_combo.get_value())],
            'skew_factor_x': None, 'skew_factor_y': None, 'skew_type': 0,
            'skew_reference': reference_list[int(self.ui.skew_ref_combo.get_value())],
            'mirror': None
        }

        if self.ui.film_scale_cb.get_value():
            scale_type = self.ui.film_scale_type_combo.get_value()
            params['scale_type'] = scale_type
            # a "length" does nothing at 0.0, a "factor" does nothing at 1.0
            neutral_val = 0.0 if scale_type == 0 else 1.0
            if self.ui.film_scalex_entry.get_value() != neutral_val:
                params['scale_factor_x'] = self.ui.film_scalex_entry.get_value()
            if self.ui.film_scaley_entry.get_value() != neutral_val:
                params['scale_factor_y'] = self.ui.film_scaley_entry.get_value()

        if self.ui.film_skew_cb.get_value():
            if self.ui.film_skewx_entry.get_value() != 0.0:
                params['skew_factor_x'] = self.ui.film_skewx_entry.get_value()
            if self.ui.film_skewy_entry.get_value() != 0.0:
                params['skew_factor_y'] = self.ui.film_skewy_entry.get_value()
            params['skew_type'] = self.ui.film_skew_type_combo.get_value()

        if self.ui.film_mirror_cb.get_value():
            params['mirror'] = self.ui.film_mirror_axis.get_value()

        return params

    def get_film_filename(self, caption, name, ftype):
        filter_ext = {
            'svg': "SVG Files (*.SVG);;All Files (*.*)",
            'png': "PNG Files (*.PNG);;All Files (*.*)",
        }.get(ftype, "PDF Files (*.PDF);;All Files (*.*)")

        try:
            filename, _f = FCFileSaveDialog.get_saved_filename(
                caption=caption,
                directory=self.app.get_last_save_folder() + '/' + name + '_film',
                ext_filter=filter_ext)
        except TypeError:
            filename, _f = FCFileSaveDialog.get_saved_filename(caption=caption, ext_filter=filter_ext)

        return str(filename)

    def generate_positive_normal_film(self, name, boxname, factor, ftype='svg'):
        self.app.log.debug("ToolFilm.Film.generate_positive_normal_film() started ...")

        params = self.read_transform_params()

        filename = self.get_film_filename(_("Export positive film"), name, ftype)
        if filename == "":
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
            return

        self.export_positive_handler(name, boxname, filename, scale_stroke_factor=factor, opacity_val=1.0,
                                     ftype=ftype, **params)

    def generate_positive_punched_film(self, name, boxname, source, factor, ftype='svg'):
        film_obj = self.app.collection.get_by_name(name)
        film_geo = unary_union(flatten_shapely_geometry(film_obj.solid_geometry))

        if source == 'exc':
            self.app.log.debug("ToolFilm.Film.generate_positive_punched_film() with Excellon source started ...")

            exc_obj = self.app.collection.get_by_name(self.ui.exc_combo.currentText())
            if exc_obj is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' %
                                     _("No Excellon object selected. Load an object for punching reference and retry."))
                return 'fail'

            punched_solid_geometry = film_geo.difference(
                unary_union(flatten_shapely_geometry(exc_obj.solid_geometry)))
        else:
            self.app.log.debug("ToolFilm.Film.generate_positive_punched_film() with Pad center source started ...")

            punch_size = float(self.ui.punch_size_spinner.get_value())

            punching_geo = []
            for aperture in film_obj.tools.values():
                aperture_type = aperture.get('type', '')
                if aperture_type == "REG":
                    continue

                if aperture_type == 'C':
                    too_big = punch_size >= float(aperture.get('size', 0.0))
                else:
                    too_big = punch_size >= float(aperture.get('width', 0.0)) or \
                              punch_size >= float(aperture.get('height', 0.0))
                if too_big:
                    self.app.inform.emit('[ERROR_NOTCL] %s' %
                                         _("Failed. Punch hole size "
                                           "is bigger than some of the apertures in the Gerber object."))
                    return 'fail'

                # the records are dicts, not geometries: flatten_shapely_geometry() raises on them
                for elem in aperture.get('geometry', []):
                    if isinstance(elem.get('follow'), Point):
                        punching_geo.append(elem['follow'].buffer(punch_size / 2))

            punching_geo = unary_union(punching_geo)
            # an intersects() test is much faster than a compare of the punched geometry with the source geometry
            if punching_geo.is_empty or not film_geo.intersects(punching_geo):
                self.app.inform.emit('[WARNING_NOTCL] %s' %
                                     _("Failed. The new object geometry "
                                       "is the same as the one in the source object geometry..."))
                return 'fail'
            punched_solid_geometry = film_geo.difference(punching_geo)

        def init_func(new_obj, app_obj):
            # Shapely geometries are immutable: no copy is necessary
            new_obj.solid_geometry = punched_solid_geometry

        new_obj = self.new_object('gerber', name + "_punched", init_func, source=film_obj)
        if isinstance(new_obj, str):
            return 'fail'

        # the collection adds a suffix to the name if the name is in use
        self.generate_positive_normal_film(new_obj.obj_options['name'], boxname, factor=factor, ftype=ftype)

    def generate_negative_film(self, name, boxname, factor, ftype='svg'):
        self.app.log.debug("ToolFilm.Film.generate_negative_film() started ...")

        params = self.read_transform_params()
        border = self.ui.boundary_entry.get_value() or 0

        filename = self.get_film_filename(_("Export negative film"), name, ftype)
        if filename == "":
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Cancelled."))
            return

        self.export_negative_handler(name, boxname, filename, border, scale_stroke_factor=factor, ftype=ftype,
                                     use_convex_hull=self.ui.convex_box_cb.get_value(),
                                     rounded_box=self.ui.rounded_cb.get_value(), **params)

    def export_negative_handler(self, obj_name, box_name, filename, boundary,
                                scale_stroke_factor=0.00,
                                scale_factor_x=None, scale_factor_y=None, scale_reference='center', scale_type=0,
                                skew_factor_x=None, skew_factor_y=None, skew_reference='center', skew_type=0,
                                mirror=None, opacity_val=1.0,
                                use_thread=True, ftype='svg', use_convex_hull=False, rounded_box=False):
        """
        Exports a Geometry Object to an SVG file in negative.

        :param obj_name:            the name of the FlatCAM object to be saved as SVG
        :param box_name:            the name of the FlatCAM object to be used as delimitation
                                    of the content to be saved
        :param filename:            Path to the SVG file to save to.
        :param boundary:            thickness of a black border to surround all the features
        :param scale_stroke_factor: factor by which to change/scale the thickness of the features
        :param scale_factor_x:      factor to scale the svg geometry on the X axis
        :param scale_factor_y:      factor to scale the svg geometry on the Y axis
        :param scale_reference:     reference to use for transformation.
                                    Values: 'center', 'bottomleft', 'topleft', 'bottomright', 'topright'
        :param scale_type:          Values 0, 1 -> 'Length', 'Factor'
                                    Length means that the scaling is done by a specific length, factor means
                                    scaling by a ratio between what should be and what is
        :param skew_factor_x:       factor to skew the svg geometry on the X axis
        :param skew_factor_y:       factor to skew the svg geometry on the Y axis
        :param skew_reference:      reference to use for transformation.
                                    Values: 'center', 'bottomleft'
        :param skew_type:           Values 0, 1, 2 -> 'Length', 'Angle', 'Factor'
                                    Length means that the deformation is done by a specific length, angle means
                                    deformation by angle and factor means deformation by a ratio between what should be
                                    and what is
        :param mirror:              can be 'x' or 'y' or 'both'. Axis on which to mirror the svg geometry
        :param opacity_val:
        :param use_thread:          if to be run in a separate thread; boolean
        :param ftype:               the type of file for saving the film: 'svg', 'png' or 'pdf'
        :param use_convex_hull:     Bool; if True it will make the negative box to minimize the black coverage
        :param rounded_box:         Bool; if True the negative bounded box will have rounded corners
                                    Works only in case the object used as box has multiple geometries
        :return:
        """
        self.app.defaults.report_usage("export_negative_handler()")
        self.app.log.debug("Film.export_negative_handler()")

        transform = {
            'scale_factor_x': scale_factor_x, 'scale_factor_y': scale_factor_y,
            'scale_reference': scale_reference, 'scale_type': scale_type,
            'skew_factor_x': skew_factor_x, 'skew_factor_y': skew_factor_y,
            'skew_reference': skew_reference, 'skew_type': skew_type,
            'mirror': mirror
        }

        def make_document(svg_geo, box_geo, color, svg_units):
            return self.create_negative_svg(svg_geo=svg_geo, box_bounds=box_geo.bounds, r_box=rounded_box,
                                            box_geo=box_geo, c_hull=use_convex_hull, margin=boundary,
                                            color=color, opacity=opacity_val, svg_units=svg_units)

        return self.export_film(obj_name, box_name, filename, make_document, scale_stroke_factor, transform,
                                use_thread, ftype)

    def export_positive_handler(self, obj_name, box_name, filename,
                                scale_stroke_factor=0.00,
                                scale_factor_x=None, scale_factor_y=None, scale_reference='center', scale_type=0,
                                skew_factor_x=None, skew_factor_y=None, skew_reference='center', skew_type=0,
                                mirror=None, opacity_val=1.0,
                                use_thread=True, ftype='svg'):

        """
        Exports a Geometry Object to an SVG file in positive black.

        :param obj_name:            the name of the FlatCAM object to be saved
        :param box_name:            the name of the FlatCAM object to be used as delimitation of the content to be saved
        :param filename:            Path to the file to save to.
        :param scale_stroke_factor: factor by which to change/scale the thickness of the features
        :param scale_factor_x:      factor to scale the geometry on the X axis
        :param scale_factor_y:      factor to scale the geometry on the Y axis
        :param scale_reference:     reference to use for transformation.
                                    Values: 'center', 'bottomleft', 'topleft', 'bottomright', 'topright'
        :param scale_type:          Values 0, 1 -> 'Length', 'Factor'
                                    Length means that the deformation is done by a specific length, factor means
                                    scaling by a ratio between what should be and what is
        :param skew_factor_x:       factor to skew the geometry on the X axis
        :param skew_factor_y:       factor to skew the geometry on the Y axis
        :param skew_reference:      reference to use for transformation.
                                    Values: 'center', 'bottomleft'
        :param skew_type:           Values 0, 1, 2 -> 'Length', 'Angle', 'Factor'
                                    Length means that the deformation is done by a specific length, angle means
                                    deformation by angle and factor means deformation by a ratio between what should be
                                    and what is
        :param mirror:              can be 'x' or 'y' or 'both'. Axis on which to mirror the svg geometry
        :param opacity_val:
        :param use_thread:          if to be run in a separate thread; boolean
        :param ftype:               the type of file for saving the film: 'svg', 'png' or 'pdf'

        :return:
        """
        self.app.defaults.report_usage("export_positive_handler()")
        self.app.log.debug("Film.export_positive_handler()")

        transform = {
            'scale_factor_x': scale_factor_x, 'scale_factor_y': scale_factor_y,
            'scale_reference': scale_reference, 'scale_type': scale_type,
            'skew_factor_x': skew_factor_x, 'skew_factor_y': skew_factor_y,
            'skew_reference': skew_reference, 'skew_type': skew_type,
            'mirror': mirror
        }
        # Define a boundary around SVG; read here because the job can run in a worker thread
        margin = self.ui.boundary_entry.get_value() or 0

        def make_document(svg_geo, box_geo, color, svg_units):
            return self.create_positive_svg(svg_geo=svg_geo, box_bounds=box_geo.bounds, margin=margin, color=color,
                                            opacity=opacity_val, svg_units=svg_units)

        return self.export_film(obj_name, box_name, filename, make_document, scale_stroke_factor, transform,
                                use_thread, ftype)

    def export_film(self, obj_name, box_name, filename, make_document, scale_stroke_factor, transform,
                    use_thread, ftype):
        """
        Transform the object and the box, make the film document and save it, in a worker thread if requested.

        :param obj_name:            the name of the FlatCAM object to be saved
        :param box_name:            the name of the FlatCAM object that sets the film frame
        :param filename:            path to the file to save to
        :param make_document:       function(svg_geo, box_geo, color, svg_units) that returns the SVG document
        :param scale_stroke_factor: factor by which to change/scale the thickness of the features
        :param transform:           the keyword parameters for transform_geometry()
        :param use_thread:          if to be run in a separate thread; boolean
        :param ftype:               the type of file for saving the film: 'svg', 'png' or 'pdf'
        :return:                    None, or an error message if an object does not exist
        """
        if filename is None:
            filename = self.app_option("global_last_save_folder")

        obj = self.app.collection.get_by_name(str(obj_name))
        if obj is None:
            return "Could not retrieve object: %s" % obj_name

        box_obj = self.app.collection.get_by_name(str(box_name))
        if box_obj is None:
            self.app.inform.emit('[WARNING_NOTCL] %s: %s' % (_("No object Box. Using instead"), obj_name))
            box_obj = obj

        # read the GUI state here: the job can run in a worker thread
        p_size = self.ui.pagesize_combo.get_value()
        orientation = self.ui.orientation_radio.get_value()
        color = obj.obj_options.get('tools_film_color') or self.app_option('tools_film_color') or '#000000'
        self.screen_dpi = self.app.qapp.screens()[0].logicalDotsPerInch()
        screen_dpi = self.screen_dpi
        dpi_rate = self.ui.png_dpi_spinner.get_value() / screen_dpi
        open_style = self.app_option("global_open_style")

        def make_film():
            self.app.log.debug("FilmTool.export_film().make_film()")

            obj_geo = self.get_film_geometry(obj)
            # the box sets the frame and the transformation origins; often it is the object itself
            if box_obj is obj:
                box_geo = transformed_obj_geo = self.transform_geometry([obj_geo], **transform)[0]
            else:
                box_geo, transformed_obj_geo = self.transform_geometry(
                    [self.get_film_geometry(box_obj), obj_geo], **transform)

            if ftype == 'png' and dpi_rate != 1:
                box_geo = scale(box_geo, dpi_rate, dpi_rate, origin=(0, 0))
                transformed_obj_geo = box_geo if box_obj is obj else \
                    scale(transformed_obj_geo, dpi_rate, dpi_rate, origin=(0, 0))

            svg_geo = self.create_svg_geometry(transformed_obj_geo, scale_stroke_factor=scale_stroke_factor)
            doc_final = make_document(svg_geo, box_geo, color, obj.units.lower())

            ret = self.write_output_file(content2save=doc_final, filename=filename, file_type=ftype, p_size=p_size,
                                         orientation=orientation, source_bounds=obj.bounds(),
                                         box_bounds=box_geo.bounds, dpi=screen_dpi)
            if ret == 'fail':
                return 'fail'

            if open_style is False:
                self.app.file_opened.emit("SVG", filename)
            self.app.file_saved.emit("SVG", filename)
            self.app.inform.emit('[success] %s: %s' % (_("Film file exported to"), filename))

        if use_thread is True:
            def job_thread_film():
                with self.app.proc_container.new(_("Working...")):
                    try:
                        make_film()
                    except Exception as e:
                        self.app.log.error("Film.export_film() process -> %s" % str(e))
                        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))

            self.app.worker_task.emit({'fcn': job_thread_film, 'params': []})
        else:
            make_film()

    # Shapely writes its own colors and opacity in each SVG element; a regex pass changes them much faster than
    # a XML parse and it keeps the fill="none" of the lines. One pass that starts with a space is the fastest.
    svg_style_re = re.compile(r' (fill|stroke)="#[0-9a-fA-F]+"| opacity="[^"]*"')

    def create_svg_document(self, svg_geo, box_bounds, margin, color, opacity, svg_units, background=''):
        """
        Put the SVG elements made by Shapely in a SVG document, in the film color.

        :param svg_geo:     the SVG elements made by Shapely
        :param box_bounds:  bounds of the film frame, without the margin
        :param margin:      the frame is bigger with this value on all sides
        :param color:       fill and stroke color of the features
        :param opacity:     opacity of the features
        :param svg_units:   'mm' or 'in'
        :param background:  SVG element to put under the features
        :return:            the SVG document
        :rtype:             str
        """
        new_attr = {
            'fill': ' fill="%s"' % color,
            'stroke': ' stroke="%s"' % color,
            None: ' opacity="%s"' % opacity
        }
        features = self.svg_style_re.sub(lambda match: new_attr[match.group(1)], svg_geo)
        # one element on each line
        features = features.replace('><', '>\n<')

        xmin, ymin, xmax, ymax = box_bounds
        svgwidth = (xmax - xmin) + (2 * margin)
        svgheight = (ymax - ymin) + (2 * margin)

        # The transform flips the Y Axis so that everything renders properly within svg apps such as inkscape
        return '<?xml version="1.0" ?>\n' \
               '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" xmlns:xlink="http://www.w3.org/1999/xlink" ' \
               'width="%s%s" height="%s%s" viewBox="%s %s %s %s">\n' \
               '<g transform="scale(1,-1)">\n%s%s\n</g>\n</svg>\n' % (
                   svgwidth, svg_units, svgheight, svg_units,
                   xmin - margin, -(ymax + margin), svgwidth, svgheight,
                   background, features)

    def create_negative_svg(self, svg_geo, box_bounds, r_box, box_geo, c_hull, margin, color, opacity, svg_units):
        # The features have the inverted color, over a polygon in the film color

        # decide if to round the bounding box for the negative
        join_s = "round" if r_box else "mitre"

        if isinstance(box_geo, (LineString, LinearRing)):
            neg_geo = Polygon(box_geo)
        elif isinstance(box_geo, Polygon):
            neg_geo = Polygon(box_geo.exterior)
        elif c_hull:
            neg_geo = box_geo.convex_hull
        else:
            neg_geo = box_geo.envelope
        if margin:
            neg_geo = neg_geo.buffer(margin, join_style=join_s)

        points_container = ' '.join('%s, %s' % (x, y) for x, y in neg_geo.exterior.coords[:])
        background = '<polygon points="%s" id="neg_rect" style="fill:%s;opacity:1.0;stroke-width:0.0"/>\n' % \
                     (points_container, color)

        return self.create_svg_document(svg_geo, box_bounds, margin, self.get_complementary(color), opacity,
                                        svg_units, background=background)

    @staticmethod
    def get_complementary(color_param):
        # strip the # from the beginning
        our_color = color_param[1:]

        # convert the string into hex
        our_color = int(our_color, 16)

        # invert the three bytes
        # as good as substracting each of RGB component by 255(FF)
        comp_color = 0xFFFFFF ^ our_color

        # convert the color back to hex by prefixing a #
        comp_color = "#%06X" % comp_color

        # return the result
        return comp_color

    def create_positive_svg(self, svg_geo, box_bounds, margin, color, opacity, svg_units):
        return self.create_svg_document(svg_geo, box_bounds, margin, str(color), opacity, svg_units)

    def write_output_file(self, content2save, filename, file_type, p_size, orientation, source_bounds, box_bounds,
                          dpi=72):
        p_msg = '[ERROR_NOTCL] %s' % _("Permission denied, saving not possible.\n"
                                       "Most likely another app is holding the file open and not accessible.")
        if file_type == 'svg':
            try:
                with open(filename, 'w') as fp:
                    fp.write(content2save)
            except PermissionError:
                self.app.inform.emit(p_msg)
                return 'fail'
        elif file_type == 'png':
            try:
                doc_final = StringIO(content2save)
                drawing = svg2rlg(doc_final)
                renderPM.drawToFile(drawing, fn=filename, fmt='PNG', dpi=dpi)
            except PermissionError:
                self.app.inform.emit(p_msg)
                return 'fail'
            except Exception as e:
                self.app.log.error("FilmTool.write_output_file() --> PNG output --> %s" % str(e))
                return 'fail'
        else:  # PDF
            try:
                if self.units == 'IN':
                    unit = inch
                else:
                    unit = mm

                if p_size == 'Bounds':
                    page_size = None
                elif orientation == 'p':
                    page_size = portrait(self.ui.pagesize[p_size])
                else:
                    page_size = landscape(self.ui.pagesize[p_size])

                xmin, ymin, xmax, ymax = source_bounds
                if page_size:
                    # the page size is in points; the bounds are in the app units
                    page_xmax, page_ymax = (
                        page_size[0] / unit,
                        page_size[1] / unit
                    )
                else:
                    page_xmax, page_ymax = xmax, ymax

                if xmax < 0 or ymax < 0 or xmin > page_xmax or ymin > page_ymax:
                    err_msg = '[ERROR_NOTCL] %s %s' % \
                              (
                                  _("Failed."),
                                  _("The artwork has to be within the selected page size in order to be visible.\n"
                                    "For 'Bounds' page size, it needs to be in the first quadrant.")
                              )
                    self.app.inform.emit(err_msg)
                    return 'fail'

                doc_final = StringIO(content2save)
                drawing = svg2rlg(doc_final)

                if p_size == 'Bounds':
                    renderPDF.drawToFile(drawing, filename)
                else:
                    my_canvas = canvas.Canvas(filename, pagesize=page_size)
                    my_canvas.translate(box_bounds[0] * unit, box_bounds[1] * unit)
                    renderPDF.draw(drawing, my_canvas, 0, 0)
                    my_canvas.save()
            except PermissionError:
                self.app.inform.emit(p_msg)
                return 'fail'
            except Exception as e:
                self.app.log.error("FilmTool.write_output_file() --> PDF output --> %s" % str(e))
                return 'fail'

    @staticmethod
    def get_film_geometry(obj):
        """
        Return the geometry of a FlatCAM object as one Shapely geometry.

        :param obj:     FlatCAM object
        :return:        Shapely geometry
        """
        if obj.kind.lower() == 'geometry' and obj.multigeo:
            flat_geo = []
            for tool in obj.tools:
                flat_geo += obj.flatten(obj.tools[tool]['solid_geometry'])
            return unary_union(flat_geo)
        return unary_union(obj.flatten())

    @staticmethod
    def transform_geometry(geo_list, scale_factor_x=None, scale_factor_y=None, scale_reference='center', scale_type=0,
                           skew_factor_x=None, skew_factor_y=None,
                           skew_reference='center', skew_type=0, mirror=None):
        """
        Scale, skew and mirror Shapely geometries all in the same way. The bounds of the first geometry (the film box)
        set the origins and the factors, so the other geometries keep their position in the box.

        :param geo_list:    list of Shapely geometries
        :return:            list of the transformed Shapely geometries, in the same order
        """
        geo_list = list(geo_list)

        # SCALING
        if scale_factor_x or scale_factor_y:
            xmin, ymin, xmax, ymax = geo_list[0].bounds
            ref_scale_val = {
                'topleft': (xmin, ymax),
                'bottomleft': (xmin, ymin),
                'topright': (xmax, ymax),
                'bottomright': (xmax, ymin)
            }.get(scale_reference, ((xmin + xmax) / 2, (ymin + ymax) / 2))

            def scale_value(factor, size):
                if not factor:
                    return 1.0
                if scale_type == 1:     # "factor"
                    return factor
                # "length": the ratio that makes the size bigger with this length
                return (size + factor) / size if size else 1.0

            val_x = scale_value(scale_factor_x, xmax - xmin)
            val_y = scale_value(scale_factor_y, ymax - ymin)
            geo_list = [scale(geo, val_x, val_y, origin=ref_scale_val) for geo in geo_list]

        # SKEWING
        if skew_factor_x or skew_factor_y:
            xmin, ymin, xmax, ymax = geo_list[0].bounds
            if skew_reference == 'bottomleft':
                ref_skew_val = (xmin, ymin)
                lever = 1.0
            else:
                ref_skew_val = ((xmin + xmax) / 2, (ymin + ymax) / 2)
                lever = 0.5

            def skew_angle(factor, size, other_size):
                if not factor:
                    return 0.0
                if skew_type == 1:  # "angle"
                    return factor
                if skew_type == 0:  # "length"
                    offset = factor
                else:   # "ratio"
                    offset = size * factor - size
                return math.degrees(math.atan2(offset, other_size * lever))

            skew_angle_x = skew_angle(skew_factor_x, xmax - xmin, ymax - ymin)
            skew_angle_y = skew_angle(skew_factor_y, ymax - ymin, xmax - xmin)
            geo_list = [skew(geo, skew_angle_x, skew_angle_y, origin=ref_skew_val) for geo in geo_list]

        if mirror in ('x', 'y', 'both'):
            xmin, ymin, xmax, ymax = geo_list[0].bounds
            center = ((xmin + xmax) / 2, (ymin + ymax) / 2)
            fact_x = -1.0 if mirror in ('y', 'both') else 1.0
            fact_y = -1.0 if mirror in ('x', 'both') else 1.0
            geo_list = [scale(geo, fact_x, fact_y, origin=center) for geo in geo_list]

        return geo_list

    @staticmethod
    def create_svg_geometry(geom, scale_stroke_factor):
        """
        Return SVG geometry made from a Shapely geometry collection property of the `obj` object

        :param geom:                Shapely geometry collection
        :type geom:
        :param scale_stroke_factor: multiplication factor for the SVG stroke-width used within shapely's svg export
                                    If 0 or less which is invalid then default to 0.01
                                    This value appears to work for zooming, and getting the output svg line width
                                    to match that viewed on screen with FlatCam
                                    MS: I choose a factor of 0.01 so the scale is right for PCB UV film
        :type scale_stroke_factor:  float
        :return:                    SVG geometry
        :rtype:
        """

        if scale_stroke_factor <= 0:
            scale_stroke_factor = 0.01

        # Convert to a SVG file
        svg_elem = geom.svg(scale_factor=scale_stroke_factor)
        return svg_elem

    def reset_fields(self):
        self.ui.tf_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.ui.tf_box_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))


class FilmUI:

    pluginName = _("Film")

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
            _("Create a positive/negative film for UV exposure.")
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
        # Source Object Frame
        # #############################################################################################################
        self.obj_combo_label = FCLabel('%s' % _("Source Object"), color='darkorange', bold=True)
        self.obj_combo_label.setToolTip(
            _("Excellon object for drilling/milling operation.")
        )
        self.tools_box.addWidget(self.obj_combo_label)

        obj_frame = FCFrame()
        self.tools_box.addWidget(obj_frame)

        obj_grid = GLay(v_spacing=5, h_spacing=3)
        obj_frame.setLayout(obj_grid)

        # Type of object for which to create the film
        self.tf_type_obj_combo = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                           {'label': _('Geometry'), 'value': 'geo'}])

        self.tf_type_obj_combo_label = FCLabel('%s:' % _("Type"))
        self.tf_type_obj_combo_label.setToolTip(
            _("Specify the type of object for which to create the film.\n"
              "The object can be of type: Gerber or Geometry.\n"
              "The selection here decide the type of objects that will be\n"
              "in the Film Object combobox.")
        )
        obj_grid.addWidget(self.tf_type_obj_combo_label, 0, 0)
        obj_grid.addWidget(self.tf_type_obj_combo, 0, 1)

        # List of objects for which we can create the film
        self.tf_object_combo = FCComboBox()
        self.tf_object_combo.setModel(self.app.collection)
        self.tf_object_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.tf_object_combo.is_last = True

        obj_grid.addWidget(self.tf_object_combo, 2, 0, 1, 2)

        # Type of Box Object to be used as an envelope for film creation
        # Within this we can create negative
        self.tf_type_box_combo = RadioSet([{'label': _('Gerber'), 'value': 'grb'},
                                           {'label': _('Geometry'), 'value': 'geo'}])

        self.tf_type_box_combo_label = FCLabel('%s:' % _("Box Type"))
        self.tf_type_box_combo_label.setToolTip(
            _("Specify the type of object to be used as an container for\n"
              "film creation. It can be: Gerber or Geometry type."
              "The selection here decide the type of objects that will be\n"
              "in the Box Object combobox.")
        )
        obj_grid.addWidget(self.tf_type_box_combo_label, 4, 0)
        obj_grid.addWidget(self.tf_type_box_combo, 4, 1)

        # Box
        self.tf_box_combo = FCComboBox()
        self.tf_box_combo.setModel(self.app.collection)
        self.tf_box_combo.setRootModelIndex(self.app.collection.index(0, 0, QtCore.QModelIndex()))
        self.tf_box_combo.is_last = True

        obj_grid.addWidget(self.tf_box_combo, 6, 0, 1, 2)

        # separator_line = QtWidgets.QFrame()
        # separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        # separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        # obj_grid.addWidget(separator_line, 8, 0, 1, 2)

        # #############################################################################################################
        # Adjustments Frame
        # #############################################################################################################
        self.film_adj_label = FCLabel('%s' % _("Adjustments"), color='green', bold=True)
        self.film_adj_label.setToolTip(
            _("Compensate print distortions.")
        )

        self.tools_box.addWidget(self.film_adj_label)

        self.adj_frame = FCFrame()
        self.tools_box.addWidget(self.adj_frame)

        adj_grid = GLay(v_spacing=5, h_spacing=3)
        self.adj_frame.setLayout(adj_grid)

        # Scale Geometry
        self.film_scale_cb = FCCheckBox('%s' % _("Scale"))
        self.film_scale_cb.setToolTip(
            _("A value greater than 1 will compact the film\n"
              "while a value less than 1 will jolt it.")
        )
        adj_grid.addWidget(self.film_scale_cb, 2, 0, 1, 2)

        # Scale Type
        self.film_scale_type_lbl = FCLabel('%s:' % _("Type"))
        self.film_scale_type_lbl.setToolTip(
            _("'Length' -> scale by a length value\n"
              "'Factor' -> scale by a ratio")
        )
        self.film_scale_type_combo = FCComboBox2()
        self.film_scale_type_combo.addItems([_("Length"), _("Factor")])

        adj_grid.addWidget(self.film_scale_type_lbl, 4, 0)
        adj_grid.addWidget(self.film_scale_type_combo, 4, 1)

        # Scale X
        self.film_scalex_label = FCLabel('%s:' % _("X val"))
        self.film_scalex_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.film_scalex_entry.set_range(-10000.0000, 10000.0000)
        self.film_scalex_entry.set_precision(self.decimals)
        self.film_scalex_entry.setSingleStep(0.01)

        adj_grid.addWidget(self.film_scalex_label, 6, 0)
        adj_grid.addWidget(self.film_scalex_entry, 6, 1)

        # Scale Y
        self.film_scaley_label = FCLabel('%s:' % _("Y val"))
        self.film_scaley_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.film_scaley_entry.set_range(-10000.0000, 10000.0000)
        self.film_scaley_entry.set_precision(self.decimals)
        self.film_scaley_entry.setSingleStep(0.01)

        adj_grid.addWidget(self.film_scaley_label, 7, 0)
        adj_grid.addWidget(self.film_scaley_entry, 7, 1)

        # Scale reference
        self.scale_ref_label = FCLabel('%s:' % _("Reference"))
        self.scale_ref_label.setToolTip(
            _("The reference point to be used as origin for the adjustment.")
        )

        self.scale_ref_combo = FCComboBox2()
        self.scale_ref_combo.addItems(
            [_('Center'), _('Bottom Left'), _('Top Left'), _('Bottom Right'), _('Top right')])

        adj_grid.addWidget(self.scale_ref_label, 10, 0)
        adj_grid.addWidget(self.scale_ref_combo, 10, 1)

        self.ois_scale = OptionalHideInputSection(self.film_scale_cb,
                                                  [
                                                      self.film_scale_type_lbl,
                                                      self.film_scale_type_combo,
                                                      self.film_scalex_label,
                                                      self.film_scalex_entry,
                                                      self.film_scaley_label,
                                                      self.film_scaley_entry,
                                                      self.scale_ref_label,
                                                      self.scale_ref_combo
                                                  ])

        self.scale_separator_line = QtWidgets.QFrame()
        self.scale_separator_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.scale_separator_line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        adj_grid.addWidget(self.scale_separator_line, 12, 0, 1, 2)

        # Skew Geometry
        self.film_skew_cb = FCCheckBox('%s' % _("Skew"))
        self.film_skew_cb.setToolTip(
            _("Positive values will skew to the right\n"
              "while negative values will skew to the left.")
        )
        adj_grid.addWidget(self.film_skew_cb, 14, 0, 1, 2)

        # Skew Type
        self.film_skew_type_lbl = FCLabel('%s:' % _("Type"))
        self.film_skew_type_lbl.setToolTip(
            _("'Length' -> deform by a length value\n"
              "'Angle' -> deform by an angle\n"
              "'Ratio' -> deform by a ratio between what should be and what is")
        )
        self.film_skew_type_combo = FCComboBox2()
        self.film_skew_type_combo.addItems([_("Length"), _("Angle"), _("Factor")])

        adj_grid.addWidget(self.film_skew_type_lbl, 16, 0)
        adj_grid.addWidget(self.film_skew_type_combo, 16, 1)

        # Skew X
        self.film_skewx_label = FCLabel('%s:' % _("X val"))
        self.film_skewx_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.film_skewx_entry.set_range(-10000.0000, 10000.0000)
        self.film_skewx_entry.set_precision(self.decimals)
        self.film_skewx_entry.setSingleStep(0.01)

        adj_grid.addWidget(self.film_skewx_label, 18, 0)
        adj_grid.addWidget(self.film_skewx_entry, 18, 1)

        # Skew Y
        self.film_skewy_label = FCLabel('%s:' % _("Y val"))
        self.film_skewy_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.film_skewy_entry.set_range(-10000.0000, 10000.0000)
        self.film_skewy_entry.set_precision(self.decimals)
        self.film_skewy_entry.setSingleStep(0.01)

        adj_grid.addWidget(self.film_skewy_label, 20, 0)
        adj_grid.addWidget(self.film_skewy_entry, 20, 1)

        # Skew Reference
        self.skew_ref_label = FCLabel('%s:' % _("Reference"))
        self.skew_ref_label.setToolTip(
            _("The reference point to be used as origin for the adjustment.")
        )

        self.skew_ref_combo = FCComboBox2()
        self.skew_ref_combo.addItems(
            [_('Center'), _('Bottom Left')])

        adj_grid.addWidget(self.skew_ref_label, 22, 0)
        adj_grid.addWidget(self.skew_ref_combo, 22, 1)

        self.ois_skew = OptionalHideInputSection(self.film_skew_cb,
                                                 [
                                                     self.film_skew_type_lbl,
                                                     self.film_skew_type_combo,
                                                     self.film_skewx_label,
                                                     self.film_skewx_entry,
                                                     self.film_skewy_label,
                                                     self.film_skewy_entry,
                                                     self.skew_ref_label,
                                                     self.skew_ref_combo
                                                 ])

        self.skew_separator_line1 = QtWidgets.QFrame()
        self.skew_separator_line1.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.skew_separator_line1.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        adj_grid.addWidget(self.skew_separator_line1, 24, 0, 1, 2)

        # Mirror Geometry
        self.film_mirror_cb = FCCheckBox('%s' % _("Mirror"))
        self.film_mirror_cb.setToolTip(
            _("Mirror the film geometry on the selected axis or on both.")
        )
        adj_grid.addWidget(self.film_mirror_cb, 26, 0, 1, 2)

        self.film_mirror_axis = RadioSet([{'label': _('X'), 'value': 'x'},
                                          {'label': _('Y'), 'value': 'y'},
                                          {'label': _('Both'), 'value': 'both'}],
                                         compact=True)
        self.film_mirror_axis_label = FCLabel('%s:' % _("Axis"))
        self.film_mirror_axis_label.setToolTip(
            _("Mirror the film geometry on the selected axis or on both.")
        )

        adj_grid.addWidget(self.film_mirror_axis_label, 28, 0)
        adj_grid.addWidget(self.film_mirror_axis, 28, 1)

        self.ois_mirror = OptionalHideInputSection(self.film_mirror_cb,
                                                   [
                                                       self.film_mirror_axis_label,
                                                       self.film_mirror_axis
                                                   ])

        # #############################################################################################################
        # Parameters Frame
        # #############################################################################################################
        self.film_param_label = FCLabel('%s' % _("Parameters"), color='blue', bold=True)
        self.tools_box.addWidget(self.film_param_label)

        par_frame = FCFrame()
        self.tools_box.addWidget(par_frame)

        param_grid = GLay(v_spacing=5, h_spacing=3)
        par_frame.setLayout(param_grid)

        # Convex Shape
        # Surrounding convex box shape
        self.convex_box_label = FCLabel('%s:' % _("Convex Shape"))
        self.convex_box_label.setToolTip(
            _("Create a convex shape surrounding the entire PCB.\n"
              "If not checked the shape is rectangular.")
        )
        self.convex_box_cb = FCCheckBox()

        param_grid.addWidget(self.convex_box_label, 0, 0)
        param_grid.addWidget(self.convex_box_cb, 0, 1)

        # Rounded corners
        self.rounded_label = FCLabel('%s:' % _("Rounded"))
        self.rounded_label.setToolTip(
            _("Resulting geometry will have rounded corners.")
        )

        self.rounded_cb = FCCheckBox()

        param_grid.addWidget(self.rounded_label, 2, 0)
        param_grid.addWidget(self.rounded_cb, 2, 1)

        # Scale Stroke size
        self.film_scale_stroke_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.film_scale_stroke_entry.set_range(-999.9999, 999.9999)
        self.film_scale_stroke_entry.setSingleStep(0.01)
        self.film_scale_stroke_entry.set_precision(self.decimals)

        self.film_scale_stroke_label = FCLabel('%s:' % _("Scale Stroke"))
        self.film_scale_stroke_label.setToolTip(
            _("Scale the line stroke thickness of each feature in the SVG file.\n"
              "It means that the line that envelope each SVG feature will be thicker or thinner,\n"
              "therefore the fine features may be more affected by this parameter.")
        )
        param_grid.addWidget(self.film_scale_stroke_label, 4, 0)
        param_grid.addWidget(self.film_scale_stroke_entry, 4, 1)

        # Polarity
        self.film_type = RadioSet([{'label': _('Positive'), 'value': 'pos'},
                                   {'label': _('Negative'), 'value': 'neg'}],
                                  compact=True)
        self.film_type_label = FCLabel('%s:' % _("Polarity"))
        self.film_type_label.setToolTip(
            _("Generate a Positive black film or a Negative film.")
        )
        param_grid.addWidget(self.film_type_label, 6, 0)
        param_grid.addWidget(self.film_type, 6, 1)

        # Border for negative film generation
        self.boundary_entry = FCDoubleSpinner(callback=self.confirmation_message)
        self.boundary_entry.set_range(-999.9999, 999.9999)
        self.boundary_entry.setSingleStep(0.01)
        self.boundary_entry.set_precision(self.decimals)

        self.boundary_label = FCLabel('%s:' % _("Border"))
        self.boundary_label.setToolTip(
            _("Specify a border around the object.\n"
              "Only for negative film.\n"
              "It helps if we use as a Box Object the same \n"
              "object as in Film Object. It will create a thick\n"
              "black bar around the actual print allowing for a\n"
              "better delimitation of the outline features which are of\n"
              "white color like the rest and which may confound with the\n"
              "surroundings if not for this border.")
        )
        param_grid.addWidget(self.boundary_label, 8, 0)
        param_grid.addWidget(self.boundary_entry, 8, 1)

        self.boundary_label.hide()
        self.boundary_entry.hide()

        # Punch Drill holes
        self.punch_cb = FCCheckBox(_("Punch drill holes"))
        self.punch_cb.setToolTip(_("When checked the generated film will have holes in pads when\n"
                                   "the generated film is positive. This is done to help drilling,\n"
                                   "when done manually."))
        param_grid.addWidget(self.punch_cb, 10, 0, 1, 2)

        # this way I can hide/show the frame
        self.punch_frame = QtWidgets.QFrame()
        self.punch_frame.setContentsMargins(0, 0, 0, 0)
        param_grid.addWidget(self.punch_frame, 12, 0, 1, 2)

        punch_grid = GLay(v_spacing=5, h_spacing=3)
        punch_grid.setContentsMargins(0, 0, 0, 0)
        self.punch_frame.setLayout(punch_grid)

        self.ois_p = OptionalHideInputSection(self.punch_cb, [self.punch_frame])

        self.source_label = FCLabel('%s:' % _("Source"))
        self.source_label.setToolTip(
            _("The punch hole source can be:\n"
              "- Excellon -> an Excellon holes center will serve as reference.\n"
              "- Pad Center -> will try to use the pads center as reference.")
        )
        self.source_punch = RadioSet([{'label': _('Excellon'), 'value': 'exc'},
                                      {'label': _('Pad center'), 'value': 'pad'}],
                                     compact=True)
        punch_grid.addWidget(self.source_label, 0, 0)
        punch_grid.addWidget(self.source_punch, 0, 1)

        self.exc_combo = FCComboBox()
        self.exc_combo.setToolTip(
            _("Remove the geometry of Excellon from the Film to create the holes in pads.")
        )
        self.exc_combo.setModel(self.app.collection)
        self.exc_combo.setRootModelIndex(self.app.collection.index(1, 0, QtCore.QModelIndex()))
        self.exc_combo.is_last = True
        self.exc_combo.obj_type = "Excellon"

        punch_grid.addWidget(self.exc_combo, 2, 0, 1, 2)

        self.exc_combo.hide()

        self.punch_size_label = FCLabel('%s:' % _("Punch Size"))
        self.punch_size_label.setToolTip(_("The value here will control how big is the punch hole in the pads."))
        self.punch_size_spinner = FCDoubleSpinner(callback=self.confirmation_message)
        self.punch_size_spinner.set_range(0, 999.9999)
        self.punch_size_spinner.setSingleStep(0.1)
        self.punch_size_spinner.set_precision(self.decimals)

        punch_grid.addWidget(self.punch_size_label, 4, 0)
        punch_grid.addWidget(self.punch_size_spinner, 4, 1)

        self.punch_size_label.hide()
        self.punch_size_spinner.hide()

        # #############################################################################################################
        # Export Frame
        # #############################################################################################################
        self.export_label = FCLabel('%s' % _("Export"), color='red', bold=True)
        self.tools_box.addWidget(self.export_label)

        exp_frame = FCFrame()
        self.tools_box.addWidget(exp_frame)

        export_grid = GLay(v_spacing=5, h_spacing=3)
        exp_frame.setLayout(export_grid)

        self.file_type_label = FCLabel('%s:' % _("Film Type"))
        self.file_type_label.setToolTip(
            _("The file type of the saved film. Can be:\n"
              "- 'SVG' -> open-source vectorial format\n"
              "- 'PNG' -> raster image\n"
              "- 'PDF' -> portable document format")
        )

        # File type
        self.file_type_radio = RadioSet([{'label': _('SVG'), 'value': 'svg'},
                                         {'label': _('PNG'), 'value': 'png'},
                                         {'label': _('PDF'), 'value': 'pdf'}
                                         ], compact=True)

        export_grid.addWidget(self.file_type_label, 0, 0)
        export_grid.addWidget(self.file_type_radio, 0, 1)

        # Page orientation
        self.orientation_label = FCLabel('%s:' % _("Page Orientation"))
        self.orientation_label.setToolTip(_("Can be:\n"
                                            "- Portrait\n"
                                            "- Landscape"))

        self.orientation_radio = RadioSet([{'label': _('Portrait'), 'value': 'p'},
                                           {'label': _('Landscape'), 'value': 'l'},
                                           ], compact=True)

        # #############################################################################################################
        # ################################  New Grid ##################################################################
        # #############################################################################################################
        export_grid.addWidget(self.orientation_label, 2, 0)
        export_grid.addWidget(self.orientation_radio, 2, 1)

        # Page Size
        self.pagesize_label = FCLabel('%s:' % _("Page Size"))
        self.pagesize_label.setToolTip(_("A selection of standard ISO 216 page sizes."))

        self.pagesize_combo = FCComboBox()

        self.pagesize = {
            'Bounds': None,
            'A0': (841 * mm, 1189 * mm),
            'A1': (594 * mm, 841 * mm),
            'A2': (420 * mm, 594 * mm),
            'A3': (297 * mm, 420 * mm),
            'A4': (210 * mm, 297 * mm),
            'A5': (148 * mm, 210 * mm),
            'A6': (105 * mm, 148 * mm),
            'A7': (74 * mm, 105 * mm),
            'A8': (52 * mm, 74 * mm),
            'A9': (37 * mm, 52 * mm),
            'A10': (26 * mm, 37 * mm),

            'B0': (1000 * mm, 1414 * mm),
            'B1': (707 * mm, 1000 * mm),
            'B2': (500 * mm, 707 * mm),
            'B3': (353 * mm, 500 * mm),
            'B4': (250 * mm, 353 * mm),
            'B5': (176 * mm, 250 * mm),
            'B6': (125 * mm, 176 * mm),
            'B7': (88 * mm, 125 * mm),
            'B8': (62 * mm, 88 * mm),
            'B9': (44 * mm, 62 * mm),
            'B10': (31 * mm, 44 * mm),

            'C0': (917 * mm, 1297 * mm),
            'C1': (648 * mm, 917 * mm),
            'C2': (458 * mm, 648 * mm),
            'C3': (324 * mm, 458 * mm),
            'C4': (229 * mm, 324 * mm),
            'C5': (162 * mm, 229 * mm),
            'C6': (114 * mm, 162 * mm),
            'C7': (81 * mm, 114 * mm),
            'C8': (57 * mm, 81 * mm),
            'C9': (40 * mm, 57 * mm),
            'C10': (28 * mm, 40 * mm),

            # American paper sizes
            'LETTER': (8.5 * inch, 11 * inch),
            'LEGAL': (8.5 * inch, 14 * inch),
            'ELEVENSEVENTEEN': (11 * inch, 17 * inch),

            # From https://en.wikipedia.org/wiki/Paper_size
            'JUNIOR_LEGAL': (5 * inch, 8 * inch),
            'HALF_LETTER': (5.5 * inch, 8 * inch),
            'GOV_LETTER': (8 * inch, 10.5 * inch),
            'GOV_LEGAL': (8.5 * inch, 13 * inch),
            'LEDGER': (17 * inch, 11 * inch),
        }

        page_size_list = list(self.pagesize.keys())
        self.pagesize_combo.addItems(page_size_list)

        export_grid.addWidget(self.pagesize_label, 4, 0)
        export_grid.addWidget(self.pagesize_combo, 4, 1)

        self.on_film_type(val='hide')

        # PNG DPI
        self.png_dpi_label = FCLabel('%s:' % "PNG DPI")
        self.png_dpi_label.setToolTip(
            _("Default value is 96 DPI. Change this value to scale the PNG file.")
        )
        self.png_dpi_spinner = FCSpinner(callback=self.confirmation_message_int)
        self.png_dpi_spinner.set_range(0, 100000)

        export_grid.addWidget(self.png_dpi_label, 6, 0)
        export_grid.addWidget(self.png_dpi_spinner, 6, 1)

        self.png_dpi_label.hide()
        self.png_dpi_spinner.hide()

        GLay.set_common_column_size([adj_grid, param_grid, obj_grid, export_grid, punch_grid], 0)

        # Buttons
        self.film_object_button = FCButton(_("Save Film"), bold=True)
        self.film_object_button.setIcon(QtGui.QIcon(self.app.resource_location + '/save_as.png'))
        self.film_object_button.setToolTip(
            _("Create a Film for the selected object, within\n"
              "the specified box. Does not create a new \n "
              "FlatCAM object, but directly save it in the\n"
              "selected format.")
        )
        self.tools_box.addWidget(self.film_object_button)

        self.layout.addStretch(1)

        # ## Reset Tool
        self.reset_button = FCButton(_("Reset Tool"), bold=True)
        self.reset_button.setIcon(QtGui.QIcon(self.app.resource_location + '/reset32.png'))
        self.reset_button.setToolTip(
            _("Will reset the tool parameters.")
        )
        self.layout.addWidget(self.reset_button)

        # #################################### FINSIHED GUI ###########################
        # #############################################################################

    def on_film_type(self, val):
        type_of_film = val

        if type_of_film == 'neg':
            self.boundary_label.show()
            self.boundary_entry.show()
            self.punch_cb.set_value(False)  # required so the self.punch_frame it's hidden also by the signal emitted
            self.punch_cb.hide()
        else:
            self.boundary_label.hide()
            self.boundary_entry.hide()
            self.punch_cb.show()

    def on_file_type(self, val):
        if val == 'pdf':
            self.orientation_label.show()
            self.orientation_radio.show()
            self.pagesize_label.show()
            self.pagesize_combo.show()
            self.png_dpi_label.hide()
            self.png_dpi_spinner.hide()
        elif val == 'png':
            self.png_dpi_label.show()
            self.png_dpi_spinner.show()
            self.orientation_label.hide()
            self.orientation_radio.hide()
            self.pagesize_label.hide()
            self.pagesize_combo.hide()
        else:
            self.orientation_label.hide()
            self.orientation_radio.hide()
            self.pagesize_label.hide()
            self.pagesize_combo.hide()
            self.png_dpi_label.hide()
            self.png_dpi_spinner.hide()

    def on_punch_source(self, val):
        if val == 'pad' and self.punch_cb.get_value():
            self.punch_size_label.show()
            self.punch_size_spinner.show()
            self.exc_combo.hide()
        else:
            self.punch_size_label.hide()
            self.punch_size_spinner.hide()
            self.exc_combo.show()

        if val == 'pad' and self.tf_type_obj_combo.get_value() == 'geo':
            self.source_punch.set_value('exc')
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Using the Pad center does not work on Geometry objects. "
                                                          "Only a Gerber object has pads."))

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
