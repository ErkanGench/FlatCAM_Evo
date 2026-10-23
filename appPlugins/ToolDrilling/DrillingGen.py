"""Explicit-data drilling geometry and tool calculations."""

from copy import deepcopy

import numpy as np
from shapely import LineString

from camlib import flatten_shapely_geometry


def merge_same_diameter_tools(tools):
    """Merge equal diameters, keeping the first tool's data and all its features."""
    diameters = [tool_val['tooldia'] for tool_val in tools.values()]
    if len(diameters) == len(set(diameters)):
        return tools

    merged = {}
    id_by_dia = {}
    for tool_val in tools.values():
        dia = tool_val['tooldia']
        if dia not in id_by_dia:
            id_by_dia[dia] = len(merged) + 1
            merged[id_by_dia[dia]] = deepcopy(tool_val)
            continue

        target = merged[id_by_dia[dia]]
        for key in ('drills', 'slots'):
            if tool_val.get(key):
                target[key] = list(target.get(key) or []) + list(tool_val[key])
        if tool_val.get('solid_geometry'):
            target['solid_geometry'] = flatten_shapely_geometry(
                [target.get('solid_geometry') or [], tool_val['solid_geometry']])
    return merged


def process_slot_as_drills(slot, overlap, add_last_pt=False):
    drills_list = []
    start_pt = slot[0]
    stop_pt = slot[1]
    slot_line = LineString([start_pt, stop_pt])
    drills_list.append(start_pt)

    ii = 0
    while True:
        ii += 1
        target = overlap * ii
        new_pt = slot_line.interpolate(target)
        if new_pt.within(slot_line) is False:
            break
        drills_list.append(new_pt)

    if add_last_pt and stop_pt.distance(drills_list[-1]) >= overlap/10:
        drills_list.append(stop_pt)
    return drills_list


def create_drill_points(selected_tools, selected_sorted_tools, excellon_tools,
                        drill_overlap, add_last_pt, slot_processor=process_slot_as_drills):
    """Group selected drills and converted slots without changing source tool records."""
    points = {}
    for tool_key, tl_dict in excellon_tools.items():
        if tool_key in selected_tools:
            if 'drills' in tl_dict and tl_dict['drills']:
                for drill_pt in tl_dict['drills']:
                    try:
                        points[tool_key].append(drill_pt)
                    except KeyError:
                        points[tool_key] = [drill_pt]

    for tool_key, tl_dict in excellon_tools.items():
        convert_slots = tl_dict['data']['tools_drill_drill_slots']
        if convert_slots:
            if tool_key in selected_tools:
                overlap = 1 - (drill_overlap / 100.0)
                spacing = 0.0
                for i in selected_sorted_tools:
                    if i[0] == tool_key:
                        slot_tool_dia = i[1]
                        spacing = overlap * slot_tool_dia
                        break

                new_drills = []
                if 'slots' in tl_dict and tl_dict['slots']:
                    for slot in tl_dict['slots']:
                        new_drills += slot_processor(slot=slot, overlap=spacing, add_last_pt=add_last_pt)
                    if new_drills:
                        try:
                            points[tool_key] += new_drills
                        except Exception:
                            points[tool_key] = new_drills
    return points


def distance(pt1, pt2):
    return np.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)


def distance_euclidian(x1, y1, x2, y2):
    return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
