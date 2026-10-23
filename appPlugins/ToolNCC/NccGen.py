
from PyQt6 import QtWidgets     # noqa

from dataclasses import dataclass, field
from copy import copy, deepcopy
import traceback
import logging

from shapely import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.geometry.base import BaseGeometry
from typing import TYPE_CHECKING, Union

import gettext
import appTranslation as fcTranslate
import builtins

from camlib import grace, flatten_shapely_geometry, residual_cleanup
from appParsers.feature_access import fused_solid
from appCommon.SafeEval import safe_eval
from appPlugins.ToolNCC import NccModel

if TYPE_CHECKING:
    from appObjects.GerberObject import GerberObject
    from appObjects.GeometryObject import GeometryObject
    from appMain import App

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

log = logging.getLogger('base')


def ncc_gerber_copper(obj, repair_buffer=None):
    """
    The copper of a Gerber object as one valid Polygon / MultiPolygon (``fused_solid``): the composed geometry with
    the polarity applied, repaired and fused. Nothing is changed on the object.

    :param repair_buffer:   if not None, a small tolerance buffer applied after the fuse (the NCC clip geometry keeps
                            the 1e-9 one it always had when the Gerber was loaded without buffering)
    """
    geo = fused_solid(obj)
    if repair_buffer is not None:
        geo = geo.buffer(repair_buffer)
    return geo


@dataclass
class Params:
    units: str
    tool_ordering: int
    clipping_type: int
    rest_machining_choice: bool
    simplification_value: float
    prog_plot: bool
    tools_storage: field(default_factory=dict)
    sorted_clear_tools: list[int | float | str]
    areas_to_clear_list: list[Polygon | MultiPolygon]
    output_object_name: str | None
    run_threaded: bool


class NccGen:
    """Legacy controller adapter and compatibility facade for GUI and Tcl callers.

    Geometry kernels live in NccModel; settings, signals and output-object writes stay here.
    """
    def __init__(self, tool):
        self.app = tool.app
        self.parent_tool = tool

        self.ui = tool.ui


        self.decimals = tool.app.decimals
        self.temp_shapes = tool.temp_shapes

        self.first_click = tool.first_click
        self.cursor_pos = tool.cursor_pos
        self.mouse_is_dragging = tool.mouse_is_dragging
        self.areas_to_clear_list = tool.areas_to_clear_list

        self.circle_steps = tool.circle_steps

        self.obj_name = tool.obj_name
        self.select_method = tool.select_method
        self.bound_obj_name = tool.bound_obj_name
        self.bound_obj = tool.bound_obj

        self.o_name = tool.o_name

        self.ncc_obj = tool.ncc_obj

        self.ncc_dia_list = []
        self.iso_dia_list = []
        self.tooldia = tool.tooldia
        self.ncc_tools: dict = tool.ncc_tools

        self.solid_geometry = tool.solid_geometry

    def on_ncc_click(self):
        """
        Slot for clicking signal
        :return: None
        """

        self.app.defaults.report_usage("on_ncc_click")

        self.first_click = False
        self.cursor_pos = None
        self.mouse_is_dragging = False
        should_check_validity = self.ui.valid_cb.get_value()

        prog_plot = True if self.app.options.get(
            "tools_ncc_plotting",
            self.app.defaults.get(
                "tools_ncc_plotting",
                self.app.defaults.factory_defaults.get("tools_ncc_plotting")
            )
        ) == 'progressive' else False
        if prog_plot:
            self.temp_shapes.clear(update=True)

        self.areas_to_clear_list = []

        obj_type = self.ui.type_obj_radio.get_value
        geo_steps = self.app.options.get(
            "geometry_circle_steps",
            self.app.defaults.get(
                "geometry_circle_steps",
                self.app.defaults.factory_defaults.get("geometry_circle_steps", 64)
            )
        )
        gerber_steps = self.app.options.get(
            "gerber_circle_steps",
            self.app.defaults.get(
                "gerber_circle_steps",
                self.app.defaults.factory_defaults.get("gerber_circle_steps", 64)
            )
        )
        self.circle_steps = int(gerber_steps) if obj_type == 'gerber' else int(geo_steps)
        self.obj_name = self.ui.obj_combo.currentText()

        # Get source object.
        try:
            self.ncc_obj = self.app.collection.get_by_name(self.obj_name)
        except Exception as e:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"),  str(self.obj_name)))
            return "Could not retrieve object: %s with error: %s" % (self.obj_name, str(e))

        if self.ncc_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Object not found"), str(self.obj_name)))
            return

        # Check tool validity
        if should_check_validity is True:
            # this is done in another Process
            self.parent_tool.find_safe_tooldia_multiprocessing()

        # use the selected tools in the tool table; get diameters for isolation
        self.iso_dia_list = []
        # use the selected tools in the tool table; get diameters for non-copper clear
        self.ncc_dia_list = []

        table_items = self.ui.tools_table.selectedItems()
        sel_rows = {t.row() for t in table_items}
        if len(sel_rows) > 0:
            for row in sel_rows:
                # try to convert comma to decimal point. if it's still not working error message and return
                try:
                    self.tooldia = float(self.ui.tools_table.item(row, 1).text().replace(',', '.'))
                except ValueError:
                    self.app.inform.emit('[ERROR_NOTCL] %s' % _("Wrong value format entered, use a number."))
                    continue

                # find out which tools are for isolation and which are for copper clearing
                for uid_k, uid_v in self.ncc_tools.items():
                    if round(uid_v['tooldia'], self.decimals) == round(self.tooldia, self.decimals):
                        if uid_v['data']['tools_ncc_operation'] == "iso":
                            self.iso_dia_list.append(self.tooldia)
                        else:
                            self.ncc_dia_list.append(self.tooldia)
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("There are no tools selected in the Tool Table."))
            return

        self.o_name = '%s_ncc' % self.obj_name

        self.select_method = self.ui.select_method_combo.get_value()
        if self.select_method == 0:   # Itself
            self.bound_obj_name = self.ui.obj_combo.currentText()
            # Get source object.
            try:
                self.bound_obj = self.app.collection.get_by_name(self.bound_obj_name)
            except Exception as e:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), self.bound_obj_name))
                return "Could not retrieve object: %s with error: %s" % (self.bound_obj_name, str(e))

            self.ncc_handler(cleared_object=self.ncc_obj,
                             clear_tooldia_list=self.ncc_dia_list,
                             iso_tooldia_list=self.iso_dia_list,
                             outname=self.o_name,
                             tools_storage=self.ncc_tools)
        elif self.select_method == 1:   # Area Selection
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
            # disable the "notebook UI" until finished
            self.app.ui.notebook.setDisabled(True)
        elif self.select_method == 2:   # Reference Object
            self.bound_obj_name = self.ui.reference_combo.currentText()
            # Get source object.
            try:
                self.bound_obj = self.app.collection.get_by_name(self.bound_obj_name)
            except Exception as e:
                self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), self.bound_obj_name))
                return "Could not retrieve object: %s. Error: %s" % (self.bound_obj_name, str(e))

            self.ncc_handler(
                cleared_object=self.ncc_obj,
                sel_obj=self.bound_obj,
                clear_tooldia_list=self.ncc_dia_list,
                iso_tooldia_list=self.iso_dia_list,
                outname=self.o_name,
            )

    def compute_clipping_region(
            self,
            cleared_object: Union["GerberObject", "GeometryObject"],
            clipping_object: Union["GerberObject", "GeometryObject"] = None,
            clipping_type: int = 0,
            clipping_areas: Union[Polygon, MultiPolygon] | list[Polygon | MultiPolygon] = None,
    ) -> tuple[BaseGeometry | list[BaseGeometry] | None, str | None]:
        """
        Will return a geometry that dictate the total extent of the area to be copper cleared

        :param cleared_object:      The object to be copper cleared
        :param clipping_object:     The object whose geometry will be used as delimitation for copper clearing - if selected
        :param clipping_type:       Index that choose what kind of reference to be used for copper clearing extent
                                        0 -> _('Itself')
                                        1 -> _('Area Selection')
                                        2 -> _('Reference Object')
        :param clipping_areas:      The geometry that will be used as delimitation for copper clearing - if selected
        :return:                    The geometry that surrounds the area to be cleared and the kind of object from which the
                                    geometry originated (string: "gerber", "geometry" or None)
        """

        # when using an external object geometry as the area constraint for the copper clearing,
        box_kind = clipping_object.kind if clipping_object is not None else None
        env_obj = None

        if clipping_type == 0:     # _('Itself')
            return self._copper_clear_area_for_entire_object(cleared_object), box_kind

        if clipping_type == 1:   # _("Area Selection")
            if clipping_areas is None:
                return None, None
            return self._copper_clear_area_from_selection_areas(clipping_areas), box_kind

        if clipping_type == 2:   # _("Reference Object")
            if clipping_object is None:
                return None, None
            return self._copper_clear_area_from_reference_object(cleared_object, clipping_object, box_kind), box_kind

        return env_obj, box_kind

    def _copper_clear_area_for_entire_object(self, ncc_obj: Union["GerberObject", "GeometryObject"]):
        try:
            return NccModel.entire_object(ncc_obj.solid_geometry)
        except Exception as e:
            self.app.log.error("ToolNcc.calculate_bounding_box() 'itself'  --> %s" % str(e))
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object available."))
            return None

    def _copper_clear_area_from_selection_areas(
            self,
            area_constraint: Union[Polygon, MultiPolygon] | list[Polygon | MultiPolygon],
    ):
        return NccModel.selection_areas(area_constraint)

    def _copper_clear_area_from_reference_object(
            self,
            cleared_object: Union["GerberObject", "GeometryObject"],
            box_obj: Union["GerberObject", "GeometryObject"],
            box_kind: str,
    ):
        if box_kind not in ('geometry', 'gerber'):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The reference object type is not supported."))
            return None
        source_geometry = cleared_object.solid_geometry if box_kind == 'gerber' else None
        return NccModel.reference_area(source_geometry, box_obj.solid_geometry, box_kind)

    def apply_margin_to_clipping_region(
            self,
            clipping_region: Union[BaseGeometry, list[BaseGeometry]],
            box_kind: str,
            clipping_type,
            margin,
    ):
        """Apply the resolved margin to the clipping region."""
        self.app.log.debug("NCC Tool. Preparing non-copper polygons.")
        self.app.inform.emit(_("NCC Tool. Preparing non-copper polygons."))
        if clipping_region is None:
            return 'fail'
        if clipping_type == 2 and box_kind not in ('geometry', 'gerber'):
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("The reference object type is not supported."))
            return 'fail'
        try:
            result = NccModel.apply_margin(
                clipping_region, box_kind, clipping_type, margin, lambda: NccGen._check_abort(self))
        except grace:
            raise
        except Exception as err:
            self.app.log.error("ToolNcc.apply_margin_to_bounding_box() --> %s" % str(err))
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("No object available."))
            return 'fail'
        self.app.log.debug("NCC Tool. Finished non-copper polygons.")
        return result

    def compute_area_to_clear(
            self,
            name: str,
            cleared_object: Union["GerberObject", "GeometryObject"],
            geo_obj,
            iso_tooldia,
            has_offset,
            offset,
            margin,
            clipping_region,
            tools_storage,
            clipping_geometry=None,
    ):
        """Legacy area seam. Scheduled jobs pass a plain dictionary for isolation output."""
        self.app.inform.emit(_("NCC Tool. Calculate 'empty' area."))
        if clipping_geometry is not None:
            geometry = clipping_geometry
            isolation = []
            milling_type = None
        elif cleared_object.kind == 'gerber':
            buffering_off = not iso_tooldia and self.app.options.get(
                'gerber_buffering', self.app.defaults.get(
                    'gerber_buffering', self.app.defaults.factory_defaults.get('gerber_buffering'))) == 'no'
            geometry = ncc_gerber_copper(cleared_object, 1e-9 if buffering_off and not iso_tooldia else None)
            isolation = iso_tooldia or []
            milling_type = (geo_obj['milling_type'] if isinstance(geo_obj, dict)
                            else self.ui.milling_type_radio.get_value()) if isolation else None
        elif cleared_object.kind == 'geometry':
            geometry = unary_union(cleared_object.solid_geometry)
            isolation = []
            milling_type = None
        else:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _('The selected object is not suitable for copper clearing.'))
            return 'fail', 0
        # Resolve isolation settings in the caller before scheduling; direct legacy calls still read the UI.
        if isinstance(geo_obj, dict) and 'milling_type' in geo_obj:
            milling_type = geo_obj['milling_type']
        if isolation:
            self.solid_geometry = geometry
        area, generated, warning, messages = NccModel.prepare_area(
            geometry, clipping_region, isolation, tools_storage, name, self.decimals,
            has_offset, offset, margin, milling_type, lambda *args: self.generate_envelope(*args),
            self._compute_area_to_clear_handler, lambda: NccGen._process_events_and_check_abort(self))
        for message in messages:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(message))
        if area == 'fail':
            self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                'Could not get the extent of the area to be non copper cleared.'))
            return 'fail', 0
        if isinstance(geo_obj, dict):
            geo_obj['tools'].update(generated)
        else:
            geo_obj.tools.update(generated)
            tools_storage.update(deepcopy(generated))
        self.app.inform.emit(_("NCC Tool. Finished calculation of 'empty' area."))
        return area, warning

    def clear_polygon_worker(self, pol, tooldia, ncc_method, ncc_overlap, ncc_connect, ncc_contour, prog_plot,
                             simplify_tol=0.0):

        # Resolve engines lazily: unbound callers may supply only the selected engine.
        paths, messages = NccModel.clear_polygon(
            pol, tooldia, ncc_method, ncc_overlap, ncc_connect, ncc_contour, prog_plot, self.circle_steps,
            lambda *args, **kwargs: self.parent_tool.clear_polygon_shrink(*args, **kwargs),
            lambda *args, **kwargs: self.parent_tool.clear_polygon_seed(*args, **kwargs),
            lambda *args, **kwargs: self.parent_tool.clear_polygon_lines(*args, **kwargs), simplify_tol)
        for message in messages:
            self.app.inform.emit(_(message))
        if paths is None:
            pt = pol.representative_point()
            coords = (pt.x, pt.y)
            self.app.inform_shell.emit('%s %s' % (_('Polygon could not be cleared. Location:'), str(coords)))
        return paths

    def _cleanup_result(self, tools, generated, domains, name, settings=None, source=None):
        if not any(tools[uid]['data'].get('tools_ncc_final_cleanup', False) for uid in domains):
            return generated, None
        copper = ncc_gerber_copper(source) if source is not None and source.kind == 'gerber' else None
        return NccModel.finish_cleanup(
            tools, generated, domains, name, self.circle_steps,
            lambda domain, dia, steps, previous, generate: residual_cleanup(
                self.app, domain, dia, steps, previous, generate),
            self.clear_polygon_worker, lambda: NccGen._process_events_and_check_abort(self), settings, copper)

    def final_cleanup(self, output, tools_storage, domains, name, settings=None, source=None):
        """Compatibility adapter for callers that already own an output object."""
        tools, residual = NccGen._cleanup_result(self, tools_storage, output.tools, domains, name, settings, source)
        if residual is None:
            return
        output.tools = tools
        for uid, value in tools.items():
            tools_storage[uid] = value
            if 'ncc_cleanup_start' in value:
                tools_storage[uid] = tools_storage.pop(uid)
        output.ncc_cleanup_residual = residual
        self.app.poly_not_cleared = not residual.is_empty
        if not residual.is_empty:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                'Final cleanup finished. Some residual copper could not be cleared with this tool.'))

    def clear_ncc_area_selection_option(self, areas_to_clear_list: list[Polygon | MultiPolygon]):
        self.app.log.info("NCCGen.clear_ncc_area_selection_option() --> Clearing the designated areas(s).")

        areas_to_clear_list = unary_union(areas_to_clear_list)
        if isinstance(areas_to_clear_list, MultiPolygon):
            areas_to_clear_list = list(areas_to_clear_list.geoms)
        elif isinstance(areas_to_clear_list, Polygon):
            areas_to_clear_list = [areas_to_clear_list]

        self.ncc_handler(
            cleared_object=self.ncc_obj,
            clear_tooldia_list=self.ncc_dia_list,
            iso_tooldia_list=self.iso_dia_list,
            areas_to_clear=areas_to_clear_list,
            sel_obj=self.bound_obj,
            outname=self.o_name,
        )

    def _publish_result(self, output, tools, storage, name, last_tool, failed, residual, warning, cutz=None,
                        rest=False):
        """Publish only after generation and cleanup both succeeded."""
        NccGen._check_abort(self)
        if not tools or not any(value.get('solid_geometry') for value in tools.values()):
            self.app.poly_not_cleared = False
            self.app.inform.emit('[ERROR] %s' % _(
                'There is no NCC Geometry in the file.\n'
                'Usually it means that the tool diameter is too big for the painted geometry.\n'
                'Change the painting parameters and try again.'))
            return 'fail'
        if cutz is not None:
            for value in tools.values():
                value['data']['tools_mill_cutz'] = cutz
        output.tools = tools
        output.solid_geometry = [path for value in tools.values()
                                 for path in flatten_shapely_geometry(value['solid_geometry'])]
        output.multigeo = True
        output.obj_options['tools_mill_tooldia'] = str(last_tool)
        if residual is not None:
            output.ncc_cleanup_residual = residual
            failed = not residual.is_empty
            if failed:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                    'Final cleanup finished. Some residual copper could not be cleared with this tool.'))
        self.app.poly_not_cleared = failed
        if rest:
            # Rest machining never rewrote the tool table, except for the final cleanup tool.
            storage.update(deepcopy({uid: value for uid, value in tools.items() if 'ncc_cleanup_start' in value}))
        else:
            storage.clear()
            storage.update(deepcopy(tools))
        if warning:
            self.app.inform.emit('[WARNING] %s: %s %s.' % (
                _("NCC Tool clear all done but the copper features isolation is broken for"),
                str(warning), _("tools")))
        else:
            self.app.inform.emit('[success] %s' % _("NCC Tool clear all done."))

    def _tool_progress(self, diameter, units):
        self.app.log.debug("Starting geometry processing for tool: %s" % str(diameter))
        self.app.inform.emit('[success] %s = %s%s %s' % (
            _('NCC Tool clearing with tool diameter'), str(diameter), units.lower(), _('started.')))

    def ncc_handler(
            self,
            cleared_object: Union["GerberObject", "GeometryObject"],
            clear_tooldia_list: list[int | float | str],
            iso_tooldia_list: list[int | float | str],
            areas_to_clear: list[Polygon | MultiPolygon] = None,
            sel_obj: Union["GerberObject", "GeometryObject"] = None,
            outname: str = None,
            tool_ordering: int = None,
            tools_storage: dict = None,
            run_threaded: bool = True,
    ):
        """Resolve GUI input, run explicit-data generation, then publish through the tool factory."""
        # Keep circle accuracy and isolation staging local to this request, not the next GUI job.
        self = copy(self)
        self.app.log.debug("Executing the ncc_handler() ...")
        tolerance = float(self.app.options.get(
            'global_tolerance', self.app.defaults.get('global_tolerance', 0.005)))
        if self.app.units.upper() == 'IN':
            tolerance /= 25.4
        rest = self.ui.rest_cb.get_value()
        order = tool_ordering if tool_ordering is not None else self.ui.order_combo.get_value()
        clipping_type = self.ui.select_method_combo.get_value()
        margin = self.ui.rest_margin_entry.get_value() if rest else self.ui.margin_entry.get_value()
        connect = self.ui.rest_connect_cb.get_value() if rest else False
        contour = self.ui.rest_contour_cb.get_value() if rest else True
        has_offset = self.ui.rest_offset_choice_cb.get_value() if rest else False
        offset = self.ui.rest_offset_entry.get_value() if rest else 0.0
        milling_type = self.ui.milling_type_radio.get_value() if iso_tooldia_list else None
        prog_plot = self.app.options.get('tools_ncc_plotting', self.app.defaults.get(
            'tools_ncc_plotting', self.app.defaults.factory_defaults.get('tools_ncc_plotting'))) == 'progressive'
        cutz = self.app.options.get('tools_ncc_cutz', self.app.defaults.get(
            'tools_ncc_cutz', self.app.defaults.factory_defaults.get('tools_ncc_cutz')))
        units = self.app.units
        storage = tools_storage if tools_storage is not None else self.ncc_tools
        snapshot = deepcopy(storage)
        tool_settings = deepcopy(self.ncc_tools)
        diameters = list(clear_tooldia_list)
        if not diameters:
            self.app.inform.emit('[ERROR_NOTCL] %s' % _("Failed."))
            return 'fail'
        if rest or order == 2:
            diameters.sort(reverse=True)
        elif order == 1:
            diameters.sort()
        for value in snapshot.values():
            if value['tooldia'] in diameters:
                value.pop('ncc_cleanup_start', None)
        name = outname if outname is not None else self.obj_name + '_ncc'
        if run_threaded:
            proc = self.app.proc_container.new('%s...' % _("Working"))
        else:
            self.app.proc_container.view.set_busy('%s...' % _("Working"))
            QtWidgets.QApplication.processEvents()

        def generate(output, app_obj):
            NccGen._process_events_and_check_abort(self)
            region, kind = self.compute_clipping_region(
                cleared_object=cleared_object, clipping_object=sel_obj,
                clipping_type=clipping_type, clipping_areas=areas_to_clear)
            if region is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("NCC Tool failed creating bounding box."))
                return 'fail'
            boundary = self.apply_margin_to_clipping_region(
                clipping_region=region, box_kind=kind, clipping_type=clipping_type, margin=margin)
            if boundary is None or boundary == 'fail':
                return 'fail'
            # This is plain staging data, never the registered output object.
            staged = {'tools': {}, 'milling_type': milling_type}
            prepared = {}
            areas = {}
            warning = 0
            for diameter in diameters:
                NccGen._process_events_and_check_abort(self)
                uid = NccModel.tool_uid(tool_settings, diameter, self.decimals)
                if uid is None:
                    continue
                data = tool_settings[uid]['data']
                use_offset = has_offset if rest else data['tools_ncc_offset_choice']
                distance = offset if rest else float(data['tools_ncc_offset_value'])
                key = (use_offset is True, distance if use_offset is True else 0.0)
                if key not in prepared:
                    prepared[key] = self.compute_area_to_clear(
                        name=name, cleared_object=cleared_object, geo_obj=staged,
                        iso_tooldia=iso_tooldia_list, has_offset=use_offset, offset=distance,
                        margin=margin, clipping_region=boundary, tools_storage=snapshot)
                areas[uid], warning = prepared[key]
                if rest and areas[uid] == 'fail':
                    return 'fail'
            generated, domains, residual, failed, last = NccModel.generate_tools(
                'gui_rest' if rest else 'gui_normal', tool_settings, snapshot, diameters, areas,
                name, self.decimals, self.circle_steps, self.clear_polygon_worker,
                lambda: NccGen._process_events_and_check_abort(self),
                self.app.proc_container.update_view_text, connect=connect, contour=contour,
                simplify_tol=tolerance, prog_plot=prog_plot, initial_tools=staged['tools'],
                tool_progress=lambda diameter: self._tool_progress(diameter, units))
            if not rest:
                self._warn_unused_tools(tool_settings, diameters, generated)
            generated, cleanup_residual = self._cleanup_result(
                snapshot, generated, domains, name,
                dict(tools_ncc_connect=connect, tools_ncc_contour=contour) if rest else None,
                cleared_object)
            if prog_plot:
                self.temp_shapes.clear(update=True)
            return self._publish_result(output, generated, storage, name, '0.0' if rest else last,
                                        failed, cleanup_residual, warning, cutz, rest)

        def job_thread(app_instance):
            try:
                result = self.parent_tool.new_object(
                    'geometry', name, generate, source=cleared_object, autoselected=False)
                if result == 'fail' or result is False:
                    return 'fail'
            except grace:
                app_instance.log.debug("NccGen.ncc_handler.job_thread() -> Graceful exit.")
                return 'fail'
            except Exception as err:
                app_instance.log.debug("NccGen.ncc_handler.job_thread() -> Exception: %s" % str(err))
                self.app.inform.emit('[ERROR] %s' % _("Failed."))
                return 'fail'
            finally:
                if prog_plot:
                    self.temp_shapes.clear(update=True)
                if run_threaded:
                    proc.done()
                else:
                    app_instance.proc_container.view.set_idle()
            self.app.inform.emit('[success] %s' % _("Done."))

        if run_threaded:
            self.app.collection.promise(name)
            self.app.worker_task.emit({'fcn': job_thread, 'params': [self.app]})
        else:
            return job_thread(self.app)

    def clear_copper_tcl(
            self,
            ncc_obj,
            sel_obj=None,
            areas_to_clear_list=None,
            ncc_tooldia=None,
            iso_tooldia=None,
            margin=None,
            has_offset=None,
            offset=None,
            select_method=None,
            outname=None,
            overlap=None,
            connect=None,
            contour=None,
            order=None,
            method=None,
            rest=None,
            tools_storage=None,
            plot=True,
            run_threaded=False,
    ):
        """Tcl adapter. Synchronous calls finish object creation before returning."""
        self = copy(self)
        storage = tools_storage if tools_storage is not None else self.ncc_tools
        snapshot = deepcopy(storage)
        try:
            diameters = [float(safe_eval(dia)) for dia in ncc_tooldia.split(',') if dia != '']
        except AttributeError:
            diameters = list(ncc_tooldia) if isinstance(ncc_tooldia, list) else [float(ncc_tooldia)]
        if not diameters:
            return 'fail'
        if rest or order == 2:
            diameters.sort(reverse=True)
        elif order == 1:
            diameters.sort()
        for value in snapshot.values():
            if value['tooldia'] in diameters:
                value.pop('ncc_cleanup_start', None)
        reference = ncc_obj if sel_obj is None or sel_obj == 0 else sel_obj
        if select_method == 0:
            region = NccModel.entire_object(flatten_shapely_geometry(reference.solid_geometry))
            boundary = NccModel.apply_margin(region, None, 0, margin)
        elif select_method == 1:
            if areas_to_clear_list is None:
                return 'fail'
            boundary = NccModel.apply_margin(
                NccModel.selection_areas(areas_to_clear_list), None, 1, margin,
                lambda: NccGen._process_events_and_check_abort(self))
        elif select_method == 2 and reference.kind in ('geometry', 'gerber'):
            # Tcl's Gerber reference historically uses the reference hull, not the source hull intersection.
            region = NccModel.reference_area(reference.solid_geometry, reference.solid_geometry, reference.kind)
            boundary = NccModel.apply_margin(
                region, reference.kind, 2, margin, lambda: NccGen._process_events_and_check_abort(self))
        else:
            return 'fail'
        name = outname if outname is not None else self.obj_name + ('_ncc_rm' if rest else '_ncc')
        milling_type = self.app.options.get('tools_ncc_milling_type', self.app.defaults.get(
            'tools_ncc_milling_type', self.app.defaults.factory_defaults.get('tools_ncc_milling_type'))
        ) if iso_tooldia else None
        units = self.app.app_units
        if run_threaded:
            proc = self.app.proc_container.new('%s...' % _("Working"))
        else:
            self.app.proc_container.view.set_busy('%s...' % _("Working"))
            QtWidgets.QApplication.processEvents()

        def clear_paths(pol, tooldia, ncc_method, ncc_overlap, ncc_connect, ncc_contour, **kwargs):
            if ncc_method == 0:
                engine = self.parent_tool.clear_polygon_shrink
            elif ncc_method == 1:
                engine = self.parent_tool.clear_polygon_seed
            else:
                engine = self.parent_tool.clear_polygon_lines
            result = engine(pol, tooldia, self.circle_steps, overlap=ncc_overlap,
                            contour=ncc_contour, connect=ncc_connect, prog_plot=False)
            return list(result.get_objects()) if result else None

        def generate(output, app_obj):
            assert output.kind == 'geometry', "Initializer expected a GeometryObject, got %s" % type(output)
            NccGen._process_events_and_check_abort(self)
            if ncc_obj.kind == 'gerber':
                geometry = ncc_gerber_copper(ncc_obj)
                isolation = iso_tooldia or []
            elif ncc_obj.kind == 'geometry':
                geometry = unary_union(ncc_obj.solid_geometry)
                isolation = []
            else:
                return 'fail'
            if isolation:
                self.solid_geometry = geometry
            area, initial, warning, messages = NccModel.prepare_area(
                geometry, boundary, isolation, snapshot, name, self.decimals,
                has_offset, offset if has_offset is True else 0.0, margin, milling_type,
                self.generate_envelope, self._compute_area_to_clear_handler,
                lambda: NccGen._process_events_and_check_abort(self))
            for message in messages:
                self.app.inform.emit('[WARNING_NOTCL] %s' % _(message))
            if area == 'fail':
                self.app.inform.emit('[ERROR_NOTCL] %s' % _(
                    'Could not get the extent of the area to be non copper cleared.'))
                return 'fail'
            areas = {uid: area for uid, value in snapshot.items() if value['tooldia'] in diameters}
            generated, domains, residual, failed, last = NccModel.generate_tools(
                'tcl_rest' if rest else 'tcl_normal', snapshot, snapshot, diameters, areas,
                name, self.decimals, self.circle_steps, clear_paths,
                lambda: NccGen._process_events_and_check_abort(self), self.app.proc_container.update_view_text,
                connect=connect, contour=contour, overlap=overlap, method=method, initial_tools=initial,
                tool_progress=lambda diameter: self._tool_progress(diameter, units))
            if not rest:
                self._warn_unused_tools(snapshot, diameters, generated)
            generated, cleanup_residual = self._cleanup_result(
                snapshot, generated, domains, name,
                dict(tools_ncc_method=method, tools_ncc_overlap=overlap * 100 if overlap is not None else 40,
                     tools_ncc_connect=connect, tools_ncc_contour=contour), ncc_obj)
            return self._publish_result(output, generated, storage, name, last,
                                        failed, cleanup_residual, warning, rest=bool(rest))

        def job_thread(app_obj):
            try:
                result = app_obj.app_obj.new_object('geometry', name, generate, plot=plot)
                if result == 'fail' or result is False:
                    return 'fail'
            except grace:
                return 'fail'
            except Exception as err:
                self.app.log.error("NccGen.clear_copper_tcl() --> %s" % str(err))
                traceback.print_stack()
                return 'fail'
            finally:
                if run_threaded:
                    proc.done()
                else:
                    app_obj.proc_container.view.set_idle()

        if run_threaded:
            self.app.collection.promise(name)
            self.app.worker_task.emit({'fcn': job_thread, 'params': [self.app]})
        else:
            return job_thread(self.app)

    def _warn_unused_tools(self, tool_settings, diameters, generated):
        for diameter in diameters:
            uid = NccModel.tool_uid(tool_settings, diameter, self.decimals)
            if uid is not None and uid not in generated:
                self.app.inform.emit('[WARNING_NOTCL] %s %s: %s %s: %s' % (
                    _("Could not use the tool for copper clear."), _("Tool"), str(uid),
                    _("with diameter"), str(tool_settings[uid]['tooldia'])))

    def _compute_area_to_clear_handler(self, target, boundary=None):
        """Return the complement of target inside boundary, retaining the public Tcl seam."""
        ret_val = NccModel.complement(
            target, boundary, lambda: NccGen._process_events_and_check_abort(self),
            lambda text: self.app.proc_container.update_view_text(text))
        if ret_val == 'fail':
            self.app.inform.emit('[ERROR_NOTCL] %s' %
                                 _("Try to use the Buffering Type = Full in Preferences -> Gerber General. "
                                   "Reload the Gerber file after this change."))
        return ret_val

    def _check_abort(self):
        if self.app.abort_flag:
            raise grace

    def _process_events_and_check_abort(self):
        QtWidgets.QApplication.processEvents()
        NccGen._check_abort(self)

    @staticmethod
    def poly2rings(poly):
        return NccModel.poly2rings(poly)

    def generate_envelope(
            self,
            offset,
            invert,
            envelope_iso_type=2,
    ):
        return NccModel.generate_envelope(
            self.solid_geometry, offset, invert, envelope_iso_type,
            lambda *args, **kwargs: self.parent_tool.isolation_geometry(*args, **kwargs))
