"""Circular-aperture FOLLOW bend edits. No polygon-outline or analytic-arc editing."""

import math
import gettext
import builtins

from PyQt6 import QtCore
from shapely import LineString, Point
from shapely.errors import GEOSException
from shapely.ops import unary_union

from appEditors.grb_plugins.GrbCommon import DrawTool, DrawToolShape, DrawToolUtilityShape
from appEditors.grb_plugins.GrbHistory import gerber_operation
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def scene_state(editor):
    """Also detect untracked list/dictionary changes before a commit or one-step reversal."""
    return tuple((apid, id(aperture.get('geometry')),
                  tuple((key, id(value)) for key, value in aperture.items() if key != 'geometry'),
                  tuple((id(shape), id(shape.geo), tuple((key, id(value)) for key, value in shape.geo.items()))
                        for shape in aperture.get('geometry', ())))
                 for apid, aperture in editor.storage_dict.items())


def straight(a, b, c):
    left = (b[0] - a[0], b[1] - a[1])
    right = (c[0] - b[0], c[1] - b[1])
    return (left[0] * right[0] + left[1] * right[1] > 0 and
            abs(left[0] * right[1] - left[1] * right[0]) <=
            1e-12 * math.hypot(*left) * math.hypot(*right))


def run_limits(coords, index):
    left, right = max(0, index - 1), min(len(coords) - 1, index + 1)
    while left > 0 and straight(coords[left - 1], coords[left], coords[left + 1]):
        left -= 1
    while right < len(coords) - 1 and straight(coords[right - 1], coords[right], coords[right + 1]):
        right += 1
    return left, right


def stretch(coords, index, point):
    """Keep the neighboring bends fixed; distribute redundant samples along their new straight runs."""
    result = list(coords)
    left, right = run_limits(coords, index)
    for anchor in (left, right):
        if anchor == index:
            continue
        length = math.dist(coords[anchor], coords[index])
        for position in range(min(anchor, index) + 1, max(anchor, index)):
            fraction = math.dist(coords[anchor], coords[position]) / length
            result[position] = tuple(coords[anchor][axis] + fraction * (point[axis] - coords[anchor][axis])
                                     for axis in (0, 1))
    result[index] = point
    if any(a == b for a, b in zip(result, result[1:])):
        raise ValueError(_("The bend would collapse an adjacent segment."))
    follow = LineString(result)
    if follow.is_empty or not follow.is_valid or not follow.is_simple or follow.is_closed:
        raise ValueError(_("The bend would create an invalid or self-intersecting track."))
    return follow


def sweep_parameters(editor, aperture, shape):
    follow, solid = shape.geo.get('follow'), shape.geo.get('solid')
    width = float(aperture.get('size', 0))
    if (aperture.get('type') != 'C' or not math.isfinite(width) or width <= 0 or
            not isinstance(follow, LineString) or follow.is_closed or follow.has_z or
            getattr(follow, 'has_m', False) or not follow.is_valid or not follow.is_simple or
            solid is None or solid.is_empty or not solid.is_valid or
            not getattr(shape.geo.get('clear'), 'is_empty', True)):
        raise ValueError(_("Choose an open, unmodified circular-aperture track without clear geometry."))
    coords = list(follow.coords)
    if (not all(len(coord) == 2 and all(math.isfinite(value) for value in coord) for coord in coords) or
            any(a == b for a, b in zip(coords, coords[1:]))):
        raise ValueError(_("The track contains invalid coordinates or zero-length segments."))
    resolutions = [editor.app.options.get('gerber_circle_steps', 64),
                   getattr(editor.gerber_obj, 'steps_per_circle', None)]
    for steps in resolutions:
        if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 4096:
            continue
        for divisor in (2.0, 1.999):
            radius = width / divisor
            candidate = follow.buffer(radius, steps)
            # Joining native records can retain redundant collinear boundary vertices.
            if (solid.equals_exact(candidate, max(1e-10, width * 1e-8), normalize=True) or
                    solid.equals(candidate)):
                return radius, steps
            # A join can mix continuous corners and separately tessellated end caps.
            # Allow only the envelope between those two native sweeps, never a wider track or a gap.
            segmented = unary_union([LineString([a, b]).buffer(radius, steps)
                                     for a, b in zip(coords, coords[1:])])
            epsilon = max(1e-10, width * 1e-8)
            if (candidate.union(segmented).buffer(epsilon).covers(solid) and
                    solid.buffer(epsilon).covers(candidate.intersection(segmented))):
                return radius, steps
    raise ValueError(_("The solid no longer matches the circular aperture and FOLLOW. Bend editing was cancelled."))


class BendEdit:
    """One validated drag, with a revision-guarded before/after state, not a separate history stack."""

    def __init__(self, editor, point, tolerance):
        self.editor = editor
        self.revision = editor.geometry_revision
        self.state = scene_state(editor)
        lines = []
        candidates = {}
        for apid, aperture in editor.storage_dict.items():
            for position, shape in enumerate(aperture.get('geometry', ())):
                follow = shape.geo.get('follow')
                if getattr(follow, 'geom_type', '') not in ('LineString', 'LinearRing', 'MultiLineString'):
                    continue
                lines.append((apid, aperture, position, shape))
                if not isinstance(follow, LineString) or follow.is_empty or follow.has_z:
                    continue
                coords = list(follow.coords)
                for index, coord in enumerate(coords):
                    if len(coord) != 2 or not all(math.isfinite(value) for value in coord):
                        continue
                    if 0 < index < len(coords) - 1 and straight(coords[index - 1], coord, coords[index + 1]):
                        continue
                    distance = math.dist(point, coord)
                    if distance <= tolerance:
                        candidates[coord] = distance
        if not candidates:
            raise ValueError(_("Click near a track bend or a two-record track join."))
        ordered = sorted(candidates, key=lambda coord: candidates[coord])
        if len(ordered) > 1 and abs(candidates[ordered[0]] - candidates[ordered[1]]) <= 1e-12:
            raise ValueError(_("Several bends are equally near. Zoom in and choose one."))
        self.point = ordered[0]
        at_point = Point(self.point)
        incident = [entry for entry in lines if entry[3].geo['follow'].distance(at_point) <= 1e-10]
        self.entries = []
        for apid, aperture, position, shape in incident:
            radius, steps = sweep_parameters(editor, aperture, shape)
            coords = list(shape.geo['follow'].coords)
            indexes = [index for index, coord in enumerate(coords) if coord == self.point]
            if len(indexes) != 1:
                raise ValueError(_("The bend meets another track. Junction editing is not supported."))
            self.entries.append((apid, position, shape, indexes[0], coords, radius, steps))
        if len(self.entries) == 1:
            entry = self.entries[0]
            if entry[3] in (0, len(entry[4]) - 1):
                raise ValueError(_("An endpoint needs exactly one same-aperture continuation."))
        elif (len(self.entries) != 2 or self.entries[0][0] != self.entries[1][0] or
              any(entry[3] not in (0, len(entry[4]) - 1) for entry in self.entries)):
            raise ValueError(_("Choose a bend, not a branch or a mixed-aperture junction."))

        # A branch on a collinear sample would also detach when the adjacent straight run stretches.
        affected = {entry[2] for entry in self.entries}
        for apid, position, shape, index, coords, radius, steps in self.entries:
            left, right = run_limits(coords, index)
            moving_run = LineString(coords[left:right + 1])
            anchors = [Point(coords[end]) for end in (left, right) if end != index]
            for other in lines:
                if other[3] in affected:
                    continue
                intersection = moving_run.intersection(other[3].geo['follow'])
                if intersection.is_empty:
                    continue
                points = list(intersection.geoms) if intersection.geom_type == 'MultiPoint' else [intersection]
                if any(item.geom_type != 'Point' or not any(item.distance(anchor) <= 1e-10 for anchor in anchors)
                       for item in points):
                    raise ValueError(_("An adjacent run contains a junction or overlap. Bend editing was cancelled."))

    def replacements(self, point):
        point = tuple(float(value) for value in point)
        if len(point) != 2 or not all(math.isfinite(value) for value in point):
            raise ValueError(_("Bend coordinates must be finite two-dimensional numbers."))
        replacements = []
        for apid, position, shape, index, coords, radius, steps in self.entries:
            follow = stretch(coords, index, point)
            solid = follow.buffer(radius, steps)
            if solid.is_empty or not solid.is_valid:
                raise ValueError(_("The bend would create invalid solid geometry."))
            geometry = dict(shape.geo)
            geometry.update(follow=follow, solid=solid)
            replacements.append(DrawToolShape(geometry))
        if len(replacements) == 2:
            intersection = replacements[0].geo['follow'].intersection(replacements[1].geo['follow'])
            if intersection.geom_type != 'Point' or not intersection.equals(Point(point)):
                raise ValueError(_("The two adjacent tracks would overlap or cross."))
        return replacements

    def current(self):
        return self.revision == self.editor.geometry_revision and self.state == scene_state(self.editor)

    def write(self, shapes, selection, modified):
        editor = self.editor
        editor.history.capture([entry[0] for entry in self.entries])
        editor.history.native_shapes.update(shapes)
        by_aperture = {}
        for entry, shape in zip(self.entries, shapes):
            by_aperture.setdefault(entry[0], {})[entry[1]] = shape
        for apid, replacements in by_aperture.items():
            storage = editor.storage_dict[apid]['geometry']
            storage[:] = [replacements.get(position, shape) for position, shape in enumerate(storage)]
        editor.selected = list(selection)
        editor.is_modified = modified
        editor.touch_geometry()
        self.revision = editor.geometry_revision
        self.state = scene_state(editor)
        selected = set(selection)
        editor.sync_aperture_rows(apid for apid, aperture in editor.storage_dict.items()
                                  if any(shape in selected for shape in aperture.get('geometry', ())))
        editor.update_ui(zoom=False)
        editor.plot_all()

    @gerber_operation(_('Move track bend'))
    def commit(self, point):
        if not self.current():
            raise ValueError(_("Geometry changed during the drag. Pick the bend again."))
        if tuple(point) == self.point:
            return
        after = self.replacements(point)
        if not self.current():
            raise ValueError(_("Geometry changed during the drag. Pick the bend again."))
        self.write(after, after, True)


class TrackBendEditorGrb(DrawTool):
    uses_raw_pick = True

    def __init__(self, draw_app):
        super().__init__(draw_app)
        self.name = 'bend'
        self.edit = None
        self.start_msg = _("Drag a circular-aperture FOLLOW bend. Arc samples are polyline vertices, not arc handles.")
        draw_app.app.inform.emit(self.start_msg)

    def destination(self, point):
        if not all(math.isfinite(value) for value in point):
            raise ValueError(_("Bend coordinates must be finite."))
        return self.draw_app.app.geo_editor.snap(*point) if self.draw_app.app.grid_status() else tuple(point)

    def click(self, point):
        self.clean_up()
        try:
            self.edit = BendEdit(self.draw_app, point, 5 * self.draw_app.canvas.pixel_size())
        except (ValueError, TypeError, OverflowError, GEOSException) as err:
            self.draw_app.app.inform.emit('[WARNING_NOTCL] %s' % str(err))

    def utility_geometry(self, data=None):
        if self.edit is None:
            return
        try:
            replacements = self.edit.replacements(self.destination(data))
            return DrawToolUtilityShape({'solid': unary_union([shape.geo['solid'] for shape in replacements])})
        except (ValueError, TypeError, OverflowError, GEOSException):
            self.draw_app.tool_shape.clear(update=True)

    def click_release(self, point):
        try:
            if self.edit is not None and not self.draw_app._is_click_not_drag(point):
                self.edit.commit(self.destination(point))
        except (ValueError, TypeError, OverflowError, GEOSException) as err:
            self.draw_app.app.inform.emit('[WARNING_NOTCL] %s' % str(err))
        finally:
            self.clean_up()

    def clean_up(self):
        self.edit = None
        self.draw_app.app.selection_type = None
        self.draw_app.tool_shape.clear(update=True)

    def on_key(self, key):
        if key in ('Escape', QtCore.Qt.Key.Key_Escape):
            self.clean_up()
            self.draw_app.select_tool('select')
        else:
            super().on_key(key)
