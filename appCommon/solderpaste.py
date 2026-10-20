"""Solder-paste aperture planning and calibrated dispensing. Volumes are always microlitres (mm³)."""
import ast
import math

from shapely import LineString, Point, Polygon, STRtree
from shapely.affinity import rotate
from shapely.ops import unary_union


CONTROLLERS = ('Mach3', 'Mach4', 'LinuxCNC', 'GRBL', 'Marlin')
PREFIX = 'tools_solderpaste_'


def restore_paste_metadata(obj, saved):
    """Restore optional paste metadata, including projects saved before the role was serialized."""
    tools = getattr(obj, 'tools', {})
    paste_tools = [tool for tool in tools.values()
                   if isinstance(tool, dict) and tool.get('type') == 'SolderPaste'] if isinstance(tools, dict) else []
    if saved.get('special_group') == 'solder_paste_tool' or paste_tools:
        obj.special_group = 'solder_paste_tool'
        if hasattr(obj, 'pp_solderpaste_name'):
            data = paste_tools[0].get('data', {}) if paste_tools else {}
            pp_name = data.get(PREFIX + 'pp', 'Paste_1')
            if data.get(PREFIX + 'volume_mode', 'Legacy') != 'Legacy':
                pp_name = {'Marlin': 'Paste_Marlin', 'GRBL': 'Paste_GRBL'}.get(
                    str(data.get(PREFIX + 'controller', 'Mach3')), 'Paste_1')
            obj.pp_solderpaste_name = saved.get('pp_solderpaste_name') or pp_name


def parse_numbers(value, count=None, allow_empty=False):
    """Read finite numeric literals, never Python expressions or executable input."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_empty:
            return []
        raise ValueError('A numeric value is required.')
    try:
        if isinstance(value, str):
            if len(value) > 4096:
                raise ValueError('Numeric input is too long.')
            value = ast.literal_eval(value)
        values = value if isinstance(value, (list, tuple)) else [value]
        if count is not None and len(values) != count:
            raise ValueError('Expected %d numeric values.' % count)
        if not values or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
            raise ValueError('Use numeric literals separated by commas.')
        values = [float(v) for v in values]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Numeric values must be finite.')
        return values
    except (SyntaxError, TypeError, OverflowError, RecursionError) as err:
        raise ValueError('Use numeric literals separated by commas.') from err


def _parts(geometry, kind):
    if isinstance(geometry, (list, tuple)):
        return [part for child in geometry for part in _parts(child, kind)]
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, kind):
        return [geometry]
    return [part for child in getattr(geometry, 'geoms', ()) for part in _parts(child, kind)]


def extract_pads(obj):
    """Include flashes and region aperture 0, clip to final polarity, merge overlapping apertures."""
    pads = []
    clears = []
    for uid, aperture in obj.tools.items():
        for element in aperture.get('geometry', ()):
            clears.extend(_parts(element.get('clear'), Polygon))
            follow = element.get('follow')
            if str(uid) == '0' or isinstance(follow, (Point, Polygon)):
                pads.extend(_parts(element.get('solid'), Polygon))
    if not pads:
        return []
    final = _parts(getattr(obj, 'solid_geometry', None), Polygon)
    masks = final or clears
    if masks:
        tree = STRtree(masks)
        clipped = []
        for pad in pads:
            nearby = tree.query(pad, predicate='intersects')
            if len(nearby):
                mask = unary_union([masks[int(i)] for i in nearby])
                clipped.extend(_parts(pad.intersection(mask) if final else pad.difference(mask), Polygon))
            elif not final:
                clipped.append(pad)
        pads = clipped
    pads = list({pad.wkb: pad for pad in pads if pad.area > 0}.values())
    if not pads:
        return []
    tree = STRtree(pads)
    parents = list(range(len(pads)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, pad in enumerate(pads):
        for j in tree.query(pad, predicate='intersects'):
            if int(j) > i:
                parents[root(int(j))] = root(i)
    groups = {}
    for i, pad in enumerate(pads):
        groups.setdefault(root(i), []).append(pad)
    return [part for group in groups.values()
            for part in _parts(group[0] if len(group) == 1 else unary_union(group), Polygon)]


def parameters(data, units='MM', for_geometry=False):
    from defaults import AppDefaults

    p = {key[len(PREFIX):]: value for key, value in AppDefaults.factory_defaults.items()
         if key.startswith(PREFIX)}
    p.update({key[len(PREFIX):]: value for key, value in data.items() if key.startswith(PREFIX)})
    p['unit_mm'] = 25.4 if units.upper() == 'IN' else 1.0
    if units.upper() not in ('IN', 'MM'):
        raise ValueError('Unsupported job units.')
    choices = {'controller': CONTROLLERS, 'drive': ('Motor', 'Stepper'),
               'volume_mode': ('Thickness', 'Fixed volume', 'Legacy'),
               'placement': ('Auto', 'Line', 'Raster', 'Dot'),
               'axis': ('A', 'B', 'C', 'E'), 'axis_mode': ('Linear', 'Rotary'),
               'mach3_dwell': ('Seconds', 'Milliseconds'), 'grbl_mode': ('Spindle', 'Laser')}
    for name, values in choices.items():
        if p[name] not in values:
            raise ValueError('Unsupported solder-paste %s: %s' % (name, p[name]))
    if any(not isinstance(p[name], bool) for name in ('z_rise', 'marlin_cold')):
        raise ValueError('Use boolean values for slow Z approach and cold-extrusion confirmation.')
    positive = ('thickness', 'volume', 'calibration', 'syringe_dia', 'pitch', 'gear_ratio',
                'plunger_feed', 'dot_dia', 'frxy', 'fr_rapids', 'frz', 'frz_dispense')
    nonnegative = ('flow_rate', 'overlap', 'prime', 'retract', 'dwellfwd', 'dwellrev',
                   'speedfwd', 'speedrev')
    for name in positive + nonnegative + ('margin', 'z_start', 'z_dispense', 'z_stop',
                                         'z_travel', 'z_toolchange'):
        p[name] = parse_numbers(p[name], count=1)[0]
        if (name in positive and p[name] <= 0) or (name in nonnegative and p[name] < 0):
            raise ValueError('%s must be %s.' % (name, 'positive' if name in positive else 'non-negative'))
    if not 0 <= p['overlap'] < 100 or p['margin'] < 0:
        raise ValueError('Use overlap below 100 and a non-negative pad margin.')
    if p['z_travel'] <= max(p['z_dispense'], p['z_start'] if p['z_rise'] else p['z_dispense']):
        raise ValueError('Travel Z must be above the dispensing height.')
    if p['z_toolchange'] < p['z_travel']:
        raise ValueError('Tool-change Z must not be below Travel Z.')
    p['xy_toolchange'] = parse_numbers(p['xy_toolchange'], count=2, allow_empty=True)
    if not for_geometry:
        if p['drive'] == 'Motor' and (p['flow_rate'] <= 0 or p['speedfwd'] <= 0):
            raise ValueError('Enter a measured flow rate at the selected forward motor speed.')
        if p['controller'] == 'GRBL' and (p['drive'] == 'Stepper' or p['grbl_mode'] == 'Laser'):
            raise ValueError('Stock GRBL needs spindle mode ($32=0); it has no extra extrusion axis.')
        if p['drive'] == 'Stepper':
            if p['controller'] == 'Marlin':
                if p['axis'] != 'E' or p['axis_mode'] != 'Linear':
                    raise ValueError('Marlin requires the linear E axis calibrated in plunger millimetres.')
                if not p['marlin_cold']:
                    raise ValueError('Configure Marlin for cold extrusion, then enable its confirmation in the UI.')
            elif p['axis'] == 'E':
                raise ValueError('Choose A, B or C for this CNC controller.')
    return p


def pad_paths(pad, diameter, data, units='MM'):
    """Return independent paths and their volume shares. Never connect across a hole."""
    p = data if 'unit_mm' in data else parameters(data, units, for_geometry=True)
    if not pad.is_valid or not math.isfinite(diameter) or diameter <= 0:
        raise ValueError('Invalid pad polygon or nozzle diameter.')
    margin = p['margin'] * diameter / 100.0
    inner = pad.buffer(-diameter / 2 - margin)
    placement = p['placement']
    paths = []
    if placement != 'Dot' and not inner.is_empty:
        corners = list(pad.minimum_rotated_rectangle.exterior.coords)
        edges = [(corners[i + 1][0] - corners[i][0], corners[i + 1][1] - corners[i][1]) for i in (0, 1)]
        dx, dy = max(edges, key=lambda edge: edge[0] ** 2 + edge[1] ** 2)
        angle = math.degrees(math.atan2(dy, dx))
        local = rotate(inner, -angle, origin=(0, 0))
        xmin, ymin, xmax, ymax = local.bounds
        if placement == 'Line' or placement == 'Auto' and ymax - ymin <= diameter * 0.5:
            rows = [(ymin + ymax) / 2]
        else:
            spacing = diameter * (1 - p['overlap'] / 100.0)
            count = max(1, math.ceil((ymax - ymin) / spacing))
            if count > 100000:
                raise ValueError('Raster spacing creates too many strokes; increase it.')
            rows = [ymin + (ymax - ymin) * i / count for i in range(count + 1)]
        for row, y in enumerate(rows):
            segments = _parts(LineString([(xmin - diameter, y), (xmax + diameter, y)]).intersection(local), LineString)
            for segment in segments:
                if segment.length > diameter * 1e-9:
                    if row % 2:
                        segment = LineString(list(segment.coords)[::-1])
                    paths.append(rotate(segment, angle, origin=(0, 0)))
    if not paths and placement in ('Auto', 'Dot'):
        dot = pad.buffer(-p['dot_dia'] / 2 - margin)
        if not dot.is_empty:
            paths = [dot.representative_point()]
    if not paths:
        return [], []
    volume = pad.area * p['unit_mm'] ** 2 * p['thickness'] if p['volume_mode'] == 'Thickness' else p['volume']
    total_length = sum(path.length for path in paths)
    volumes = [volume * path.length / total_length for path in paths] if total_length else [volume]
    return paths, volumes


def generate_program(job, tool, is_first=False):
    """Generate calibrated code, failing before publication if any dose cannot be delivered."""
    import numpy as np
    from camlib import new_rtree_index, grace

    p = parameters(tool['data'], job.units)
    paths = tool['solid_geometry']
    volumes = tool.get('dispense_volumes', ())
    if not paths or len(paths) != len(volumes):
        raise ValueError('Regenerate solder-paste geometry to calculate path volumes.')
    if any(not isinstance(path, (LineString, Point)) or path.is_empty or not path.is_valid or
           isinstance(path, LineString) and path.length <= 0 for path in paths):
        raise ValueError('Dispensing geometry must contain individual lines or dots.')
    volumes = parse_numbers(volumes)
    if any(v <= 0 for v in volumes):
        raise ValueError('Every dispensing path needs a positive volume.')
    controller = p['controller']
    motor = p['drive'] == 'Motor'
    marlin = controller == 'Marlin'
    decimals = job.coords_decimals
    feed_decimals = max(job.fr_decimals, 4)
    output = []
    emit = output.append

    def comment(text):
        return ';' + text if marlin else '(' + text + ')'

    def number(value):
        if not math.isfinite(value):
            raise ValueError('Non-finite dispensing coordinate or feed rate.')
        return '%.*f' % (decimals, value)

    def position(point):
        x, y = point
        if job._bed_skew_x and not job._bed_limit_y or job._bed_skew_y and not job._bed_limit_x:
            raise ValueError('Bed-skew correction needs a non-zero bed size.')
        x_pos = x + job._bed_offset_x + (y / job._bed_limit_y * job._bed_skew_x if job._bed_skew_x else 0)
        y_pos = y + job._bed_offset_y + (x / job._bed_limit_x * job._bed_skew_y if job._bed_skew_y else 0)
        return float(number(x_pos)), float(number(y_pos))

    def xy(point):
        x, y = position(point)
        return 'X%s Y%s' % (number(x), number(y))

    def dwell(seconds):
        if seconds > 0:
            factor = 1000 if controller == 'Mach3' and p['mach3_dwell'] == 'Milliseconds' else 1
            if not math.isfinite(seconds * factor) or round(seconds * factor, 6) <= 0:
                raise ValueError('Dispensing time is outside the dwell output range.')
            emit('G4 %s%.6f' % ('S' if marlin else 'P', seconds * factor))

    def move_z(height, feed):
        emit('G1 Z%s F%.*f' % (number(height), feed_decimals, feed))

    area = math.pi * (p['syringe_dia'] / 2) ** 2
    axis_scale = 360 * p['gear_ratio'] / p['pitch'] if p['axis_mode'] == 'Rotary' else 1 / p['unit_mm']
    if not math.isfinite(area) or not math.isfinite(axis_scale) or area <= 0 or axis_scale <= 0:
        raise ValueError('Syringe geometry or axis scaling is outside the numeric range.')
    extrusion = 0.0

    def extrude(plunger_mm):
        nonlocal extrusion
        previous = extrusion
        extrusion += plunger_mm * axis_scale
        if not math.isfinite(extrusion) or round(extrusion, 8) == round(previous, 8):
            raise ValueError('Dose or retract is outside the extrusion-axis output precision.')
        if marlin:
            emit('G1 %s%.8f F%.*f' % (p['axis'], extrusion, feed_decimals,
                                      p['plunger_feed'] / p['unit_mm']))
        elif plunger_mm:
            seconds = abs(plunger_mm) * 60 / p['plunger_feed']
            if seconds <= 0 or not math.isfinite(60 / seconds):
                raise ValueError('Extrusion time is outside the inverse-time feed range.')
            emit('G93')
            emit('G1 %s%.8f F%.8f' % (p['axis'], extrusion, 60 / seconds))
            emit('G94')

    if is_first:
        emit(comment('Calibrated solder paste: %s / %s; volume in uL' % (controller, p['drive'])))
        emit('G20' if job.units.upper() == 'IN' else 'G21')
        emit('G90')
        emit('G94')
    emit('M5')
    move_z(p['z_toolchange'], p['fr_rapids'])
    if p['xy_toolchange']:
        emit('G1 %s F%.*f' % (xy(p['xy_toolchange']), feed_decimals, p['fr_rapids']))
    emit(comment('Change nozzle T%d, diameter %s' % (job.tool, number(tool['tooldia']))))
    emit('M0')
    if not motor:
        if marlin:
            emit('M82')
            emit('M200 D0')
            emit('M221 S100')
        emit('G92 %s0' % p['axis'])
    endpoints = [(tuple(path.coords[0]), tuple(path.coords[-1])) for path in paths]
    # the id of an end point is its row: i * 2 + end (bulk load from an array)
    index = new_rtree_index(points=np.array([point[:2] for pair in endpoints for point in pair], dtype=np.float64))
    current = tuple(p['xy_toolchange']) if p['xy_toolchange'] else (0, 0)
    retracted = False
    for completed in range(len(paths)):
        if job.app.abort_flag:
            raise grace
        # k=1 returns all the points at the smallest distance (ties): the lowest id keeps the order stable
        nearest = min(index.nearest((*current, *current), 1))
        i, end = divmod(nearest, 2)
        for endpoint, point in enumerate(endpoints[i]):
            index.delete(i * 2 + endpoint, (*point, *point))
        path = paths[i]
        coords = list(path.coords)
        if end:
            coords.reverse()
        dose = volumes[i] * p['calibration']
        if not math.isfinite(dose) or dose <= 0:
            raise ValueError('Corrected dispensing volume is outside the numeric range.')
        emit(comment('PASTE_VOLUME %.10f' % volumes[i]))
        move_z(p['z_travel'], p['fr_rapids'])
        emit('G1 %s F%.*f' % (xy(coords[0]), feed_decimals, p['fr_rapids']))
        if p['z_rise']:
            move_z(p['z_start'], p['frz'])
        move_z(p['z_dispense'], p['frz_dispense'] if p['z_rise'] else p['frz'])
        if not motor and retracted:
            extrude(p['retract'])
        emit(comment('PASTE_ON'))
        if isinstance(path, Point):
            emit(comment('PASTE_DOT %s D%s' % (xy(coords[0]), number(p['dot_dia']))))
            if motor:
                emit('M3 S%.6f' % p['speedfwd'])
                dwell(dose / p['flow_rate'])
            else:
                extrude(dose / area)
        else:
            prime = p['prime']
            if prime >= dose:
                raise ValueError('Prime volume must be smaller than each path dose; reduce prime volume.')
            lengths = [math.dist(position(start), position(stop)) for start, stop in zip(coords, coords[1:])]
            path_length = sum(lengths)
            if path_length <= 0:
                raise ValueError('Path is smaller than the coordinate precision; increase precision or use a dot.')
            plunger = (dose - prime) / area
            if motor:
                seconds = (dose - prime) / p['flow_rate']
                feed = path_length * 60 / seconds
                if feed > p['frxy'] * (1 + 1e-9):
                    raise ValueError('Measured flow is too high for the XY feed limit; reduce flow or increase feed.')
                if not math.isfinite(feed) or round(feed, feed_decimals) <= 0:
                    raise ValueError('Dose requires a feed below the output precision; adjust flow or dose.')
                emit('M3 S%.6f' % p['speedfwd'])
                dwell(prime / p['flow_rate'])
            else:
                if prime:
                    extrude(prime / area)
                seconds = max(path_length / p['frxy'] * 60, plunger / p['plunger_feed'] * 60)
                feed = path_length * 60 / seconds
                if not marlin:
                    emit('G93')
            for stop, length in zip(coords[1:], lengths):
                if length == 0:
                    continue
                if motor:
                    emit('G1 %s F%.*f' % (xy(stop), feed_decimals, feed))
                else:
                    previous = extrusion
                    extrusion += plunger * axis_scale * length / path_length
                    segment_feed = feed if marlin else 60 / (seconds * length / path_length)
                    if not math.isfinite(extrusion) or not math.isfinite(segment_feed) or \
                            round(extrusion, 8) == round(previous, 8):
                        raise ValueError('Segment dose is outside the extrusion-axis output precision.')
                    emit('G1 %s %s%.8f F%.8f' % (xy(stop), p['axis'], extrusion, segment_feed))
            if not motor and not marlin:
                emit('G94')
        emit(comment('PASTE_OFF'))
        if motor:
            emit('M5')
            if p['dwellrev'] and p['speedrev']:
                emit('M4 S%.6f' % p['speedrev'])
                dwell(p['dwellrev'])
                emit('M5')
        elif p['retract']:
            extrude(-p['retract'])
            retracted = True
        move_z(p['z_travel'], p['fr_rapids'])
        current = coords[-1]
        percent = (completed + 1) * 100 // len(paths)
        previous = completed * 100 // len(paths)
        if percent != previous:
            job.app.proc_container.update_view_text(' %d%%' % percent)
    move_z(p['z_toolchange'], p['fr_rapids'])
    end_xy = parse_numbers(job.xy_end, count=2, allow_empty=True)
    if end_xy:
        emit('G1 %s F%.*f' % (xy(end_xy), feed_decimals, p['fr_rapids']))
    job.pp_solderpaste_name = {'GRBL': 'Paste_GRBL', 'Marlin': 'Paste_Marlin'}.get(controller, 'Paste_1')
    return '\n'.join(output) + '\n'
