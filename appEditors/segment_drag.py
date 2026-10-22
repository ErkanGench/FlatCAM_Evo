"""Selection-tool mouse gestures shared by the Geometry and Gerber editors."""
import math
import gettext
import builtins

from PyQt6 import QtCore
from shapely import Point
from shapely.affinity import translate
from shapely.errors import GEOSException

from appEditors.segment_ops import segments_of, segment_geometries
from appEditors.vertex_ops import SUPPORTED_TYPES, parts_of, rings_of
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

CLICK_DRAG_THRESHOLD_PX = 5


class SegmentDrag:

    def __init__(self, grips):
        self.grips = grips
        self.editor = grips.editor
        self.selected = {}       # shape -> set of segment addresses in its original geometry
        self.pressed = None      # (mode, screen point, canvas point, snapped anchor)
        self.geometries = {}
        self.candidate = None
        self.dragging = False
        self.state = None
        self.toggle = None       # (segment selection before the press, shape, address) of a Ctrl+Shift/Alt press
        self._key = None
        self._collection = None

    def context(self):
        return (getattr(self.editor.active_tool, 'name', None),
                tuple(self.grips.key(shape) for shape in self.editor.selected),
                getattr(getattr(self.editor, 'storage', None), 'revision', None),
                None if self.grips.snapshot is None else self.grips.snapshot())

    def sync(self):
        key = self.context()
        if key != self._key:
            self.clear()
            self._key = key

    def clear(self):
        self.cancel()
        self.selected.clear()
        self.draw()

    def draw(self):
        if not self.selected and self._collection is None:
            return
        if self._collection is None:
            self._collection = self.editor.app.plotcanvas.new_shape_collection(layers=1)
        self._collection.clear(update=False)
        color = self.grips.colors()[0]
        for shape, addresses in self.selected.items():
            for address, line in segments_of(self.grips.geometry(shape)):
                if address in addresses:
                    self._collection.add(shape=line, color=color, update=False, layer=0, tolerance=None)
        self._collection.redraw()

    def candidates(self, point):
        hits = self.editor.pick_candidates(point)
        return [hit[0] if isinstance(hit, tuple) else hit for hit in hits]

    def hit(self, point):
        """Pick the nearest straight segment in screen pixels, including the body of a thick Gerber trace."""
        radius = 6 * self.grips.pixel()
        best = None
        probe = Point(point)
        candidates = self.candidates(point)
        for shape in sorted(candidates, key=lambda shape: shape not in self.editor.selected):
            try:
                geometry = self.grips.geometry(shape)
            except ValueError:
                continue
            if not isinstance(geometry, SUPPORTED_TYPES) or geometry.is_empty or geometry.has_z:
                continue
            # Match the existing grip limit before doing arc recognition on a large contour.
            if sum(len(ring.coords) for part in parts_of(geometry) for ring in rings_of(part)) > 5000:
                continue
            trace_body = (isinstance(shape.geo, dict) and geometry is shape.geo.get('follow') and
                          shape.geo.get('solid') is not None and shape.geo['solid'].covers(probe))
            for address, line in segments_of(geometry):
                distance = line.distance(probe)
                if distance <= radius or trace_body:
                    rank = (shape not in self.editor.selected, distance)
                    if best is None or rank < best[0]:
                        best = rank, shape, address
        return None if best is None else best[1:]

    def refresh_selection(self):
        self._key = self.context()
        tool = self.editor.active_tool
        if hasattr(tool, 'after_selection'):
            self.editor.update_ui()
            tool.after_selection()
        else:
            if hasattr(self.editor, 'sync_tree_selection'):
                self.editor.sync_tree_selection()
            if hasattr(self.editor, 'update_ui'):
                self.editor.update_ui()
            self.editor.plot_changes()

    def snap(self, point):
        return tuple(self.editor.snap(*point)) if self.editor.app.grid_status() else point

    def press(self, screen_pos, canvas_pos, modifiers):
        if getattr(self.editor.active_tool, 'name', None) != 'select' or \
                not hasattr(self.editor, 'apply_selection_drag') or self.editor.reject_busy():
            return False
        self.sync()
        shift = bool(modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & QtCore.Qt.KeyboardModifier.AltModifier)
        ctrl = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)
        point = tuple(canvas_pos[:2])
        if ctrl and (shift or alt):
            found = self.hit(point)
            if found is None:
                return False
            shape, address = found
            # A click without a drag toggles the segment in the previous segment selection (see release()).
            self.toggle = {key: set(value) for key, value in self.selected.items()}, shape, address
            if address not in self.selected.get(shape, ()):
                self.selected = {shape: {address}}
            mode = 'cords' if alt else 'stretch'
            if shape not in self.editor.selected:
                self.editor.selected.append(shape)
                self.refresh_selection()
            self.draw()
            self.geometries = {shape: self.grips.geometry(shape) for shape in self.selected}
            if mode == 'stretch':
                # Existing records can meet at a common endpoint without having been joined into one shape.
                endpoints = {tuple(coord) for shape, addresses in self.selected.items()
                             for address, line in segments_of(self.geometries[shape]) if address in addresses
                             for coord in line.coords}
                for endpoint in endpoints:
                    for neighbor in self.candidates(endpoint):
                        if neighbor in self.geometries:
                            continue
                        try:
                            geometry = self.grips.geometry(neighbor)
                        except ValueError:
                            continue
                        if isinstance(geometry, SUPPORTED_TYPES) and not geometry.has_z:
                            self.geometries[neighbor] = geometry
        elif shift or alt or ctrl:
            # Ctrl+click (multiple selection) and Shift+click (copy coordinates) stay with the editor.
            return False
        else:
            candidates = self.candidates(point)
            if not candidates:
                self.clear()
                return False
            shape = next((shape for shape in candidates if shape in self.editor.selected), candidates[0])
            if shape not in self.editor.selected:
                self.editor.selected[:] = [shape]
                self.refresh_selection()
            self.selected.clear()
            self.draw()
            mode = 'move'
            self.geometries = {shape: shape.geo.get('solid') if isinstance(shape.geo, dict) else shape.geo
                               for shape in self.editor.selected}
        self.pressed = mode, tuple(screen_pos[:2]), point, self.snap(point)
        self.state = self.context(), tuple((shape, self.grips.key(shape)) for shape in self.geometries)
        return True

    def stale(self):
        return self.state != (self.context(), tuple((shape, self.grips.key(shape)) for shape in self.geometries))

    def move(self, screen_pos, canvas_pos):
        if self.pressed is None:
            return False
        mode, screen, start, anchor = self.pressed
        if not self.dragging and math.dist(tuple(screen_pos[:2]), screen) < CLICK_DRAG_THRESHOLD_PX:
            return True
        self.dragging = True
        point = self.snap(tuple(canvas_pos[:2]))
        offset = point[0] - anchor[0], point[1] - anchor[1]
        color, invalid = self.grips.colors()
        self.candidate = None
        try:
            if mode == 'move':
                results = {shape: translate(geometry, *offset) for shape, geometry in self.geometries.items()}
            else:
                results = segment_geometries(self.geometries, self.selected, offset, cords=mode == 'cords')
            self.candidate = results, offset if mode == 'move' else None
        except (ValueError, TypeError, OverflowError, GEOSException):
            color = invalid
            results = {shape: translate(geometry, *offset) for shape, geometry in self.geometries.items()
                       if shape in self.selected}
        collection = self.editor.tool_shape
        collection.clear(update=False)
        for geometry in results.values():
            collection.add(shape=geometry, color=color, update=False, layer=0, tolerance=None)
        collection.redraw()
        return True

    def release(self, screen_pos, canvas_pos):
        if self.pressed is None:
            return False
        mode, screen, start, anchor = self.pressed
        self.move(screen_pos, canvas_pos)
        candidate, dragging, stale, toggle = self.candidate, self.dragging, self.stale(), self.toggle
        self.cancel()
        if stale:
            self.sync()
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' %
                                        _('Geometry changed during the drag. Select the segments again.'))
        elif dragging and candidate is not None:
            results, offset = candidate
            if results:
                self.editor.apply_selection_drag(results, offset=offset)
            self.sync()
        elif not dragging and mode == 'move':
            self.editor.active_tool.click_release(start)
            self.refresh_selection()
        elif not dragging and toggle is not None:
            selected, shape, address = toggle
            addresses = selected.setdefault(shape, set())
            if address in addresses:
                addresses.remove(address)
                if not addresses:
                    del selected[shape]
            else:
                addresses.add(address)
            self.selected = selected
            self.draw()
        return True

    def cancel(self):
        if self.dragging:
            self.editor.tool_shape.clear(update=True)
        self.pressed, self.candidate, self.dragging, self.toggle = None, None, False, None
