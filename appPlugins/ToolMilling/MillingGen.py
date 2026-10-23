"""Explicit-data geometry and tool calculations for Milling."""

from shapely import LineString, box


def milling_drills_geometry(tool_records, tools, tooldia):
    """Return per-drill milling rings in selected tool order."""
    geometry = []
    for tool in tools:
        buffer_value = tool_records[tool]['tooldia'] / 2 - tooldia / 2
        for drill in tool_records[tool]['drills']:
            # Equal diameters retain the historical almost-zero milling path.
            geometry.append(drill.buffer(0.0000001 if buffer_value == 0 else buffer_value).exterior)
    return geometry


def milling_slots_geometry(tool_records, tools, tooldia, decimals, steps_per_circle, line_string=LineString):
    """Return slot milling rings with the existing unit-rounding allowance."""
    geometry = []
    for tool in tools:
        toolstable_tool = float('%.*f' % (decimals, float(tooldia)))
        file_tool = float('%.*f' % (decimals, float(tool_records[tool]['tooldia'])))
        buffer_value = float(file_tool / 2) - float(toolstable_tool / 2) + 0.0001
        for start, stop in tool_records[tool]['slots']:
            lines_string = line_string([start, stop])
            geometry.append(lines_string.buffer(
                0.0000001 if buffer_value == 0 else buffer_value, int(steps_per_circle)).exterior)
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


def excellon_paint_polygons(tool, line_string=LineString):
    """Build each drill/slot polygon without merging overlapping features."""
    drills_tool_geo = []
    slots_tool_geo = []
    total_paint_geo = []
    data = tool['data']
    mill_type = data['tools_mill_milling_type']
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
    buff_dia = float(tool['tooldia']) / 2.0 + offset
    if mill_type in ['drills', 'both']:
        try:
            drills_tool_geo = [d_p.buffer(buff_dia) for d_p in tool['drills']]
            total_paint_geo = drills_tool_geo
        except KeyError:
            total_paint_geo = []
    if mill_type in ['slots', 'both']:
        try:
            slots_tool_geo = [line_string(s_l).buffer(buff_dia) for s_l in tool['slots']]
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
