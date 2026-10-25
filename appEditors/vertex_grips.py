"""
Grips on the vertices of 1 selected shape: drag a vertex grip to move the vertex, drag a midpoint grip to insert a
vertex, Ctrl+click a vertex grip to remove the vertex. An arc has 3 grips: drag its middle grip to bend it, drag an
end grip to move that end, Ctrl+click the middle grip to make it a straight segment. A full circle has 4 radius grips.

Away from the grips, the Selection Tool delegates to SegmentDrag: drag the object body to move it, Ctrl+Shift+click or
Ctrl+Alt+click to add or remove a straight segment, Ctrl+Shift+drag to stretch the segments, or Ctrl+Alt+drag to pull
them with endpoint cords. These 2 gestures win over the grips. Ctrl+click and Shift+click stay with the editor
(multiple selection, copy coordinates). The modifiers can be released during a drag; Escape or a right click cancels.

The editor keeps 1 instance as `vertex_grips` and calls sync(), press(), move(), release() and cancel(). Commits go
through apply_vertex_edit() or apply_selection_drag(), so 1 drag is 1 Undo step. Only x and y of each point are used:
VisPy translate_coords() returns (x, y, z, w).
"""
import math
import gettext
import builtins

from PyQt6 import QtCore
import shapely
from shapely import LineString, Polygon, box
from shapely.errors import GEOSException

from appEditors.vertex_ops import SUPPORTED_TYPES, DEFAULT_CIRCLE_STEPS, vertex_grips, ring_after_edit, \
    edit_vertex, check_vertex_result, contrast_color
from appEditors.segment_drag import SegmentDrag, CLICK_DRAG_THRESHOLD_PX
import appTranslation as fcTranslate
from camlib import object_circle_steps

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

GRIP_HIT_PX = 6             # hit radius of a grip, in screen pixels
GRIP_SIZE_PX = 4            # half the side of a vertex grip square, in screen pixels
GRIP_GAP_PX = 12            # minimum distance between 2 shown grips, in screen pixels
GRIP_LIMIT = 5000           # shapes with more vertices get no grips
GRIP_FACE_ALPHA = '80'      # the fill of a grip is half transparent: the shape under it stays visible
GRIP_COLOR = '#FF8000FF'
INVALID_COLOR = '#FF0000FF'
# the edit action of a drag and of a Ctrl+click, for each grip kind (no entry: the Ctrl+click does nothing)
DRAG_ACTIONS = {'vertex': 'move', 'mid': 'insert', 'arc_end': 'arc_end', 'arc_mid': 'arc_mid',
                'radius': 'arc_radius'}
CLICK_ACTIONS = {'vertex': 'remove', 'arc_end': 'remove', 'arc_mid': 'arc_flatten'}


def xy(pos):
    return float(pos[0]), float(pos[1])


def spaced_grips(grips, gap):
    """The grips that are at least gap apart, so that dense grips do not cover the shape when zoomed out. Vertex,
    arc and radius grips come before the midpoint grips; in each group, the first grip in the list wins."""
    cells = {}
    shown = []
    for grip in sorted(grips, key=lambda item: item[0] == 'mid'):
        x, y = grip[2]
        cx, cy = math.floor(x / gap), math.floor(y / gap)
        if any(math.dist((x, y), other) < gap
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for other in cells.get((cx + dx, cy + dy), ())):
            continue
        cells.setdefault((cx, cy), []).append((x, y))
        shown.append(grip)
    return shown


class VertexGrips:

    def __init__(self, editor, geometry=None, steps_option=None, snapshot=None):
        """
        :param geometry:     callable(shape) -> the shapely geometry to edit, None for a shape without grips. It may
                             raise ValueError (the message is shown). Default: shape.geo.
        :param steps_option: a function of the radius that gives the circle steps of new arcs, or the application
                             option with them. Default: the Geometry preference "Circles" (adaptive or fixed)
        :param snapshot:     callable() -> the state of the editor storage. If it changed between show() and a press,
                             or between a press and the release, the grips are rebuilt and nothing is committed.
        """
        self.editor = editor
        self.geometry = geometry or (lambda shape: shape.geo)
        self.steps_option = steps_option
        self.snapshot = snapshot
        self.state = None       # snapshot() of show() and of the press
        self.geo = None         # the geometry of self.shape
        self.shape = None       # the shape with grips
        self.grips = []         # [(kind, address, (x, y))] of self.shape
        self.shown = []         # the grips of the last draw(): only these take a press
        self.pressed = None     # (kind, address, grip point, screen point, Ctrl held) of the pressed grip
        self.dragging = False
        self.candidate = None   # (action, address, point) of the last preview with valid input
        self._key = None        # (id(shape), id(shape.geo)) of the last sync()
        self._pixel = None      # pixel size of the last draw()
        self._collection = None
        self._zoom_timer = None  # redraws the grips after a zoom, also without a mouse move
        self.segment_drag = SegmentDrag(self)

    def collection(self):
        if self._collection is None:
            self._collection = self.editor.app.plotcanvas.new_shape_collection(layers=1)
            self.watch_zoom()
        return self._collection

    def watch_zoom(self):
        try:
            changed = self.editor.canvas.view.camera.transform.changed
        except AttributeError:
            return  # a canvas without a VisPy camera: the next mouse move redraws the grips
        self._zoom_timer = QtCore.QTimer()
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(50)
        self._zoom_timer.timeout.connect(self.on_zoom)
        changed.connect(lambda *args: self._zoom_timer.start())

    def on_zoom(self):
        if self.shape is not None and self._pixel is not None and self.pixel() != self._pixel:
            self.draw()

    def pixel(self):
        return self.editor.canvas.pixel_size()

    def steps(self):
        if callable(self.steps_option):
            return self.steps_option
        if self.steps_option is None:
            app = self.editor.app
            return lambda radius: object_circle_steps(app.options, 'geometry', radius, app.app_units)
        return self.editor.app.options.get(self.steps_option, DEFAULT_CIRCLE_STEPS)

    def grid_step(self):
        """The larger grid gap of the editor, or 0."""
        try:
            options = self.editor.editor_options
            return max(abs(float(options['global_gridx'])), abs(float(options['global_gridy'])))
        except (AttributeError, KeyError, TypeError, ValueError):
            return 0.0

    def background(self):
        try:
            return self.editor.canvas.view.bgcolor.hex
        except AttributeError:
            return '#FFFFFF'

    def colors(self):
        """(grip color, invalid color), each changed to its opposite if it is near an editor or canvas color."""
        editor = self.editor
        used = [editor.get_draw_color(), editor.get_sel_color(),
                editor.app.options.get('global_sel_line', '#0000ffbf'), self.background()]
        grip = contrast_color(GRIP_COLOR, used)
        return grip, contrast_color(INVALID_COLOR, used + [grip])

    def sync(self):
        """Grips on the only selected shape while the Select tool is active; none in any other case."""
        self.segment_drag.sync()
        editor = self.editor
        selected = list(editor.selected)
        shape = selected[0] if len(selected) == 1 and getattr(editor.active_tool, 'name', None) == 'select' else None
        key = None if shape is None else self.key(shape)
        if key == self._key:
            return
        self.hide()
        if shape is not None:
            self.show(shape)

    def key(self, shape):
        # an editor that changes shapes in place counts the changes in geometry_revision
        return id(shape), id(shape.geo), getattr(self.editor, 'geometry_revision', None)

    def show(self, shape):
        self.hide()
        self._key = self.key(shape)
        self.state = None if self.snapshot is None else self.snapshot()
        try:
            geo = self.geometry(shape)
        except ValueError as err:
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' % str(err))
            return
        if not isinstance(geo, SUPPORTED_TYPES) or geo.is_empty or geo.has_z:
            return
        if shapely.get_num_coordinates(geo) > GRIP_LIMIT:
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' %
                                        _("The shape has too many vertices for grips. Use Edit vertices."))
            return
        self.shape, self.geo, self.grips = shape, geo, vertex_grips(geo)
        self.collection().enabled = True
        self.draw()

    def hide(self):
        self.cancel()
        self.shape, self.geo, self.grips, self.shown, self._key, self._pixel = None, None, [], [], None, None
        if self._collection is not None:
            self._collection.clear(update=True)
            self._collection.enabled = False

    def draw(self):
        collection = self.collection()
        collection.clear(update=False)
        self._pixel = pixel = self.pixel()
        self.shown = spaced_grips(self.grips, GRIP_GAP_PX * pixel) if pixel > 0 else list(self.grips)
        color = self.colors()[0]
        face = color[:7] + GRIP_FACE_ALPHA
        for kind, __, (x, y) in self.shown:
            half = GRIP_SIZE_PX * pixel * (0.6 if kind == 'mid' else 1.0)
            if kind in ('vertex', 'arc_end'):
                square = box(x - half, y - half, x + half, y + half)
                collection.add(shape=square, color=color, face_color=face, update=False, layer=0, tolerance=None)
            elif kind == 'mid':
                square = box(x - half, y - half, x + half, y + half)
                collection.add(shape=square.exterior, color=color, update=False, layer=0, tolerance=None)
            else:
                diamond = Polygon([(x - half, y), (x, y - half), (x + half, y), (x, y + half)])
                if kind == 'radius':
                    collection.add(shape=diamond, color=color, face_color=face, update=False, layer=0,
                                   tolerance=None)
                else:
                    collection.add(shape=diamond.exterior, color=color, update=False, layer=0, tolerance=None)
        collection.redraw()

    def hit(self, point):
        """(kind, address, grip point) of the grip under point, or None. With the grid on, the pick radius is at
        least 1 grid step. Midpoint grips last, then the nearest grip, then the lower address (2 parts that touch
        at 1 vertex). Only the shown grips count: zoom in to reach the others."""
        radius = GRIP_HIT_PX * self.pixel()
        if self.editor.app.grid_status():
            radius = max(radius, self.grid_step())
        best = None
        for kind, address, grip in self.shown:
            dist = math.dist(point, grip)
            if dist > radius:
                continue
            rank = (kind == 'mid', dist, address)
            if best is None or rank < best[0]:
                best = (rank, kind, address, grip)
        return None if best is None else best[1:]

    def stale(self):
        """True if the editor storage changed since show()."""
        return self.snapshot is not None and self.snapshot() != self.state

    def resync(self):
        self._key = None
        self.sync()

    def press(self, screen_pos, canvas_pos, modifiers):
        """True if a grip took the press."""
        self.cancel()
        if getattr(self.editor.active_tool, 'name', None) != 'select' or self.editor.reject_busy():
            return False
        if self.shape is not None and self.stale():
            self.resync()
            return False
        ctrl = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)
        if ctrl and modifiers & (QtCore.Qt.KeyboardModifier.ShiftModifier | QtCore.Qt.KeyboardModifier.AltModifier):
            # A segment gesture wins over the grips: with the grid on, a grip catches 1 grid step around a vertex.
            return self.segment_drag.press(screen_pos, canvas_pos, modifiers)
        found = self.hit(xy(canvas_pos)) if self.shape is not None else None
        if found is None:
            return self.segment_drag.press(screen_pos, canvas_pos, modifiers)
        if ctrl and found[0] == 'mid':
            return False  # a midpoint grip has no Ctrl+click action: the editor toggles the shape selection
        self.pressed = (*found, xy(screen_pos), ctrl)
        return True

    def target(self, canvas_pos):
        """The snapped drag point. Corner snap to the start point of the dragged vertex is ignored."""
        x, y = xy(canvas_pos)
        editor = self.editor
        if not editor.app.grid_status():
            return x, y
        snapped = tuple(editor.snap(x, y))
        kind, __, start = self.pressed[:3]
        if kind in ('vertex', 'arc_end') and snapped == start and \
                getattr(editor, 'active_snap_type', None) == 'corner':
            return x, y
        return snapped

    def move(self, screen_pos, canvas_pos):
        """True while a grip is pressed: the editor must not run its own move code."""
        if self.shape is not None and self._pixel is not None and self.pixel() != self._pixel:
            self.draw()  # the zoom changed: keep the grips at their size in pixels
        if self.segment_drag.move(screen_pos, canvas_pos):
            return True
        if self.pressed is None:
            return False
        kind, address, __, press_screen, __ = self.pressed
        if not self.dragging:
            if math.dist(xy(screen_pos), press_screen) < CLICK_DRAG_THRESHOLD_PX:
                return True
            self.dragging = True
        action = DRAG_ACTIONS[kind]
        point = self.target(canvas_pos)
        self.preview(action, address, point)
        return True

    def preview(self, action, address, point):
        tool_shape = self.editor.tool_shape
        tool_shape.clear(update=False)
        grip_color, invalid_color = self.colors()
        geo = self.geo
        try:
            coords = ring_after_edit(geo, action, address, point, steps=self.steps())
        except (ValueError, TypeError, OverflowError, GEOSException):
            self.candidate = None
            tool_shape.redraw()
            return
        self.candidate = (action, address, point)
        try:
            check_vertex_result(edit_vertex(geo, action, address, point, steps=self.steps()), address)
            color = grip_color
        except (ValueError, TypeError, OverflowError, GEOSException):
            color = invalid_color
        tool_shape.add(shape=LineString(coords), color=color, update=False, layer=0, tolerance=None)
        tool_shape.redraw()

    def release(self, screen_pos, canvas_pos):
        """True if a grip took the release. A drag commits; a Ctrl+click removes a vertex or flattens an arc."""
        if self.segment_drag.release(screen_pos, canvas_pos):
            return True
        if self.pressed is None:
            return False
        if self.dragging:
            self.move(screen_pos, canvas_pos)
        kind, address, __, __, ctrl = self.pressed
        dragging, candidate, shape = self.dragging, self.candidate, self.shape
        self.cancel()
        if self.stale():
            self.resync()
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' %
                                        _("Geometry changed during the drag. Pick the vertex again."))
            return True
        if not dragging:
            if ctrl and kind in CLICK_ACTIONS:
                self.editor.apply_vertex_edit(CLICK_ACTIONS[kind], address, target=shape)
            return True
        if candidate is not None:
            action, address, point = candidate
            self.editor.apply_vertex_edit(action, address, point, target=shape, on_segment=False)
        return True

    def cancel(self):
        self.segment_drag.cancel()
        if self.dragging:
            self.editor.tool_shape.clear(update=True)
        self.pressed, self.dragging, self.candidate = None, False, None
