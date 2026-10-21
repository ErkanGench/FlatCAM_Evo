"""Read-only drill/slot measurements and tolerance-based Excellon diagnostics."""

import builtins
import gettext
import math

from shapely import Point, LineString, MultiLineString, Polygon, STRtree, box


def _(text):
    # resolved at call time: the application installs the translation after the editors are imported
    return builtins.__dict__.get('_', gettext.gettext)(text)


def feature_properties(shape, diameter, index):
    geo = shape.geo
    record = {'shape': shape, 'diameter': diameter, 'index': index,
              'type': 'drill' if isinstance(geo, MultiLineString) else 'slot' if isinstance(geo, Polygon) else 'unknown'}
    if geo is None or geo.is_empty or not geo.is_valid:
        return record
    record['bounds'] = geo.bounds
    center = geo.centroid
    record['center'] = (center.x, center.y)
    if record['type'] == 'slot':
        native = getattr(shape, 'exc_slot', None)
        record['inferred'] = native is None or getattr(shape, 'exc_slot_geometry', None) is not geo
        if not record['inferred']:
            start, stop = native
        else:
            # Legacy tools retain capsules only. These are estimates, explicitly labelled in the UI;
            # don't use their polygon vertices as editable drill/slot source data.
            coords = list(geo.minimum_rotated_rectangle.exterior.coords)
            edges = [(math.dist(a, b), a, b) for a, b in zip(coords, coords[1:])]
            extent, a, b = max(edges, key=lambda edge: edge[0])
            length = max(0.0, extent - diameter)
            ux, uy = ((b[0] - a[0]) / extent, (b[1] - a[1]) / extent) if extent else (1, 0)
            start = (center.x - ux * length / 2, center.y - uy * length / 2)
            stop = (center.x + ux * length / 2, center.y + uy * length / 2)
        record['endpoints'] = (start, stop)
        record['length'] = math.dist(start, stop)
        record['orientation'] = math.degrees(math.atan2(stop[1] - start[1], stop[0] - start[0])) % 180
        record['overall_length'] = record['length'] + diameter
    return record


def native_feature_properties(shape, diameter, index):
    """Reject geometry that a circular Excellon tool can't represent without data loss."""
    if not math.isfinite(diameter) or diameter <= 0:
        raise ValueError(_('Invalid Excellon tool diameter.'))
    record = feature_properties(shape, diameter, index)
    geo = shape.geo
    if 'bounds' not in record or record['type'] == 'unknown':
        raise ValueError(_('Invalid Excellon feature.'))
    if record['type'] == 'drill':
        arms = list(geo.geoms)
        if len(arms) != 2 or any(len(arm.coords) != 2 or arm.length == 0 for arm in arms):
            raise ValueError(_('Invalid drill cross.'))
        a, b = arms
        ax, ay = (a.coords[1][0] - a.coords[0][0], a.coords[1][1] - a.coords[0][1])
        bx, by = (b.coords[1][0] - b.coords[0][0], b.coords[1][1] - b.coords[0][1])
        if not math.isclose(a.length, b.length, rel_tol=1e-8) or \
                abs(ax * bx + ay * by) > a.length * b.length * 1e-8 or \
                a.centroid.distance(b.centroid) > max(a.length, b.length) * 1e-8:
            raise ValueError(_('Noncircular drill geometry cannot be saved as Excellon.'))
    elif record['inferred']:
        # Legacy capsules have no native endpoints. Validate their reconstruction rather
        # than silently projecting an ellipse, sheared capsule or arbitrary polygon.
        resolution = max(1, (len(geo.exterior.coords) - 3) // 4)
        capsule = LineString(record['endpoints']).buffer(diameter / 2, resolution)
        tolerance = max(diameter * 1e-8, diameter * (1 - math.cos(math.pi / (4 * resolution))))
        if geo.interiors or geo.hausdorff_distance(capsule) > tolerance:
            raise ValueError(_('Noncircular slot geometry cannot be saved as Excellon.'))
    return record


def filter_features(storage_dict, selected=None, kind='all', diameter=None, length=None, bounds=None):
    """Return feature records in storage order; bounds require complete containment."""
    if kind not in ('all', 'drill', 'slot'):
        raise ValueError(_('Invalid feature type.'))
    for limits in (diameter, length):
        if limits is not None and (len(limits) != 2 or not all(math.isfinite(v) for v in limits) or
                                   limits[0] < 0 or limits[0] > limits[1]):
            raise ValueError(_('Ranges must be finite, non-negative and ordered.'))
    if bounds is not None and (len(bounds) != 4 or not all(math.isfinite(v) for v in bounds) or
                               bounds[0] > bounds[2] or bounds[1] > bounds[3]):
        raise ValueError(_('Bounds must be finite and ordered: xmin, ymin, xmax, ymax.'))
    records = []
    for dia, storage in storage_dict.items():
        for index, shape in enumerate(storage.get_objects()):
            if selected is not None and shape not in selected:
                continue
            record = feature_properties(shape, dia, index)
            if 'bounds' not in record or not math.isfinite(dia) or dia <= 0:
                continue
            if kind != 'all' and record['type'] != kind:
                continue
            if diameter is not None and not diameter[0] <= dia <= diameter[1]:
                continue
            if length is not None and ('length' not in record or not length[0] <= record['length'] <= length[1]):
                continue
            x0, y0, x1, y1 = record['bounds']
            if bounds is not None and not (bounds[0] <= x0 and bounds[1] <= y0 and
                                           bounds[2] >= x1 and bounds[3] >= y1):
                continue
            records.append(record)
    return records


def diagnose_features(storage_dict, selected, tolerance):
    report = {key: [] for key in ('features', 'empty', 'invalid', 'degenerate', 'duplicate', 'coincident', 'invalid_tools')}
    report.update(drills=0, slots=0)
    valid = []
    for diameter, storage in storage_dict.items():
        if not math.isfinite(diameter) or diameter <= 0:
            report['invalid_tools'].append(diameter)
            continue
        for index, shape in enumerate(storage.get_objects()):
            if selected is not None and shape not in selected:
                continue
            record = feature_properties(shape, diameter, index)
            report['features'].append(record)
            if record['type'] in ('drill', 'slot'):
                report[record['type'] + 's'] += 1
            geo = shape.geo
            if geo is None or geo.is_empty:
                report['empty'].append(record)
            elif not geo.is_valid or record['type'] == 'unknown':
                report['invalid'].append(record)
            elif (record['type'] == 'drill' and geo.length <= tolerance) or \
                    (record['type'] == 'slot' and record['length'] <= tolerance):
                report['degenerate'].append(record)
            else:
                valid.append(record)
    centers = [Point(record['center']) for record in valid]
    tree = STRtree(centers)
    for index, (record, center) in enumerate(zip(valid, centers)):
        x, y = record['center']
        for candidate in tree.query(box(x - tolerance, y - tolerance, x + tolerance, y + tolerance)):
            if candidate <= index or center.distance(centers[candidate]) > tolerance:
                continue
            other = valid[candidate]
            if record['type'] != other['type']:
                continue
            if record['type'] == 'slot':
                a, b = record['endpoints']
                c, d = other['endpoints']
                error = min(max(math.dist(a, c), math.dist(b, d)), max(math.dist(a, d), math.dist(b, c)))
                if error > tolerance:
                    continue
            kind = 'duplicate' if abs(record['diameter'] - other['diameter']) <= tolerance else 'coincident'
            report[kind].append((record, other))
    return report
