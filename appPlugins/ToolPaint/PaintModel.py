"""Explicit-data Paint geometry kernels. Application objects stay in the legacy facade."""

import logging
from copy import deepcopy

from shapely import LineString, LinearRing, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry import base
from shapely.ops import linemerge, unary_union

from camlib import AppRTreeStorage, flatten_shapely_geometry, grace

log = logging.getLogger('base')


def generate_paint(geometry, tools_storage, diameters, ordering, simplification, decimals,
                   process_polygon, check_abort=None, progress=None, tool_started=None,
                   find_uid=None, get_params=None, buffer=None, simplify=None):
    """Generate independent tool passes without publishing or changing caller-owned tools."""
    tools = deepcopy(tools_storage)
    for tool in tools.values():
        tool.pop('paint_cleanup_start', None)
        tool['solid_geometry'] = []
    diameters = list(diameters)
    if ordering in (1, 2):
        diameters.sort(reverse=ordering == 2)
    find_uid = find_uid or (lambda dia, storage: find_tool_uid(dia, storage, decimals))
    get_params = get_params or tool_params
    buffer = buffer or buffer_geometry
    simplify = simplify or simplify_geometry
    warnings = []
    old_progress = 0
    last_diameter = None
    for diameter in diameters:
        last_diameter = diameter
        if check_abort is not None:
            check_abort()
        if tool_started is not None:
            tool_started(diameter)
        uid = find_uid(diameter, tools)
        if not uid:
            return 'fail'
        settings = get_params(uid, tools)
        polygons = buffer(geometry, settings['offset'])
        if not polygons:
            warnings.append(('empty', None))
            continue
        try:
            cleared = []
            for number, polygon in enumerate(polygons, 1):
                if check_abort is not None:
                    check_abort()
                result = process_polygon(polygon, diameter, settings)
                if result == 'fail':
                    # One polygon that cannot be painted must not discard the whole job.
                    warnings.append(('skipped', diameter))
                    result = None
                if result:
                    cleared.extend(simplify(result.get_objects(), simplification))
                if progress is not None:
                    old_progress = progress(number, len(polygons), old_progress)
        except grace:
            raise
        except Exception as err:
            warnings.append(('normal', str(err)))
            continue
        tools[uid]['solid_geometry'] = [path for path in cleared if path and not path.is_empty]
    if check_abort is not None:
        check_abort()
    return {'tools': tools, 'paths': [path for tool in tools.values() for path in tool['solid_geometry']],
            'warnings': warnings, 'last_diameter': last_diameter}


def generate_rest_paint(geometry, tools_storage, diameters, ordering, simplification, decimals,
                        process_polygon, check_abort=None, progress=None, tool_started=None,
                        rest_offset=0, find_uid=None, get_params=None, buffer=None, simplify=None):
    """Rest passes retain both local and global intermediate stock subtractions."""
    tools = deepcopy(tools_storage)
    for tool in tools.values():
        tool.pop('paint_cleanup_start', None)
        tool['solid_geometry'] = []
    diameters = sorted(diameters, reverse=True)
    find_uid = find_uid or (lambda dia, storage: find_tool_uid(dia, storage, decimals))
    get_params = get_params or tool_params
    simplify = simplify or simplify_geometry
    if check_abort is not None:
        check_abort()
    polygons = flatten_shapely_geometry(unary_union(buffer_geometry(geometry, rest_offset)))
    warnings = []
    output_tools = {}
    old_progress = 0
    last_diameter = None
    geo_len = len(polygons)
    if not polygons:
        return {'tools': tools, 'output_tools': output_tools, 'paths': [],
                'warnings': [('empty', None)], 'last_diameter': None}
    for tool_index, diameter in enumerate(diameters):
        last_diameter = diameter
        has_next_tool = tool_index + 1 < len(diameters)
        if check_abort is not None:
            check_abort()
        if tool_started is not None:
            tool_started(diameter)
        uid = find_uid(diameter, tools)
        if not uid:
            return 'fail'
        settings = get_params(uid, tools)
        rest_list, cleared = [], []
        number = 0
        try:
            for polygon in polygons:
                if check_abort is not None:
                    check_abort()
                left, bottom, right, top = polygon.bounds
                if right - left < diameter or top - bottom < diameter:
                    continue
                check_buff = polygon.buffer(-diameter / 2.0)
                if not check_buff or check_buff.is_empty:
                    continue
                result = process_polygon(polygon, diameter, settings)
                if result == 'fail':
                    # Not swept, so the polygon stays in the stock handed to the next tool.
                    warnings.append(('skipped', diameter))
                    continue
                elements = simplify(result.get_objects(), simplification) if result else []
                if has_next_tool:
                    swept = unary_union(elements).buffer(diameter / 2.0)
                    remaining = polygon.difference(swept)
                    if remaining:
                        rest_list.extend(part for part in flatten_shapely_geometry(remaining)
                                         if part.is_valid and not part.is_empty)
                if result:
                    cleared += elements
                number += 1
                if progress is not None:
                    old_progress = progress(number, geo_len, old_progress)
        except grace:
            raise
        except Exception as err:
            warnings.append(('rest', str(err)))
            continue
        if cleared:
            tools[uid]['solid_geometry'] = deepcopy(cleared)
            output_tools[uid] = dict(tools[uid])
        if not has_next_tool:
            break
        # Keep this separate from the per-polygon subtraction above: legacy stock
        # arithmetic intentionally combines the two results before repairing them.
        swept = unary_union(cleared).buffer(diameter / 2.0)
        polygons = flatten_shapely_geometry(MultiPolygon(polygons).difference(swept))
        remaining = [part for part in polygons if part.is_valid] + rest_list
        polygons = MultiPolygon(remaining)
        if not polygons.is_valid:
            polygons = unary_union(remaining)
        if not polygons or polygons.is_empty or not polygons.is_valid:
            break
        polygons = flatten_shapely_geometry(polygons)
    if check_abort is not None:
        check_abort()
    return {'tools': tools, 'output_tools': output_tools,
            'paths': [path for tool in output_tools.values() for path in tool['solid_geometry']],
            'warnings': warnings, 'last_diameter': last_diameter}


def final_cleanup(geometry, tools_storage, output_tools, diameters, decimals, process_polygon,
                  cleanup, rest_offset=None, check_abort=None, find_uid=None, get_params=None,
                  buffer=None):
    """Select one final tool and return physical cleanup paths and residual stock."""
    tools = deepcopy(tools_storage)
    output_tools = deepcopy(output_tools)
    find_uid = find_uid or (lambda dia, storage: find_tool_uid(dia, storage, decimals))
    get_params = get_params or tool_params
    buffer = buffer or buffer_geometry
    selected = {find_uid(diameter, tools) for diameter in diameters}
    eligible = [uid for uid, tool in tools.items() if uid in selected and float(tool['tooldia']) > 0
                and tool['data'].get('tools_paint_final_cleanup', False)]
    residual = None
    warnings = []
    if eligible:
        if check_abort is not None:
            check_abort()
        original = unary_union(flatten_shapely_geometry(geometry))
        for uid in sorted(eligible, key=lambda key: float(tools[key]['tooldia'])):
            tool = tools[uid]
            offset = float(tool['data']['tools_paint_offset']) if rest_offset is None else rest_offset
            # Negative offsets never authorize cutting outside the selection or in its holes.
            domain = original.intersection(unary_union(buffer(geometry, offset)))
            if not domain.is_empty:
                settings = get_params(uid, tools)

                def generate_paths(polygon, diameter):
                    result = process_polygon(polygon, diameter, settings)
                    if result == 'fail':
                        return 'fail'
                    return list(result.get_objects()) if result else []

                previous = [entry for entry in output_tools.values() if entry['solid_geometry']]
                paths, residual = cleanup(domain, float(tool['tooldia']), previous,
                                          generate_paths, not settings['conn'])
                if check_abort is not None:
                    check_abort()
                if paths:
                    standard = list(output_tools.get(uid, {}).get('solid_geometry', []))
                    tool['solid_geometry'] = standard + paths
                    tool['paint_cleanup_start'] = len(standard)
                    tools[uid] = tools.pop(uid)
                    output_tools.pop(uid, None)
                    output_tools[uid] = dict(tool)
                if not residual.is_empty:
                    warnings.append(('cleanup', None))
                break
    return {'tools': tools, 'output_tools': output_tools, 'residual': residual, 'warnings': warnings,
            'paths': [path for tool in output_tools.values() for path in tool['solid_geometry']]}


def find_tool_uid(tool_dia, tools_storage, decimals):
    for uid, tool in tools_storage.items():
        if float('%.*f' % (decimals, tool['tooldia'])) == float('%.*f' % (decimals, tool_dia)):
            return int(uid)
    return None


def tool_params(tool_uid, tools_storage):
    data = tools_storage[tool_uid]['data']
    return {
        'over': float(data['tools_paint_overlap']) / 100.0,
        'conn': data['tools_paint_connect'],
        'cont': data['tools_paint_contour'],
        'offset': float(data['tools_paint_offset'])
    }


def buffer_geometry(geometry, offset):
    buffered = []
    for polygon in flatten_shapely_geometry(geometry):
        result = polygon.buffer(-offset)
        if result and not result.is_empty:
            buffered.append(result)
    return buffered


def simplify_geometry(geometry, tolerance):
    if tolerance > 0.0:
        return [element.simplify(tolerance) for element in geometry]
    return list(geometry)


def selection_geometry(geometry, check_abort=None, expand_multi=False):
    """Flatten selected geometry, retaining the legacy all/area multipart distinction."""
    if check_abort is not None:
        check_abort()
    if geometry is None:
        return None
    result = []
    try:
        parts = geometry.geoms if expand_multi and isinstance(geometry, (MultiPolygon, MultiLineString)) else geometry
        for part in parts:
            if part and (isinstance(part, list) or not part.is_empty):
                result.extend(selection_geometry(part, check_abort, expand_multi))
    except TypeError:
        result.append(Polygon(geometry) if isinstance(geometry, LinearRing) else geometry)
    return result


def select_polygon(geometry, point):
    try:
        for part in geometry:
            selected = select_polygon(part, point)
            if selected is not None:
                return selected
    except TypeError:
        if isinstance(geometry, LinearRing):
            geometry = Polygon(geometry)
        try:
            if geometry.contains(Point(point)):
                return geometry
        except AttributeError:
            return None
    return None


def reference_area(geometry):
    if isinstance(geometry, MultiPolygon):
        envelope = geometry.convex_hull
    elif isinstance(geometry, list) and len(geometry) == 1 and isinstance(geometry[0], Polygon):
        envelope = unary_union(geometry)
    else:
        envelope = unary_union(geometry).convex_hull
    return envelope.buffer(distance=0.0000001, join_style=base.JOIN_STYLE.mitre)


def area_intersection(target, areas, check_abort=None):
    if isinstance(areas, list):
        areas = unary_union(areas)
    painted_area = selection_geometry(target.intersection(areas), check_abort, expand_multi=True)
    try:
        painted_area = linemerge(painted_area)
    except Exception:
        pass
    if isinstance(painted_area, (MultiPolygon, MultiLineString)):
        painted_area = painted_area.geoms
    try:
        parts = iter(painted_area)
    except TypeError:
        parts = iter([painted_area])
    polygons = []
    for part in parts:
        if part.is_empty:
            continue
        if isinstance(part, Polygon):
            polygons.append(part)
        elif isinstance(part, (LinearRing, LineString)):
            coords = list(part.coords)
            if not part.is_closed:
                coords.append(coords[0])
            polygons.append(Polygon(coords))
    return polygons


def classify_apertures(poly_g, apertures, flashes, traces):
    for aperture in apertures.values():
        for element in aperture['geometry']:
            if 'size' in aperture and aperture['size'] == 0.0:
                traces.setdefault(aperture['size'], []).append(element)
            if 'follow' in element and element['follow'].within(poly_g):
                if isinstance(element['follow'], Point):
                    if aperture['type'] in ('C', 'O', 'R'):
                        flashes.setdefault(aperture['type'], []).append(element)
                else:
                    traces.setdefault(aperture['size'], []).append(element)


def laser_lines(poly_g, tool_diameter, over, conn, cont, prog_plot, circle_steps,
                geometry_circle_steps, apertures, clear_seed, clear_lines, fill_lines):
    flashes, traces = {}, {}
    try:
        classify_apertures(poly_g, apertures, flashes, traces)
    except grace:
        return 'fail'
    except Exception as err:
        log.error('ToolPaint.paint_polygon_worker() Laser Lines -> Identify flashes/traces--> %s' % str(err))
    result = AppRTreeStorage()
    pads = []
    try:
        for aperture_type, elements in flashes.items():
            for element in elements:
                if 'solid' in element:
                    clear = clear_lines if aperture_type == 'R' else clear_seed
                    steps = circle_steps if aperture_type == 'C' else geometry_circle_steps
                    paths = clear(element['solid'], tooldia=tool_diameter, steps_per_circle=steps,
                                  overlap=over, contour=True, connect=conn, prog_plot=prog_plot)
                    pads += [path for path in paths.get_objects() if path]
    except grace:
        return 'fail'
    except Exception as err:
        log.error('ToolPaint.paint_polygon_worker() Laser Lines -> Process flashes--> %s' % str(err))
    try:
        result.insert_many([path for path in pads if path])
    except TypeError:
        result.insert(pads)
    copper = []
    try:
        for size, elements in traces.items():
            for element in elements:
                line = element['follow']
                if line and isinstance(line, (LineString, MultiLineString)):
                    paths = fill_lines(line, size, tooldia=tool_diameter,
                                       steps_per_circle=geometry_circle_steps, overlap=over,
                                       contour=cont, connect=conn, prog_plot=prog_plot)
                    copper += [path for path in paths.get_objects() if path]
    except grace:
        return 'fail'
    except Exception as err:
        log.error('ToolPaint.paint_polygon_worker() Laser Lines -> Process traces--> %s' % str(err))
    merged = linemerge(unary_union(copper))
    lines = merged.geoms if isinstance(merged, MultiLineString) else [merged]
    try:
        result.insert_many([line for line in lines if line])
    except TypeError:
        result.insert(lines)
    return result


def paint_polygon(poly_g, tool_diameter, paint_method, over, conn, cont, prog_plot, circle_steps,
                  clear_shrink, clear_seed, clear_lines, apertures=None, geometry_circle_steps=64,
                  fill_lines=None, progress=None):
    result = None
    if paint_method == 3:
        result = laser_lines(poly_g, tool_diameter, over, conn, cont, prog_plot, circle_steps,
                             geometry_circle_steps, apertures, clear_seed, clear_lines, fill_lines)
        if result == 'fail':
            return result
    else:
        methods = {0: clear_shrink, 1: clear_seed, 2: clear_lines}
        sequence = (2, 1, 0) if paint_method == 4 else (paint_method,)
        try:
            for method in sequence:
                if method not in methods:
                    break
                if paint_method == 4 and progress is not None:
                    progress(method)
                result = methods[method](poly_g, tooldia=tool_diameter, steps_per_circle=circle_steps,
                                         overlap=over, contour=cont, connect=conn, prog_plot=prog_plot)
                if result and result.objects:
                    break
        except grace:
            return 'fail'
        except Exception as err:
            name = {0: 'Standard', 1: 'Seed', 2: 'Lines', 4: 'Combo'}.get(paint_method, '')
            log.error('ToolPaint.paint_polygon_worker() %s --> %s' % (name, str(err)))
    return result if result and result.objects else None
