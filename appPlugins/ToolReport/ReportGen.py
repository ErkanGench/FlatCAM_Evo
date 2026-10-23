"""Object report geometry calculations on explicit data. No Qt."""

from shapely import MultiPolygon, Polygon
from shapely.ops import unary_union


def calculate_dimensions(geo, tools, kind, units, bounds=None):
    """Return (box area, length, width, hull area, copper area) and recoverable errors.

    Keep the report's existing unit conversions, including copper area / 100 in
    inch projects, and its per-tool hull fallback rather than changing displayed values.
    """
    length = 0.0
    width = 0.0
    area = 0.0
    copper_area = 0.0
    errors = []
    if geo:
        if bounds is not None:
            try:
                xmin, ymin, xmax, ymax = bounds
                length = abs(xmax - xmin)
                width = abs(ymax - ymin)
            except Exception as ee:
                errors.append("PropertiesTool.addItems() -> calculate dimensions --> %s" % str(ee))
        if units.lower() == 'mm':
            area = (length * width) / 100
        else:
            area = length * width
        if kind.lower() == 'gerber':
            try:
                for geo_el in geo:
                    copper_area += geo_el.area
            except TypeError:
                copper_area += geo.area
            copper_area /= 100
    else:
        xmin = []
        ymin = []
        xmax = []
        ymax = []
        # Preserve the two passes used by the CNCJob report, including error recovery.
        for _ in range(2 if kind.lower() == 'cncjob' else 1):
            try:
                for tool_k in tools:
                    x0, y0, x1, y1 = unary_union(tools[tool_k]['solid_geometry']).bounds
                    xmin.append(x0)
                    ymin.append(y0)
                    xmax.append(x1)
                    ymax.append(y1)
            except Exception as ee:
                errors.append("PropertiesTool.addItems() --> %s" % str(ee))
        try:
            xmin = min(xmin)
            ymin = min(ymin)
            xmax = max(xmax)
            ymax = max(ymax)
            length = abs(xmax - xmin)
            width = abs(ymax - ymin)
            if units.lower() == 'mm':
                area = (length * width) / 100
            else:
                area = length * width
            if kind.lower() == 'gerber':
                geo_tools = []
                for tool_k in tools:
                    if 'solid_geometry' in tools[tool_k]:
                        for geo_el in tools[tool_k]['solid_geometry']:
                            geo_tools.append(geo_el)
                geo_tools_mp = MultiPolygon(geo_tools)
                try:
                    for geo_el in geo_tools_mp.geoms:
                        copper_area += geo_el.area
                except TypeError:
                    copper_area += geo_tools_mp.area
                copper_area /= 100
        except Exception as err:
            errors.append("Properties.addItems() --> %s" % str(err))

    area_chull = 0.0
    if kind.lower() != 'cncjob':
        if geo:
            if isinstance(geo, list) and geo[0] is not None:
                if isinstance(geo, MultiPolygon):
                    env_obj = geo.convex_hull
                elif (isinstance(geo, MultiPolygon) and len(geo.geoms) == 1) or \
                        (isinstance(geo, list) and len(geo) == 1) and isinstance(geo[0], Polygon):
                    env_obj = unary_union(geo)
                    env_obj = env_obj.convex_hull
                else:
                    env_obj = unary_union(geo)
                    env_obj = env_obj.convex_hull
                area_chull = env_obj.area
            else:
                area_chull = 0
        else:
            try:
                area_chull = []
                for tool_k in tools:
                    area_el = unary_union(tools[tool_k]['solid_geometry']).convex_hull
                    area_chull.append(area_el.area)
                area_chull = max(area_chull)
            except Exception as er:
                area_chull = None
                errors.append("Properties.addItems() --> %s" % str(er))
    if units.lower() == 'mm' and area_chull:
        area_chull = area_chull / 100
    if area_chull is None:
        area_chull = 0
    return (area, length, width, area_chull, copper_area), errors
