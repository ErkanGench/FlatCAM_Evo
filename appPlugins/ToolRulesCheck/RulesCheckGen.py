# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 09/27/2019                                         #
# MIT Licence                                              #
# ##########################################################

from copy import deepcopy

from shapely import Polygon, MultiPolygon
from shapely.ops import nearest_points


def check_inside_gerber_clearance(gerber_obj, size, rule):
    # log.debug("RulesCheck.check_inside_gerber_clearance()")

    rule_title = rule

    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'points': list()
    })

    if not gerber_obj:
        return 'Fail. Not enough Gerber objects to check Gerber 2 Gerber clearance'

    obj_violations['name'] = gerber_obj['name']

    solid_geo = []
    clear_geo = []
    for apid in gerber_obj['apertures']:
        if 'geometry' in gerber_obj['apertures'][apid]:
            geometry = gerber_obj['apertures'][apid]['geometry']
            for geo_el in geometry:
                if 'solid' in geo_el and geo_el['solid'] is not None:
                    solid_geo.append(geo_el['solid'])
                if 'clear' in geo_el and geo_el['clear'] is not None:
                    clear_geo.append(geo_el['clear'])

    if clear_geo:
        total_geo = []
        for geo_c in clear_geo:
            for geo_s in solid_geo:
                if geo_c.within(geo_s):
                    total_geo.append(geo_s.difference(geo_c))
    else:
        total_geo = MultiPolygon(solid_geo)
        total_geo = total_geo.buffer(0.000001)

    if isinstance(total_geo, Polygon):
        obj_violations['points'] = ['Failed. Only one polygon.']
        return rule_title, [obj_violations]
    else:
        iterations = len(total_geo)
        iterations = (iterations * (iterations - 1)) / 2
    # log.debug("RulesCheck.check_gerber_clearance(). Iterations: %s" % str(iterations))

    min_dict = {}
    idx = 1
    for geo in total_geo:
        for s_geo in total_geo[idx:]:
            # minimize the number of distances by not taking into considerations those that are too small
            dist = geo.distance(s_geo)
            if float(dist) < float(size):
                loc_1, loc_2 = nearest_points(geo, s_geo)

                dx = loc_1.x - loc_2.x
                dy = loc_1.y - loc_2.y
                loc = min(loc_1.x, loc_2.x) + (abs(dx) / 2), min(loc_1.y, loc_2.y) + (abs(dy) / 2)

                if dist in min_dict:
                    min_dict[dist].append(loc)
                else:
                    min_dict[dist] = [loc]
        idx += 1
    points_list = set()
    for dist in min_dict.keys():
        for location in min_dict[dist]:
            points_list.add(location)

    obj_violations['points'] = list(points_list)
    violations.append(deepcopy(obj_violations))

    return rule_title, violations


def check_gerber_clearance(gerber_list, size, rule):
    # log.debug("RulesCheck.check_gerber_clearance()")
    rule_title = rule

    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'points': list()
    })

    if len(gerber_list) == 2:
        gerber_1 = gerber_list[0]
        # added it, so I won't have errors of using before declaring
        gerber_2 = {}

        gerber_3 = gerber_list[1]
    elif len(gerber_list) == 3:
        gerber_1 = gerber_list[0]
        gerber_2 = gerber_list[1]
        gerber_3 = gerber_list[2]
    else:
        return 'Fail. Not enough Gerber objects to check Gerber 2 Gerber clearance'

    total_geo_grb_1 = []
    for apid in gerber_1['apertures']:
        if 'geometry' in gerber_1['apertures'][apid]:
            geometry = gerber_1['apertures'][apid]['geometry']
            for geo_el in geometry:
                if 'solid' in geo_el and geo_el['solid'] is not None:
                    total_geo_grb_1.append(geo_el['solid'])

    if len(gerber_list) == 3:
        # add the second Gerber geometry to the first one if it exists
        for apid in gerber_2['apertures']:
            if 'geometry' in gerber_2['apertures'][apid]:
                geometry = gerber_2['apertures'][apid]['geometry']
                for geo_el in geometry:
                    if 'solid' in geo_el and geo_el['solid'] is not None:
                        total_geo_grb_1.append(geo_el['solid'])

    total_geo_grb_3 = []
    for apid in gerber_3['apertures']:
        if 'geometry' in gerber_3['apertures'][apid]:
            geometry = gerber_3['apertures'][apid]['geometry']
            for geo_el in geometry:
                if 'solid' in geo_el and geo_el['solid'] is not None:
                    total_geo_grb_3.append(geo_el['solid'])

    total_geo_grb_1 = MultiPolygon(total_geo_grb_1)
    total_geo_grb_1 = total_geo_grb_1.buffer(0)

    total_geo_grb_3 = MultiPolygon(total_geo_grb_3)
    total_geo_grb_3 = total_geo_grb_3.buffer(0)

    if isinstance(total_geo_grb_1, Polygon):
        len_1 = 1
        total_geo_grb_1 = [total_geo_grb_1]
    else:
        len_1 = len(total_geo_grb_1)

    if isinstance(total_geo_grb_3, Polygon):
        len_3 = 1
        total_geo_grb_3 = [total_geo_grb_3]
    else:
        len_3 = len(total_geo_grb_3)

    iterations = len_1 * len_3
    # log.debug("RulesCheck.check_gerber_clearance(). Iterations: %s" % str(iterations))

    min_dict = {}
    for geo in total_geo_grb_1:
        for s_geo in total_geo_grb_3:
            # minimize the number of distances by not taking into considerations those that are too small
            dist = geo.distance(s_geo)
            if float(dist) < float(size):
                loc_1, loc_2 = nearest_points(geo, s_geo)

                dx = loc_1.x - loc_2.x
                dy = loc_1.y - loc_2.y
                loc = min(loc_1.x, loc_2.x) + (abs(dx) / 2), min(loc_1.y, loc_2.y) + (abs(dy) / 2)

                if dist in min_dict:
                    min_dict[dist].append(loc)
                else:
                    min_dict[dist] = [loc]

    points_list = set()
    for dist in min_dict.keys():
        for location in min_dict[dist]:
            points_list.add(location)

    name_list = []
    if gerber_1:
        name_list.append(gerber_1['name'])
    if gerber_2:
        name_list.append(gerber_2['name'])
    if gerber_3:
        name_list.append(gerber_3['name'])

    obj_violations['name'] = name_list
    obj_violations['points'] = list(points_list)
    violations.append(deepcopy(obj_violations))

    return rule_title, violations


def check_holes_size(elements, size, rule):
    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'dia': list()
    })

    for elem in elements:
        dia_list = []

        name = elem['name']
        for tool in elem['tools']:
            tool_dia = float('%.*f' % (4, float(elem['tools'][tool]['tooldia'])))
            if tool_dia < float(size):
                dia_list.append(tool_dia)
        obj_violations['name'] = name
        obj_violations['dia'] = dia_list
        violations.append(deepcopy(obj_violations))

    return rule, violations


def check_holes_clearance(elements, size, rule):
    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'points': list()
    })

    total_geo = []
    for elem in elements:
        for tool in elem['tools']:
            if 'solid_geometry' in elem['tools'][tool]:
                geometry = elem['tools'][tool]['solid_geometry']
                for geo in geometry:
                    total_geo.append(geo)

    min_dict = {}
    idx = 1
    for geo in total_geo:
        for s_geo in total_geo[idx:]:

            # minimize the number of distances by not taking into considerations those that are too small
            dist = geo.distance(s_geo)
            loc_1, loc_2 = nearest_points(geo, s_geo)

            dx = loc_1.x - loc_2.x
            dy = loc_1.y - loc_2.y
            loc = min(loc_1.x, loc_2.x) + (abs(dx) / 2), min(loc_1.y, loc_2.y) + (abs(dy) / 2)

            if dist in min_dict:
                min_dict[dist].append(loc)
            else:
                min_dict[dist] = [loc]
        idx += 1

    points_list = set()
    for dist in min_dict.keys():
        if float(dist) < size:
            for location in min_dict[dist]:
                points_list.add(location)

    name_list = []
    for elem in elements:
        name_list.append(elem['name'])

    obj_violations['name'] = name_list
    obj_violations['points'] = list(points_list)
    violations.append(deepcopy(obj_violations))

    return rule, violations


def check_traces_size(elements, size, rule):
    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'size': list(),
        'points': list()
    })

    for elem in elements:
        dia_list = []
        points_list = []
        name = elem['name']

        for apid in elem['apertures']:
            try:
                tool_dia = float(elem['apertures'][apid]['size'])
                if tool_dia < float(size) and tool_dia != 0.0:
                    dia_list.append(tool_dia)
                    for geo_el in elem['apertures'][apid]['geometry']:
                        if 'solid' in geo_el.keys():
                            geo = geo_el['solid']
                            pt = geo.representative_point()
                            points_list.append((pt.x, pt.y))
            except Exception:
                # An exception  will be raised for the 'size' key in case of apertures of type AM (macro) which does
                # not have the size key
                pass

        obj_violations['name'] = name
        obj_violations['size'] = dia_list
        obj_violations['points'] = points_list
        violations.append(deepcopy(obj_violations))
    return rule, violations


def check_gerber_annular_ring(obj_list, size, rule):
    rule_title = rule

    violations = []
    obj_violations = {}
    obj_violations.update({
        'name': '',
        'points': list()
    })

    # added it so, I won't have errors of using before declaring
    gerber_obj = {}
    gerber_extra_obj = {}
    exc_obj = {}
    exc_extra_obj = {}

    if len(obj_list) == 2:
        gerber_obj = obj_list[0]
        exc_obj = obj_list[1]
        if 'apertures' in gerber_obj and 'tools' in exc_obj:
            pass
        else:
            return 'Fail. At least one Gerber and one Excellon object is required to check Minimum Annular Ring'
    elif len(obj_list) == 3:
        o1 = obj_list[0]
        o2 = obj_list[1]
        o3 = obj_list[2]
        if 'apertures' in o1 and 'apertures' in o2:
            gerber_obj = o1
            gerber_extra_obj = o2
            exc_obj = o3
        elif 'tools' in o2 and 'tools' in o3:
            gerber_obj = o1
            exc_obj = o2
            exc_extra_obj = o3
    elif len(obj_list) == 4:
        gerber_obj = obj_list[0]
        gerber_extra_obj = obj_list[1]
        exc_obj = obj_list[2]
        exc_extra_obj = obj_list[3]
    else:
        return 'Fail. Not enough objects to check Minimum Annular Ring'

    total_geo_grb = []
    for apid in gerber_obj['apertures']:
        if 'geometry' in gerber_obj['apertures'][apid]:
            geometry = gerber_obj['apertures'][apid]['geometry']
            for geo_el in geometry:
                if 'solid' in geo_el and geo_el['solid'] is not None:
                    total_geo_grb.append(geo_el['solid'])

    if len(obj_list) == 3 and gerber_extra_obj:
        # add the second Gerber geometry to the first one if it exists
        for apid in gerber_extra_obj['apertures']:
            if 'geometry' in gerber_extra_obj['apertures'][apid]:
                geometry = gerber_extra_obj['apertures'][apid]['geometry']
                for geo_el in geometry:
                    if 'solid' in geo_el and geo_el['solid'] is not None:
                        total_geo_grb.append(geo_el['solid'])

    total_geo_grb = MultiPolygon(total_geo_grb)
    total_geo_grb = total_geo_grb.buffer(0)

    total_geo_exc = []
    for tool in exc_obj['tools']:
        if 'solid_geometry' in exc_obj['tools'][tool]:
            geometry = exc_obj['tools'][tool]['solid_geometry']
            for geo in geometry:
                total_geo_exc.append(geo)

    if len(obj_list) == 3 and exc_extra_obj:
        # add the second Excellon geometry to the first one if it exists
        for tool in exc_extra_obj['tools']:
            if 'solid_geometry' in exc_extra_obj['tools'][tool]:
                geometry = exc_extra_obj['tools'][tool]['solid_geometry']
                for geo in geometry:
                    total_geo_exc.append(geo)

    if isinstance(total_geo_grb, Polygon):
        len_1 = 1
        total_geo_grb = [total_geo_grb]
    else:
        len_1 = len(total_geo_grb)

    if isinstance(total_geo_exc, Polygon):
        len_2 = 1
        total_geo_exc = [total_geo_exc]
    else:
        len_2 = len(total_geo_exc)

    iterations = len_1 * len_2
    # log.debug("RulesCheck.check_gerber_annular_ring(). Iterations: %s" % str(iterations))

    min_dict = {}
    dist = None
    for geo in total_geo_grb:
        for s_geo in total_geo_exc:
            try:
                # minimize the number of distances by not taking into considerations those that are too small
                dist = abs(geo.exterior.distance(s_geo))
            except Exception:
                # log.error("RulesCheck.check_gerber_annular_ring() --> %s" % str(e))
                pass

            if dist > 0:
                if float(dist) < float(size):
                    loc_1, loc_2 = nearest_points(geo.exterior, s_geo)

                    dx = loc_1.x - loc_2.x
                    dy = loc_1.y - loc_2.y
                    loc = min(loc_1.x, loc_2.x) + (abs(dx) / 2), min(loc_1.y, loc_2.y) + (abs(dy) / 2)

                    if dist in min_dict:
                        min_dict[dist].append(loc)
                    else:
                        min_dict[dist] = [loc]
            else:
                if dist in min_dict:
                    min_dict[dist].append(s_geo.representative_point())
                else:
                    min_dict[dist] = [s_geo.representative_point()]

    points_list = []
    for dist in min_dict.keys():
        for location in min_dict[dist]:
            points_list.append(location)

    name_list = []
    try:
        if gerber_obj:
            name_list.append(gerber_obj['name'])
    except KeyError:
        pass
    try:
        if gerber_extra_obj:
            name_list.append(gerber_extra_obj['name'])
    except KeyError:
        pass

    try:
        if exc_obj:
            name_list.append(exc_obj['name'])
    except KeyError:
        pass

    try:
        if exc_extra_obj:
            name_list.append(exc_extra_obj['name'])
    except KeyError:
        pass

    obj_violations['name'] = name_list
    obj_violations['points'] = points_list
    violations.append(deepcopy(obj_violations))
    return rule_title, violations
