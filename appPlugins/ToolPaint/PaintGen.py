
from PyQt6 import QtWidgets     # noqa

from dataclasses import dataclass, field
from copy import copy, deepcopy

import numpy as np

import traceback
import logging

from shapely import (
    Polygon,
    MultiPolygon,
    total_bounds,
)
from shapely.ops import unary_union

from typing import TYPE_CHECKING, Union

import gettext
import appTranslation as fcTranslate
import builtins

from camlib import (
    grace,
    flatten_shapely_geometry,
    residual_cleanup,
)
from defaults import AppDefaults
from appParsers.feature_access import fused_solid
from appCommon.SafeEval import safe_eval
from appPlugins.ToolPaint import PaintModel

if TYPE_CHECKING:
    from appObjects.GerberObject import GerberObject
    from appObjects.GeometryObject import GeometryObject

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


class _PaintAppSnapshot:
    """Freeze generation options while forwarding live services and cancellation."""
    def __init__(self, app):
        self._app = app
        self.options = deepcopy(dict(app.options))
        self.defaults = dict(getattr(app, 'defaults', None) or AppDefaults.factory_defaults)
        self.units = app.units

    def __getattr__(self, name):
        return getattr(self._app, name)


def gerber_copper_for_paint(obj):
    """
    The copper of a Gerber object as one valid Polygon / MultiPolygon (``fused_solid``): the composed geometry with
    the polarity applied, repaired and fused. Nothing is changed on the object.
    """
    return fused_solid(obj)


@dataclass
class Params:
    units: str
    tool_ordering: int
    paint_method: int
    rest_machining_choice: bool
    simplification_value: float
    prog_plot: bool
    tools_storage: field(default_factory=dict)
    output_object_name: str | None
    run_threaded: bool
    rest_offset: float = 0.0
    source_tools: dict | None = None


class PaintGen:
    def __init__(self, tool):
        self.app = tool.app
        self.ui = tool.ui
        self.obj_name = tool.obj_name

        self.decimals = tool.decimals

        self.paint_obj = tool.paint_obj
        self.paint_tools = tool.paint_tools

        self.o_name = tool.o_name
        self.circle_steps = tool.circle_steps

        self.overlap = tool.overlap
        self.connect = tool.connect
        self.contour = tool.contour

        self.tooldia_list = tool.tooldia_list
        self.tool_type_item_options = tool.tool_type_item_options
        self.tooldia = tool.tooldia

        self.units = tool.units
        self.select_method = tool.select_method
        self.first_click = tool.first_click
        self.cursor_pos = tool.cursor_pos
        self.mouse_is_dragging = tool.mouse_is_dragging

        self.temp_shapes = tool.temp_shapes

        self.bound_obj_name = tool.bound_obj_name
        self.bound_obj = tool.bound_obj


        self.poly_drawn = tool.poly_drawn
        self.points = tool.points

        self.parent_tool = tool

    def on_paint_button_click(self):
        """
        Slot for clicking signal
        :return: None
        """

        self.app.defaults.report_usage("on_paint_button_click")
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        self.first_click = False
        self.cursor_pos = None
        self.mouse_is_dragging = False

        prog_plot = True if self.app.options.get(
            "tools_paint_plotting",
            app_defaults.get("tools_paint_plotting", AppDefaults.factory_defaults.get("tools_paint_plotting"))
        ) == 'progressive' else False
        if prog_plot:
            self.temp_shapes.clear(update=True)

        self.parent_tool.area_to_paint_list = []

        obj_type = self.ui.type_obj_radio.get_value()
        gerber_circle_steps = int(self.app.options.get(
            "gerber_circle_steps",
            app_defaults.get("gerber_circle_steps", AppDefaults.factory_defaults.get("gerber_circle_steps"))
        ))
        geometry_circle_steps = int(self.app.options.get(
            "geometry_circle_steps",
            app_defaults.get("geometry_circle_steps", AppDefaults.factory_defaults.get("geometry_circle_steps"))
        ))
        self.circle_steps = gerber_circle_steps if obj_type == 'gerber' else geometry_circle_steps
        self.obj_name = self.ui.obj_combo.currentText()

        # Get source object.
        try:
            self.paint_obj = self.app.collection.get_by_name(str(self.obj_name))
        except Exception as e:
            self.app.log.error("ToolPaint.on_paint_button_click() --> %s" % str(e))
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), self.obj_name))
            return

        if self.paint_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), self.paint_obj))
            return

        # test if the Geometry Object is multigeo with more than one tool and return Fail if True because
        # for now Paint don't work on MultiGeo with more than one tools
        if self.paint_obj.kind == 'geometry' and self.paint_obj.multigeo is True and len(self.paint_obj.tools) > 1:
            self.app.inform.emit('[ERROR_NOTCL] %s...' % _("Can't do Paint on MultiGeo geometries"))
            return 'Fail'

        self.o_name = '%s_mt_paint' % self.obj_name

        # use the selected tools in the tool table; get diameters
        self.tooldia_list = []
        table_items = self.ui.tools_table.selectedItems()
        sel_rows = {t.row() for t in table_items}
        if len(sel_rows) > 0:
            for row in sel_rows:
                try:
                    self.tooldia = float(self.ui.tools_table.item(row, 1).text())
                except ValueError:
                    # try to convert comma to decimal point. if it's still not working error message and return
                    try:
                        self.tooldia = float(self.ui.tools_table.item(row, 1).text().replace(',', '.'))
                    except ValueError:
                        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                        continue
                self.tooldia_list.append(self.tooldia)
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("There are no tools selected in the Tool Table."))
            return

        self.select_method = self.ui.select_method_combo.get_value()
        if self.select_method == 0:  # _("All")
            self.paint_poly_all(self.paint_obj, tooldia=self.tooldia_list, outname=self.o_name)

        elif self.select_method == 1:   # _("Polygon Selection")
            self._paint_poly_single()

        elif self.select_method == 2:   # _("Area Selection")
            self._paint_poly_area()

        elif self.select_method == 3:   # _("Reference Object")
            self._paint_poly_reference()

    def paint_area_selection_option(self, areas_to_paint_list: list[Polygon | MultiPolygon]):
        self.app.log.info("PaintGen.paint_area_selection_option() --> Painting the designated areas(s).")

        areas_to_paint_list = unary_union(areas_to_paint_list)
        if isinstance(areas_to_paint_list, MultiPolygon):
            areas_to_paint_list = list(areas_to_paint_list.geoms)
        elif isinstance(areas_to_paint_list, Polygon):
            areas_to_paint_list = [areas_to_paint_list]

        self.paint_poly_area_worker(
            painted_object=self.paint_obj,
            tooldia=self.tooldia_list,
            areas_to_paint=areas_to_paint_list,
            outname=self.o_name
        )

    def paint_polygon_worker(
            self,
            poly_g,
            tool_diameter,
            paint_method,
            over,
            conn,
            cont,
            prog_plot,
            obj,
    ):

        geometry_circle_steps = self.circle_steps
        apertures = None
        if paint_method == 3:
            app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
            geometry_circle_steps = self.app.options.get(
                "geometry_circle_steps",
                app_defaults.get("geometry_circle_steps", AppDefaults.factory_defaults.get("geometry_circle_steps", 64))
            )
            apertures = obj.tools

        def progress(method):
            messages = {
                2: _("Painting polygon with method: lines."),
                1: _("Failed. Painting polygon with method: seed."),
                0: _("Failed. Painting polygon with method: standard.")
            }
            self.app.inform.emit(messages[method])

        result = PaintModel.paint_polygon(
            poly_g, tool_diameter, paint_method, over, conn, cont, prog_plot, self.circle_steps,
            getattr(self.parent_tool, 'clear_polygon_shrink', None),
            getattr(self.parent_tool, 'clear_polygon_seed', None),
            getattr(self.parent_tool, 'clear_polygon_lines', None),
            apertures=apertures, geometry_circle_steps=geometry_circle_steps,
            fill_lines=getattr(self.parent_tool, 'fill_with_lines', None), progress=progress)
        if result is None:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _('Geometry could not be painted completely'))
        return result

    def paint_handler(
            self,
            painted_object: Union["GeometryObject", "GerberObject"],
            geometry,
            tooldia=None,
            order=None,
            method=None,
            outname=None,
            tools_storage=None,
            plot=True,
            rest=None,
            run_threaded=True,
    ):
        """
        Paints a given geometry.

        :param painted_object:             painted object
        :param geometry:        geometry to Paint
        :param tooldia:         Diameter of the painting tool
        :param order:           if the tools are ordered and how
        :param outname:         Name of the resulting Geometry Object.
        :param method:          choice out of _("Seed"), 'normal', 'lines'
        :param tools_storage:   whether to use the current tools_storage self.paints_tools or a different one.
                                Usage of the different one is related to when this function is called
                                from a TcL command.
        :param plot:            if the geometry is plotted; bool
        :param rest:            if rest machining apply here; bool
        :param run_threaded:
        :return: None
        """

        # Each queued callback owns its settings, not the shared controller's next job.
        self = copy(self)
        self.app = _PaintAppSnapshot(self.app)
        params = self._create_params(
            order=order,
            method=method,
            rest=rest,
            outname=outname,
            tools_storage=tools_storage,
            run_threaded=run_threaded
        )

        sorted_paint_tools = self._parse_tool_diameters(tooldia)
        if sorted_paint_tools == 'fail':
            return 'fail'
        sorted_paint_tools = list(sorted_paint_tools)

        proc = None
        if run_threaded:
            proc = self.app.proc_container.new('%s...' % _("Working"))
        else:
            self.app.proc_container.view.set_busy('%s...' % _("Working"))
            QtWidgets.QApplication.processEvents()

        def job_thread(app_instance, proc):
            ret = None
            try:
                if params.rest_machining_choice:
                    ret = self.parent_tool.new_object(
                        "geometry",
                        params.output_object_name,
                        lambda o, a: self._generate_rest_paint_worker(
                            o,
                            a,
                            params,
                            sorted_paint_tools,
                            geometry,
                            painted_object,
                            plot,
                        ),
                        plot=plot,
                        source=painted_object,
                        autoselected=False,
                    )
                else:
                    ret = self.parent_tool.new_object(
                        "geometry",
                        params.output_object_name,
                        lambda o, a: self._generate_paint_worker(
                            o, a, params, sorted_paint_tools, geometry, painted_object, plot),
                        plot=plot,
                        source=painted_object,
                        autoselected=False,
                    )
            except grace:
                app_instance.log.debug("PaintGen.paint_handler.job_thread() -> Graceful exit.")
                ret = 'fail'
            except Exception as err:
                app_instance.log.debug(f"PaintGen.paint_handler.job_thread() -> Exception: {str(err)}")
                traceback.print_stack()
                ret = 'fail'
            finally:
                if proc is not None:
                    proc.done()
                else:
                    app_instance.proc_container.view.set_idle()

            if ret == 'fail':
                self.app.inform.emit('[ERROR] %s' % _("Failed."))
                return 'fail'

            self.app.inform.emit('[success] %s' % _("Done."))

        if run_threaded:
            self.app.collection.promise(params.output_object_name)
            self.app.worker_task.emit({'fcn': job_thread, 'params': [self.app, proc]})
        else:
            return job_thread(app_instance=self.app, proc=proc)

    def _create_params(self, order, method, rest, outname, tools_storage, run_threaded):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        simplification_value = float(self.app.options.get(
            "tools_paint_simplification",
            app_defaults.get("tools_paint_simplification", AppDefaults.factory_defaults["tools_paint_simplification"])
        ))
        # Preferences store tolerances in mm; both workers consume geometry units.
        if self.app.units.upper() == 'IN':
            simplification_value /= 25.4
        rest_choice = rest if rest is not None else self.ui.rest_cb.get_value()
        source_tools = self.paint_tools if tools_storage is None else tools_storage
        return Params(
            units=self.app.units,
            tool_ordering=order if order is not None else self.ui.order_combo.get_value(),
            paint_method=method if method is not None else self.ui.method_combo.get_value(),
            rest_machining_choice=rest_choice,
            simplification_value=simplification_value,
            prog_plot=self.app.options.get(
                "tools_paint_plotting",
                app_defaults.get("tools_paint_plotting", AppDefaults.factory_defaults.get("tools_paint_plotting"))
            ) == 'progressive',
            tools_storage=deepcopy(source_tools),
            output_object_name=outname if outname is not None else self.obj_name + "_paint",
            run_threaded=run_threaded,
            rest_offset=self.ui.rest_offset_entry.get_value() if rest_choice else 0.0,
            source_tools=source_tools
        )

    def _parse_tool_diameters(self, tooldia):
        sorted_paint_tools = []
        if tooldia is not None:
            try:
                sorted_paint_tools = [float(safe_eval(dia)) for dia in tooldia.split(",") if dia != '']
            except AttributeError:
                if not isinstance(tooldia, list):
                    sorted_paint_tools = [float(tooldia)]
                else:
                    sorted_paint_tools = tooldia
        else:
            table_items = self.ui.tools_table.selectedItems()
            sel_rows = {t.row() for t in table_items}
            for row in sel_rows:
                try:
                    self.tooldia = float(self.ui.tools_table.item(row, 1).text())
                except ValueError:
                    try:
                        self.tooldia = float(self.ui.tools_table.item(row, 1).text().replace(',', '.'))
                    except ValueError:
                        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                        continue
                sorted_paint_tools.append(self.tooldia)
            if not sorted_paint_tools:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("There are no tools selected in the Tool Table."))
                return 'fail'
        return sorted_paint_tools

    def _find_tool_uid(self, tool_dia, tools_storage):
        return PaintModel.find_tool_uid(tool_dia, tools_storage, self.decimals)

    def _get_tool_params(self, tool_uid, tools_storage):
        return PaintModel.tool_params(tool_uid, tools_storage)

    def _buffer_geometry(self, geometry, offset):
        return PaintModel.buffer_geometry(geometry, offset)

    def _process_polygon(self, polygon, tool_dia, tool_params, params, painted_object):
        return self.paint_polygon_worker(
            polygon,
            tool_diameter=tool_dia,
            over=tool_params['over'],
            conn=tool_params['conn'],
            cont=tool_params['cont'],
            paint_method=params.paint_method,
            obj=painted_object,
            prog_plot=params.prog_plot,
        )

    def _simplify_geometry(self, geometry_list, simplification_value):
        return PaintModel.simplify_geometry(geometry_list, simplification_value)

    def _update_progress(self, current, total, old_disp_number):
        disp_number = int(np.interp(current, [0, total], [0, 100]))
        if old_disp_number < disp_number <= 100:
            self.app.proc_container.update_view_text(' %d%%' % disp_number)
            return disp_number
        return old_disp_number

    def _cleanup_progressive_plotting(self):
        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        if self.app.options.get(
            "tools_paint_plotting",
            app_defaults.get("tools_paint_plotting", AppDefaults.factory_defaults.get("tools_paint_plotting"))
        ) == 'progressive':
            self.temp_shapes.clear(update=True)

    def _remove_empty_tools(self, tools_storage):
        for uid in list(tools_storage.keys()):
            if not tools_storage[uid]['solid_geometry']:
                tools_storage.pop(uid, None)

    def _set_output_bounds(self, output_obj, solid_geometry):
        try:
            # Bounds don't need another topological union of the completed toolpaths.
            a, b, c, d = total_bounds(solid_geometry) if solid_geometry else (np.nan,) * 4
            output_obj.obj_options['xmin'] = a
            output_obj.obj_options['ymin'] = b
            output_obj.obj_options['xmax'] = c
            output_obj.obj_options['ymax'] = d
        except Exception as ee:
            self.app.log.error("ToolPaint.paint_poly.job_init() bounds error --> %s" % str(ee))
            return False
        return True

    def _validate_output_geometry(self, output_obj):
        has_solid_geo = sum(1 for uid in output_obj.tools if output_obj.tools[uid]['solid_geometry'])
        if has_solid_geo == 0:
            self.app.log.error(
                "There is no Painting Geometry in the file.\n"
                "Usually it means that the tool diameter is too big for the painted geometry.\n"
                "Change the painting parameters and try again."
            )
            return False
        return True

    def _generate_paint_worker(self, output_geo_object, app_obj, params, sorted_paint_tools, geometry, painted_object, plot):
        return self._generate_worker(output_geo_object, app_obj, params, sorted_paint_tools,
                                     geometry, painted_object, rest=False)

    def _generate_rest_paint_worker(self, output_geo_object, app_obj, params, sorted_paint_tools, geometry, painted_object, plot):
        return self._generate_worker(output_geo_object, app_obj, params, sorted_paint_tools,
                                     geometry, painted_object, rest=True)

    def _check_abort(self):
        QtWidgets.QApplication.processEvents()
        if self.app.abort_flag:
            raise grace

    def _tool_started(self, diameter):
        self.app.log.debug("Starting geometry processing for tool: %s" % str(diameter))
        self.app.inform.emit('[success] %s %s%s %s' % (
            _('Painting with tool diameter = '), str(diameter), self.units.lower(), _('started')))
        self.app.proc_container.update_view_text(' %d%%' % 0)

    def _report_warnings(self, warnings):
        for kind, error in warnings:
            if kind == 'cleanup':
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                    'Final paint finished. Some areas could not be painted with this tool.'))
            elif kind == 'skipped':
                self.app.inform.emit('[WARNING_NOTCL] %s %s' % (
                    _("A polygon could not be painted with tool diameter ="), error))
            elif kind == 'empty':
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    "There is no geometry to process or the tool diameter is too big."))
            else:
                self.app.log.error("Could not Paint the polygons. %s" % error)
                self.app.inform.emit('[ERROR] %s\n%s' % (_(
                    "Could not do Paint. Try a different combination of parameters. "
                    "Or a different method of Paint"), error))

    def _generate_worker(self, output, app_obj, params, diameters, geometry, painted_object, rest):
        def process_polygon(polygon, diameter, settings):
            return self._process_polygon(polygon, diameter, settings, params, painted_object)

        try:
            generate = PaintModel.generate_rest_paint if rest else PaintModel.generate_paint
            extra = {'rest_offset': getattr(params, 'rest_offset', 0.0)} if rest else {}
            result = generate(
                geometry, params.tools_storage, diameters, getattr(params, 'tool_ordering', 0),
                params.simplification_value, self.decimals, process_polygon,
                check_abort=self._check_abort, progress=self._update_progress, tool_started=self._tool_started,
                find_uid=self._find_tool_uid, get_params=self._get_tool_params,
                buffer=self._buffer_geometry, simplify=self._simplify_geometry, **extra)
            if result == 'fail':
                return 'fail'
            self._report_warnings(result['warnings'])
            finished = self._cleanup_result(
                geometry, result['tools'], result.get('output_tools', result['tools']), params, diameters,
                getattr(params, 'rest_offset', 0.0) if rest else None)
            self._report_warnings(finished['warnings'])
            tools = finished['tools']
            self._remove_empty_tools(tools)
            if not tools:
                return 'fail'
            solid_geometry = flatten_shapely_geometry(unary_union(finished['paths']))
            self._check_abort()
            for tool in tools.values():
                tool['data']['output_object_name'] = params.output_object_name
            output.tools = finished['output_tools'] if rest else dict(tools)
            for tool in output.tools.values():
                tool['data']['output_object_name'] = params.output_object_name
            output.solid_geometry = solid_geometry
            output.multigeo = True
            output.multitool = True
            output.obj_options['tools_mill_tooldia'] = '0.0' if rest else str(result['last_diameter'])
            if finished['residual'] is not None:
                output.paint_cleanup_residual = finished['residual']
            if not self._set_output_bounds(output, solid_geometry) or not self._validate_output_geometry(output):
                app_obj.inform.emit(_("Failed."))
                return 'fail'
            publication_tools = getattr(params, 'source_tools', None)
            if publication_tools is None:
                publication_tools = params.tools_storage
            publication_tools.clear()
            publication_tools.update(tools)
        except grace:
            return 'fail'
        finally:
            self._cleanup_progressive_plotting()

    def _cleanup_result(self, geometry, tools, output_tools, params, diameters, rest_offset):
        def process_polygon(polygon, diameter, settings):
            return self.paint_polygon_worker(
                polygon, diameter, 2 if params.paint_method == 3 else params.paint_method,
                settings['over'], settings['conn'], True, False, None)

        def cleanup(domain, diameter, previous, generate_paths, boundary_first):
            return residual_cleanup(self.app, domain, diameter, self.circle_steps, previous,
                                    generate_paths, physical=True, boundary_first=boundary_first)

        return PaintModel.final_cleanup(
            geometry, tools, output_tools, diameters, self.decimals, process_polygon, cleanup,
            rest_offset=rest_offset, check_abort=self._check_abort, find_uid=self._find_tool_uid,
            get_params=self._get_tool_params, buffer=self._buffer_geometry)

    def final_cleanup(self, output, params, diameters, geometry, rest_offset=None):
        """One final tool; residuals are targets, not new boundaries for the cutter."""
        result = self._cleanup_result(geometry, params.tools_storage, output.tools,
                                      params, diameters, rest_offset)
        if result['residual'] is None:
            return
        for tool in result['tools'].values():
            if 'paint_cleanup_start' in tool:
                tool['data']['output_object_name'] = params.output_object_name
        params.tools_storage.clear()
        params.tools_storage.update(result['tools'])
        output.tools = result['output_tools']
        output.paint_cleanup_residual = result['residual']
        self._report_warnings(result['warnings'])

    def paint_poly(
            self,
            obj: Union["GeometryObject", "GerberObject"],
            inside_pt=None,
            poly_list=None,
            tooldia=None,
            order=None,
            method=None,
            outname=None,
            tools_storage=None,
            plot=True,
            run_threaded=True,
    ):
        """
        Paints a polygon selected by clicking on its interior or by having a point coordinates given

        Note:
            * The margin is taken directly from the form.

        :param run_threaded:
        :param plot:
        :param poly_list:
        :param obj:             painted object
        :param inside_pt:       [x, y]
        :param tooldia:         Diameter of the painting tool
        :param order:           if the tools are ordered and how
        :param outname:         Name of the resulting Geometry Object.
        :param method:          choice out of _("Seed"), 'normal', 'lines'
        :param tools_storage:   whether to use the current tools_storage self.paints_tools or a different one.
                                Usage of the different one is related to when this function is called
                                from a TcL command.
        :return: None
        """

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        if obj.kind == 'gerber':
            # I don't do anything here, like buffering when the Gerber is loaded without buffering????!!!!
            if self.app.options.get(
                "gerber_buffering",
                app_defaults.get("gerber_buffering", AppDefaults.factory_defaults.get("gerber_buffering"))
            ) == 'no':
                msg = '%s %s %s' % (_("Paint Plugin."),
                                    _("Normal painting polygon task started."),
                                    _("Buffering geometry..."))
                self.app.inform.emit(msg)
            else:
                self.app.inform.emit('%s %s' % (_("Paint Plugin."), _("Normal painting polygon task started.")))

            if self.app.options.get(
                "tools_paint_plotting",
                app_defaults.get("tools_paint_plotting", AppDefaults.factory_defaults.get("tools_paint_plotting"))
            ) == 'progressive':
                obj.solid_geometry = gerber_copper_for_paint(obj)
        else:
            self.app.inform.emit('%s %s' % (_("Paint Plugin."), _("Normal painting polygon task started.")))

        if inside_pt and poly_list is None:
            polygon_list = PaintModel.select_polygon(obj.solid_geometry, inside_pt)
            if polygon_list:
                polygon_list = [polygon_list]
        elif (inside_pt is None and poly_list) or (inside_pt and poly_list):
            polygon_list = poly_list
        else:
            return

        # No polygon?
        if polygon_list is None:
            self.app.log.warning('No polygon found.')
            self.app.inform.emit('[WARNING] %s' % _('No polygon found.'))
            return "fail"

        return self.paint_handler(
            obj,
            polygon_list,
            tooldia=tooldia,
            order=order,
            method=method,
            outname=outname,
            tools_storage=tools_storage,
            plot=plot,
            run_threaded=run_threaded,
        )

    def paint_poly_all(
            self,
            obj: Union["GeometryObject", "GerberObject"],
            tooldia=None,
            order=None,
            method=None,
            outname=None,
            tools_storage=None,
            plot=True,
            run_threaded=True,
    ):
        """
        Paints all polygons in this object.

        :param obj:             painted object
        :param tooldia:         a tuple or single element made out of diameters of the tools to be used
        :param order:           if the tools are ordered and how
        :param outname:         name of the resulting object
        :param method:          choice out of _("Seed"), 'normal', 'lines'
        :param tools_storage:   whether to use the current tools_storage self.paints_tools or a different one.
                                Usage of the different one is related to when this function is called from
                                a TcL command.
        :param run_threaded:
        :param plot:
        :return:
        """

        def check_abort():
            if self.app.abort_flag:
                raise grace

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults
        if obj.kind == 'gerber':
            # I don't do anything here, like buffering when the Gerber is loaded without buffering????!!!!
            if self.app.options.get(
                "gerber_buffering",
                app_defaults.get("gerber_buffering", AppDefaults.factory_defaults.get("gerber_buffering"))
            ) == 'no':
                msg = '%s %s %s' % (_("Paint Plugin."), _("Paint all polygons task started."),
                                    _("Buffering geometry..."))
                self.app.inform.emit(msg)
            else:
                self.app.inform.emit('%s %s' % (_("Paint Plugin."), _("Paint all polygons task started.")))

            if self.app.options.get(
                "tools_paint_plotting",
                app_defaults.get("tools_paint_plotting", AppDefaults.factory_defaults.get("tools_paint_plotting"))
            ) == 'progressive':
                obj.solid_geometry = gerber_copper_for_paint(obj)
        else:
            self.app.inform.emit('%s %s' % (_("Paint Plugin."), _("Paint all polygons task started.")))

        try:
            painted_area = PaintModel.selection_geometry(obj.solid_geometry, check_abort)
        except grace:
            return 'fail'
        if painted_area is not None:
            self.flat_geometry = painted_area

        # No polygon?
        if not painted_area:
            self.app.log.warning('No polygon found.')
            self.app.inform.emit('[WARNING] %s' % _('No polygon found.'))
            return 'fail'

        return self.paint_handler(
            obj,
            painted_area,
            tooldia=tooldia,
            order=order,
            method=method,
            outname=outname,
            tools_storage=tools_storage,
            plot=plot,
            run_threaded=run_threaded,
        )

    def _paint_poly_single(self):
        self.parent_tool.paint_obj = self.paint_obj
        self.parent_tool.tooldia_list = self.tooldia_list

        # disengage the grid snapping since it may be hard to click on polygons with grid snapping on
        if self.app.ui.grid_snap_btn.isChecked():
            self.parent_tool.grid_status_memory = True
            self.app.ui.grid_snap_btn.trigger()
        else:
            self.parent_tool.grid_status_memory = False

        self.app.inform.emit('[WARNING_NOTCL] %s' % _("Click on a polygon to paint it."))

        self.app.plotcanvas.graph_event_connect(
            'mouse_release',
            self.parent_tool.on_single_poly_mouse_release,
        )
        self.app.plotcanvas.graph_event_connect(
            'key_press',
            self.parent_tool.on_key_press,
        )

        self.app.plotcanvas.graph_event_disconnect(
            'mouse_release',
            self.app.on_mouse_click_release_over_plot,
        )
        self.app.plotcanvas.graph_event_disconnect(
            'mouse_press',
            self.app.on_mouse_click_over_plot,
        )

        # disconnect flags
        self.parent_tool.poly_sel_disconnect_flag = True

    def _paint_poly_area(self):
        self.app.inform.emit('[WARNING_NOTCL] %s' % _("Click the start point of the area."))

        self.app.plotcanvas.graph_event_disconnect(
            'mouse_press',
            self.app.on_mouse_click_over_plot,
        )
        self.app.plotcanvas.graph_event_disconnect(
            'mouse_move',
            self.app.on_mouse_move_over_plot,
        )
        self.app.plotcanvas.graph_event_disconnect(
            'mouse_release',
            self.app.on_mouse_click_release_over_plot,
        )

        self.app.plotcanvas.graph_event_connect(
            'mouse_release',
            self.parent_tool.on_mouse_release,
        )
        self.app.plotcanvas.graph_event_connect(
            'mouse_move',
            self.parent_tool.on_mouse_move,
        )
        self.app.plotcanvas.graph_event_connect(
            'key_press',
            self.parent_tool.on_key_press,
        )

        # disconnect flags
        self.parent_tool.area_sel_disconnect_flag = True
        # disable the "notebook" until the process is finished
        self.app.ui.notebook.setDisabled(True)

    def _paint_poly_reference(self):
        self.bound_obj_name = self.ui.reference_combo.currentText()
        # Get source object.
        try:
            self.bound_obj = self.app.collection.get_by_name(self.bound_obj_name)
        except Exception:
            self.app.inform.emit(
                '[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), self.obj_name)
            )
            return "Could not retrieve object: %s" % self.obj_name

        self.paint_poly_ref(
            obj=self.paint_obj,
            sel_obj=self.bound_obj,
            tooldia=self.tooldia_list,
            outname=self.o_name,
        )

    def paint_poly_ref(
            self,
            obj,
            sel_obj,
            tooldia=None,
            order=None,
            method=None,
            outname=None,
            tools_storage=None,
            plot=True,
            run_threaded=True,
    ):
        """
        Paints all polygons in this object that are within the areas_to_paint object

        :param obj: painted object
        :param sel_obj: paint only what is inside this object bounds
        :param tooldia: a tuple or single element made out of diameters of the tools to be used
        :param order: if the tools are ordered and how
        :param outname: name of the resulting object
        :param method: choice out of _("Seed"), 'normal', 'lines'
        :param tools_storage: whether to use the current tools_storage self.paints_tools or a different one.
        Usage of the different one is related to when this function is called from a TcL command.
        :param run_threaded:
        :param plot:
        :return:
        """
        try:
            sel_rect = PaintModel.reference_area(sel_obj.solid_geometry)
        except Exception as e:
            self.app.log.error("ToolPaint.paint_poly_ref() --> %s" % str(e))
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object available."))
            return

        return self.paint_poly_area_worker(
            painted_object=obj,
            areas_to_paint=sel_rect,
            tooldia=tooldia,
            order=order,
            method=method,
            outname=outname,
            tools_storage=tools_storage,
            plot=plot,
            run_threaded=run_threaded,
        )

    def paint_poly_area_worker(
            self,
            painted_object: Union["GeometryObject", "GerberObject"],
            areas_to_paint: Union[Polygon, MultiPolygon] | list[Polygon | MultiPolygon],
            tooldia=None,
            order=None,
            method=None,
            outname=None,
            tools_storage=None,
            plot=True,
            run_threaded=True,
    ):
        """
        Paints all polygons in this object that are within the sel_obj object

        :param painted_object: painted object
        :param areas_to_paint: paint only what is inside this object bounds
        :param tooldia: a tuple or single element made out of diameters of the tools to be used
        :param order: if the tools are ordered and how
        :param outname: name of the resulting object
        :param method: choice out of _("Seed"), 'normal', 'lines'
        :param tools_storage: whether to use the current tools_storage self.paints_tools or a different one.
        Usage of the different one is related to when this function is called from a TcL command.
        :param run_threaded:
        :param plot:
        :return:
        """

        def check_abort():
            if self.app.abort_flag:
                raise grace

        app_defaults = getattr(self.app, "defaults", None) or AppDefaults.factory_defaults

        # this is where heavy lifting is done and creating the geometry to be painted
        if painted_object.kind == 'gerber':
            target_geo = gerber_copper_for_paint(painted_object)
        else:
            target_geo = unary_union(painted_object.solid_geometry)

        p_msg = f'{_("Paint Plugin.")} {_("Painting area task started.")}'
        if painted_object.kind == 'gerber':
            # I don't do anything here, like buffering when the Gerber is loaded without buffering????!!!!
            if self.app.options.get(
                "gerber_buffering",
                app_defaults.get("gerber_buffering", AppDefaults.factory_defaults.get("gerber_buffering"))
            ) == 'no':
                msg = '%s %s %s' % (_("Paint Plugin."),
                                    _("Painting area task started."),
                                    _("Buffering geometry..."))
                self.app.inform.emit(msg)
            else:
                self.app.inform.emit(p_msg)
        else:
            self.app.inform.emit(p_msg)

        try:
            p_geo_list = PaintModel.area_intersection(target_geo, areas_to_paint, check_abort)
        except grace:
            return 'fail'
        self.flat_geometry = p_geo_list

        # No polygon?
        if not p_geo_list:
            self.app.log.warning('ToolPaint.paint_poly_Area(). No geometry or the found geometry could not be painted.')
            self.app.inform.emit('[WARNING] %s' % _('No polygon found.'))
            return

        self.paint_handler(
            painted_object,
            p_geo_list,
            tooldia=tooldia,
            order=order,
            method=method,
            outname=outname,
            tools_storage=tools_storage,
            plot=plot,
            run_threaded=run_threaded,
        )
