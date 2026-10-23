"""Explicit-data NCC geometry kernels. Application objects stay in the legacy adapter."""

import logging
from copy import deepcopy

import numpy as np
from shapely import LineString, LinearRing, MultiLineString, MultiPolygon, Polygon
from shapely.geometry import base
from shapely.ops import unary_union

from camlib import flatten_shapely_geometry, grace

log = logging.getLogger('base')


def entire_object(geometry):
    single = (isinstance(geometry, MultiPolygon) and len(geometry.geoms) == 1) or (
        isinstance(geometry, list) and len(geometry) == 1 and isinstance(geometry[0], Polygon))
    if single:
        return unary_union(geometry)
    if isinstance(geometry, MultiPolygon):
        return geometry.convex_hull
    return unary_union(geometry).convex_hull


def selection_areas(geometry):
    return flatten_shapely_geometry(unary_union(geometry))


def reference_area(source_geometry, reference_geometry, reference_kind):
    if reference_kind == 'geometry':
        return flatten_shapely_geometry(reference_geometry)
    if reference_kind == 'gerber':
        return flatten_shapely_geometry(unary_union(source_geometry).convex_hull.intersection(
            unary_union(reference_geometry).convex_hull))
    return None


def apply_margin(region, reference_kind, clipping_type, margin, check_abort=None):
    if clipping_type == 0 or (clipping_type == 2 and reference_kind == 'gerber'):
        # reference_area() returns a flattened list for a Gerber reference
        return unary_union(region).buffer(distance=margin, join_style=base.JOIN_STYLE.mitre)
    if clipping_type == 1 or (clipping_type == 2 and reference_kind == 'geometry'):
        buffered = []
        for poly in region:
            if check_abort is not None:
                check_abort()
            buffered.append(poly.buffer(distance=margin, join_style=base.JOIN_STYLE.mitre))
        return unary_union(buffered)
    return None


def offset_geometry(geometry, has_offset, offset):
    if has_offset is True:
        if isinstance(geometry, list):
            geometry = MultiPolygon(geometry)
        return geometry.buffer(distance=offset)
    return geometry


def complement(target, boundary=None, check_abort=None, progress=None):
    if isinstance(target, list):
        target = MultiPolygon(target)
    if isinstance(target, (LineString, LinearRing, Polygon)):
        geo_len = 1
    elif isinstance(target, (MultiPolygon, MultiLineString)):
        geo_len = len(target.geoms)
    else:
        geo_len = len(target)
    if boundary is None or boundary.is_empty:
        boundary = target.envelope
    try:
        return boundary.difference(target)
    except Exception as err:
        log.error("NCCGen.get_ncc_empty_area() --> %s" % str(err))
        try:
            old_disp_number = 0
            target_geoms = target.geoms if isinstance(target, MultiPolygon) else target
            for pol_nr, element in enumerate(target_geoms, 1):
                if check_abort is not None:
                    check_abort()
                boundary = boundary.difference(element)
                disp_number = int(np.interp(pol_nr, [0, geo_len], [0, 100]))
                if old_disp_number < disp_number <= 100:
                    if progress is not None:
                        progress(' %d%%' % disp_number)
                    old_disp_number = disp_number
            return boundary
        except Exception as err:
            log.error("NCCGen.get_ncc_empty_area() --> %s" % str(err))
            return 'fail'


def poly2rings(poly):
    return [poly.exterior] + [interior for interior in poly.interiors]


def clip_isolation(geometry, boundary, check_abort=None):
    paths = []
    for element in flatten_shapely_geometry(geometry):
        if check_abort is not None:
            check_abort()
        rings = poly2rings(element) if isinstance(element, Polygon) else (
            [element] if isinstance(element, LineString) else [])
        for ring in rings:
            clipped = ring.intersection(boundary)
            if clipped and not clipped.is_empty:
                paths.append(clipped)
    return paths, int(any(type(path) == MultiLineString for path in paths))


def generate_envelope(geometry, offset, invert, envelope_iso_type, isolation_geometry):
    try:
        geom = unary_union(isolation_geometry(offset, geometry=geometry, iso_type=envelope_iso_type))
    except Exception as err:
        log.error('ToolNcc.generate_envelope() --> %s' % str(err))
        return 'fail'
    if invert:
        try:
            polygons = []
            for poly in flatten_shapely_geometry(geom):
                if isinstance(poly, Polygon):
                    polygons.append(Polygon(poly.exterior.coords[::-1], poly.interiors))
                elif isinstance(poly, LinearRing):
                    polygons.append(Polygon(poly.coords[::-1]))
            geom = MultiPolygon(polygons)
        except TypeError:
            if isinstance(geom, Polygon) and geom is not None:
                geom = Polygon(geom.exterior.coords[::-1], geom.interiors)
            elif isinstance(geom, LinearRing) and geom is not None:
                geom = Polygon(geom.coords[::-1])
            else:
                log.debug(f"ToolNcc.generate_envelope() Error --> Unexpected Geometry {type(geom)}")
        except Exception as err:
            log.error(f"ToolNcc.generate_envelope() Error --> {str(err)}")
            return 'fail'
    return geom


def clear_polygon(pol, tooldia, method, overlap, connect, contour, prog_plot, circle_steps,
                  shrink, seed, lines, simplify_tol=0.0):
    """Return paths plus status messages; only Geometry engine callbacks enter this kernel."""
    cp = None
    messages = []
    methods = {0: shrink, 1: seed, 2: lines}
    try:
        if method in methods:
            cp = methods[method](pol, tooldia, steps_per_circle=circle_steps, overlap=overlap,
                                 contour=contour, connect=connect, prog_plot=prog_plot)
        elif method == 3:
            for engine, message in (
                    (lines, 'Clearing the polygon with the method: lines.'),
                    (seed, 'Failed. Clearing the polygon with the method: seed.'),
                    (shrink, 'Failed. Clearing the polygon with the method: standard.')):
                messages.append(message)
                cp = engine(pol, tooldia, steps_per_circle=circle_steps, overlap=overlap,
                            contour=contour, connect=connect, prog_plot=prog_plot)
                if cp and cp.objects:
                    break
    except grace:
        return 'fail', messages
    except Exception as err:
        label = {0: 'Standard', 1: 'Seed', 2: 'Lines', 3: 'Combo'}.get(method, '')
        log.error("ToolNcc.clear_polygon_worker() %s --> %s" % (label, str(err)))
    if cp and cp.objects:
        paths = []
        for path in cp.get_objects():
            simplified = path.simplify(simplify_tol) if simplify_tol > 0.0 else path
            # A simplified chord must not let the cutter cross copper.
            if simplify_tol > 0.0 and not pol.covers(simplified.buffer(tooldia / 2)):
                simplified = path
            paths.append(simplified)
        return paths, messages
    return None, messages


def cleanup_domain(geometry, copper=None):
    domain = unary_union(flatten_shapely_geometry(geometry))
    return domain.difference(copper) if copper is not None else domain


def tool_uid(tools, diameter, decimals):
    return next((int(uid) for uid, tool in tools.items()
                 if round(float(tool['tooldia']), decimals) == round(float(diameter), decimals)), None)


def prepare_area(geometry, boundary, iso_diameters, tools, name, decimals, has_offset, offset,
                 margin, milling_type, envelope, area_complement, check_abort):
    """Prepare stock and isolation tool data without publishing into an output object."""
    generated = {}
    warnings = []
    broken = 0
    isolated = geometry
    for diameter in iso_diameters:
        check_abort()
        isolated = envelope(diameter / 2, int(milling_type == 'cl'))
        if isolated == 'fail' or isolated.is_empty:
            warnings.append('Isolation geometry could not be generated.')
            continue
        if margin < diameter:
            warnings.append('Isolation geometry is broken. Margin is less than isolation tool diameter.')
        paths, count = clip_isolation(isolated, boundary, check_abort)
        broken += count
        uid = tool_uid(tools, diameter, decimals)
        if uid is not None:
            generated[uid] = deepcopy(tools[uid])
            generated[uid]['solid_geometry'] = flatten_shapely_geometry(paths)
            generated[uid]['data']['name'] = name
    if isolated == 'fail':
        return 'fail', generated, broken, warnings
    target = offset_geometry(unary_union(isolated), has_offset, offset)
    area = area_complement(target=target, boundary=boundary)
    check_abort()
    if area == 'fail' or area.is_empty:
        return 'fail', generated, broken, warnings
    if isinstance(area, Polygon):
        area = MultiPolygon([area])
    return area, generated, broken, warnings


def generate_tools(mode, tool_settings, tools_storage, diameters, areas, name, decimals, circle_steps,
                   clear_paths, check_abort, progress, connect=False, contour=True, overlap=0.4,
                   method=0, simplify_tol=0.0, prog_plot=False, initial_tools=None, tool_progress=None):
    """Generate the four legacy NCC variants from resolved data.

    GUI normal tools each clear their complete domain. Tcl normal retains its
    historical remaining-tool inset and morphological cleared-area estimate.
    Rest modes subtract actual cutter sweeps (Tcl uses its historical epsilon).
    """
    storage = deepcopy(tools_storage)
    generated = deepcopy(initial_tools or {})
    domains = {}
    rest = mode.endswith('rest')
    tcl = mode.startswith('tcl')
    ordered = sorted(diameters, reverse=True) if rest else list(diameters)
    residual = None
    cleared = MultiPolygon()
    # Only tools that exist in the table take part in the remaining-tool inset.
    offset_a = sum(dia for dia in ordered if tool_uid(tool_settings, dia, decimals) is not None)
    failed = rest
    last = None
    for index, diameter in enumerate(ordered):
        check_abort()
        last = diameter
        if tool_progress is not None:
            tool_progress(diameter)
        progress(' %d%%' % 0)
        uid = tool_uid(tool_settings, diameter, decimals)
        if uid is None:
            continue
        domain = areas.get(uid, 'fail')
        if domain == 'fail' or domain is None:
            continue
        domains[uid] = domain
        if rest:
            if residual is None:
                residual = domain.buffer(0) if tcl else domain
            area = residual
        elif tcl:
            offset_a -= diameter - 1e-12
            try:
                area = domain.buffer(-offset_a).difference(cleared)
            except Exception as err:
                log.error('NCC normal area difference failed: %s' % str(err))
                continue
        else:
            area = domain
        data = tool_settings[uid]['data']
        tool_overlap = overlap if tcl else float(data['tools_ncc_overlap']) / 100
        tool_method = method if tcl else data['tools_ncc_method']
        tool_connect = connect if tcl or rest else data['tools_ncc_connect']
        tool_contour = contour if tcl or rest else data['tools_ncc_contour']
        used_diameter = diameter - 1e-12 if mode == 'tcl_rest' else diameter
        polygons = flatten_shapely_geometry(area)
        paths = []
        for number, polygon in enumerate(polygons, 1):
            check_abort()
            if polygon is None or polygon.is_empty or (mode == 'gui_rest' and not polygon.is_valid):
                continue
            if mode == 'gui_rest' and polygon.buffer(-diameter / 2, circle_steps).is_empty:
                continue
            parts = flatten_shapely_geometry(polygon.buffer(0)) if mode != 'gui_rest' else [polygon]
            for pol in parts:
                check_abort()
                if not isinstance(pol, Polygon) or not pol.is_valid or pol.is_empty:
                    continue
                try:
                    result = clear_paths(
                        pol=pol, tooldia=used_diameter, ncc_method=tool_method,
                        ncc_overlap=tool_overlap, ncc_connect=tool_connect, ncc_contour=tool_contour,
                        simplify_tol=simplify_tol if not tcl else 0.0,
                        prog_plot=prog_plot if not tcl else False)
                except grace:
                    raise
                except Exception as err:
                    if mode != 'tcl_rest':
                        raise
                    log.error("Polygon can't be cleared. %s" % str(err))
                    result = None
                check_abort()
                if result == 'fail':
                    raise grace
                if result is not None:
                    paths.extend(result)
                else:
                    failed = True
            progress(' %d%%' % int(number * 100 / len(polygons)))
        check_abort()
        if paths:
            target_uid = tool_uid(storage, diameter, decimals) if mode == 'gui_normal' or tcl else uid
            if target_uid is not None:
                value = storage[target_uid]
                value['solid_geometry'] = flatten_shapely_geometry(paths)
                value.pop('ncc_cleanup_start', None)
                if tcl:
                    value['data']['name'] = name
                else:
                    value['data']['output_object_name'] = name + '_' + str(diameter) if rest else name
                generated[target_uid] = deepcopy(value)
            if rest:
                swept = unary_union([path.buffer(used_diameter / 2) for path in paths])
                residual = area.difference(swept)
                residual = MultiPolygon([pol for pol in flatten_shapely_geometry(residual)
                                         if isinstance(pol, Polygon) and pol.is_valid and not pol.is_empty])
            elif tcl:
                cleared = domain.buffer(-offset_a * (1 + overlap)).buffer(-diameter / 1.999999).buffer(
                    diameter / 1.999999).buffer(0)
        if mode == 'gui_rest' and residual is not None and residual.is_empty:
            # Cleanup still needs the original domain of every selected tool.
            for pending in ordered[index + 1:]:
                pending_uid = tool_uid(tool_settings, pending, decimals)
                if pending_uid is not None and pending_uid in areas:
                    domains[pending_uid] = areas[pending_uid]
            break
    check_abort()
    # Normal generation historically retains non-empty unselected stored tools.
    if not rest:
        for uid, value in generated.items():
            storage[uid] = value
        generated = {uid: value for uid, value in storage.items() if value.get('solid_geometry')}
    return generated, domains, residual, failed, last


def finish_cleanup(tools_storage, generated, domains, name, circle_steps, cleanup_paths, clear_paths,
                   check_abort, settings=None, copper=None):
    """Select the final tool and return safe cleanup geometry, metadata and residuals."""
    tools = deepcopy(generated)
    eligible = [uid for uid in domains if tools_storage[uid]['data'].get('tools_ncc_final_cleanup', False)]
    if not eligible:
        return tools, None
    check_abort()
    uid = min(eligible, key=lambda key: tools_storage[key]['tooldia'])
    tool = deepcopy(tools_storage[uid])
    diameter = float(tool['tooldia'])
    if diameter <= 0:
        return tools, None
    domain = cleanup_domain(domains[uid], copper)
    if domain.is_empty:
        return tools, None
    data = dict(tool['data'], **(settings or {}))

    def generate_paths(pol, dia):
        return clear_paths(
            pol=pol, tooldia=dia, ncc_method=data.get('tools_ncc_method', 0),
            ncc_overlap=float(data.get('tools_ncc_overlap', 40)) / 100,
            ncc_connect=data.get('tools_ncc_connect', False), ncc_contour=True, prog_plot=False)

    paths, residual = cleanup_paths(domain, diameter, circle_steps, tools.values(), generate_paths)
    check_abort()
    if paths:
        standard = list(tools.get(uid, {}).get('solid_geometry', []))
        tool['solid_geometry'] = standard + paths
        tool['data']['output_object_name'] = name
        tool['ncc_cleanup_start'] = len(standard)
        tools.pop(uid, None)
        tools[uid] = tool
    return tools, residual
