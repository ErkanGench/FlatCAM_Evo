"""Explicit-data geometry and tool calculations for Milling."""

from shapely import LineString, box


# Diameter tolerance for IN <-> MM rounding: a bit up to this much larger than the hole still fits.
DIA_TOLERANCE = 0.0001
# "Almost zero" ring radius used when the bit has the hole's size (6 decimals is the app resolution).
ALMOST_ZERO = 0.0000001
# Paint margins below this collapse: the bit fills the whole feature.
PAINT_MIN_MARGIN = 0.000001


def _rounded(value, decimals):
    return float('%.*f' % (decimals, float(value)))


def milling_bit_too_large(file_dia, tooldia, decimals=6):
    """True when the milling bit is larger than the feature, beyond the rounding tolerance."""
    return _rounded(tooldia, decimals) > _rounded(file_dia, decimals) + DIA_TOLERANCE


def milling_drills_too_small(tool_records, tools, tooldia, decimals=6):
    """Return the tools (keys) whose holes are smaller than the milling bit."""
    return [tool for tool in tools
            if tool_records[tool]['drills'] and milling_bit_too_large(tool_records[tool]['tooldia'], tooldia, decimals)]



def milling_drills_geometry(tool_records, tools, tooldia, steps=64, decimals=6):
    """Return per-drill milling rings in selected tool order.

    steps: circle steps of the whole circle (Shapely quad_segs = steps // 4).
    Holes smaller than the bit (beyond the IN/MM rounding tolerance) are skipped, never an empty ring;
    use milling_drills_too_small() to report them. An equal-size bit gives an almost-zero ring.
    """
    from camlib import circle_quad_segs
    quad_segs = circle_quad_segs(steps)
    geometry = []
    for tool in tools:
        if milling_bit_too_large(tool_records[tool]['tooldia'], tooldia, decimals):
            continue
        buffer_value = _rounded(tool_records[tool]['tooldia'], decimals) / 2 - _rounded(tooldia, decimals) / 2
        buffer_value = max(buffer_value, ALMOST_ZERO)
        for drill in tool_records[tool]['drills']:
            geometry.append(drill.buffer(buffer_value, quad_segs).exterior)
    return geometry


def milling_slots_geometry(tool_records, tools, tooldia, decimals, steps_per_circle, line_string=LineString):
    """Return slot milling rings with the existing unit-rounding allowance.

    steps_per_circle: circle steps of the whole circle (Shapely quad_segs = steps // 4).
    """
    from camlib import circle_quad_segs
    quad_segs = circle_quad_segs(steps_per_circle)
    geometry = []
    for tool in tools:
        if not tool_records[tool]['slots'] or milling_bit_too_large(tool_records[tool]['tooldia'], tooldia, decimals):
            continue
        toolstable_tool = _rounded(tooldia, decimals)
        file_tool = _rounded(tool_records[tool]['tooldia'], decimals)
        buffer_value = max(float(file_tool / 2) - float(toolstable_tool / 2) + DIA_TOLERANCE, ALMOST_ZERO)
        for start, stop in tool_records[tool]['slots']:
            lines_string = line_string([start, stop])
            geometry.append(lines_string.buffer(buffer_value, quad_segs).exterior)
    return geometry


def milling_offset(offset_type, tooldia, custom_offset):
    """Resolve a validated CNC offset; custom input validation stays with the caller."""
    if offset_type == 1:
        return -tooldia / 2
    if offset_type == 2:
        return tooldia / 2
    if offset_type == 3:
        return float(custom_offset)
    return 0.0


def excellon_paint_margin(tool):
    """Radius of the area to clear around each feature: hole radius plus the offset.

    A value <= PAINT_MIN_MARGIN means the milling bit is as large as or larger than the hole, so
    excellon_paint_polygons() returns [] for this tool and the caller should tell the user its tool dia.
    """
    data = tool['data']
    mill_dia = data['tools_mill_milling_dia']
    offset_type = data['tools_mill_offset_type']
    if offset_type == 0:
        offset = 0.0
    elif offset_type == 1:
        offset = -mill_dia / 2.0
    elif offset_type == 2:
        offset = mill_dia / 2.0
    else:
        offset = data['tools_mill_offset_value']
    return float(tool['tooldia']) / 2.0 + offset


def excellon_paint_polygons(tool, line_string=LineString, circle_steps=64):
    """Build each drill/slot polygon without merging overlapping features.

    circle_steps: circle steps of the whole circle (Shapely quad_segs = steps // 4).
    Returns [] when the margin collapses (see excellon_paint_margin()).
    """
    from camlib import circle_quad_segs
    quad_segs = circle_quad_segs(circle_steps)
    drills_tool_geo = []
    slots_tool_geo = []
    total_paint_geo = []
    mill_type = tool['data']['tools_mill_milling_type']
    buff_dia = excellon_paint_margin(tool)
    if buff_dia <= PAINT_MIN_MARGIN:
        return []
    if mill_type in ['drills', 'both']:
        try:
            drills_tool_geo = [d_p.buffer(buff_dia, quad_segs) for d_p in tool['drills']]
            total_paint_geo = drills_tool_geo
        except KeyError:
            total_paint_geo = []
    if mill_type in ['slots', 'both']:
        try:
            slots_tool_geo = [line_string(s_l).buffer(buff_dia, quad_segs) for s_l in tool['slots']]
            total_paint_geo = slots_tool_geo
        except KeyError:
            total_paint_geo = []
    if mill_type == 'both':
        total_paint_geo = drills_tool_geo + slots_tool_geo
    return total_paint_geo


def clear_excellon_polygon(polygon, mill_dia, overlap, connect, circle_steps, clear_polygon_seed):
    """Clear one feature using the existing geometry engine supplied by the caller."""
    return clear_polygon_seed(
        polygon, seedpoint=polygon.centroid, tooldia=mill_dia,
        overlap=overlap, steps_per_circle=circle_steps,
        connect=connect, contour=True, prog_plot=False)


def polishing_area(bounds, margin, make_box=box):
    return make_box(bounds['xmin']-margin, bounds['ymin']-margin,
                    bounds['xmax']+margin, bounds['ymax']+margin)


def polishing_geometry(bbox, tooldia, circle_steps, overlap, paint_method,
                       clear_polygon_shrink, clear_polygon_seed, clear_polygon_lines):
    """Return polishing paths, or None when the selected method can't paint the area."""
    c_poly = None
    if paint_method == 0:
        c_poly = clear_polygon_shrink(
            bbox, tooldia=tooldia, steps_per_circle=circle_steps,
            overlap=overlap, contour=True, connect=True, prog_plot=False)
    elif paint_method == 1:
        c_poly = clear_polygon_seed(
            bbox, tooldia=tooldia, steps_per_circle=circle_steps,
            overlap=overlap, contour=True, connect=True, prog_plot=False)
    elif paint_method == 2:
        c_poly = clear_polygon_lines(
            bbox, tooldia=tooldia, steps_per_circle=circle_steps,
            overlap=overlap, contour=True, connect=True, prog_plot=False)
    if not c_poly or not c_poly.objects:
        return
    return [g for g in c_poly.get_objects() if g and not g.is_empty]


def xy_pair(value):
    """(x, y) of a position given as 'x, y', '(x, y)' or a pair; None when it is none of these."""
    try:
        if isinstance(value, str):
            value = value.strip('()[] ').split(',')
        x, y = value
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def parsed_end_point(parsed):
    """The last point of the parsed G-code of a tool (the list of {'geom', 'kind'}), None when there is none."""
    try:
        x, y = parsed[-1]['geom'].coords[-1][:2]
        return x, y
    except (TypeError, IndexError, KeyError, AttributeError, ValueError):
        return None
