# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Dennis Hayrullin                            #
# Date: 2/5/2016                                           #
# MIT Licence                                              #
# ##########################################################

from vispy.visuals import CompoundVisual, LineVisual, MeshVisual, TextVisual, MarkersVisual
from vispy.visuals.gridlines import GridLinesVisual as VisPyGridLinesVisual, _GRID_COLOR
from vispy.visuals.shaders import Function
from vispy.scene.visuals import VisualNode, generate_docstring, visuals
from vispy.gloo import set_state
from vispy.color import Color
from shapely import Polygon, LineString, LinearRing
import itertools
import threading
import numpy as np
from functools import lru_cache
from appGUI.VisPyTesselators import GLUTess

# set_gl_state() replaces the whole state and set_state() sends only the given keys, so a visual without these
# draws with the blend of the previous visual (the grid uses 'additive')
_BLEND = dict(blend=True, blend_func=('src_alpha', 'one_minus_src_alpha'))

# ShapeGroup ids and the creation order of the buckets of a collection (the later bucket draws over the earlier one)
_BUCKET_IDS = itertools.count(1)
_BUCKET_SEQ = itertools.count()
_DEFAULT_BUCKET = 0


class _Bucket(object):
    """
    The shapes of one ShapeGroup (one object) in a ShapeCollectionVisual, with their own mesh and line visuals per layer.
    A bucket that did not change is not uploaded to the GPU again.
    """
    __slots__ = ('seq', 'keys', 'dirty', 'meshes', 'lines')

    def __init__(self):
        self.seq = next(_BUCKET_SEQ)
        self.keys = {}          # shape keys in draw order (a dict keeps the order)
        self.dirty = True
        self.meshes = {}        # layer: MeshVisual, only for the layers with faces
        self.lines = {}         # layer: LineVisual, only for the layers with lines


def _concat(chunks, empty_shape, dtype):
    return np.concatenate(chunks) if chunks else np.empty(empty_shape, dtype=dtype)


def _has_mesh(data):
    return len(data['mesh_tris']) > 0 and len(data['mesh_vertices']) > 0


# class FlatCAMLineVisual(LineVisual):
#     def __init__(self, pos=None, color=(0.5, 0.5, 0.5, 1), width=1, connect='strip', method='gl', antialias=False):
#         LineVisual.__init__(self, pos=pos, color=color, width=width, connect=connect,
#                             method=method, antialias=True)
#
#     def clear_data(self):
#         self._bounds = None
#         self._pos = None
#         self._changed['pos'] = True
#         self.update()


@lru_cache(maxsize=128)
def _cached_color_rgba(color):
    return Color(color).rgba


def _update_shape_buffers(data, triangulation='glu'):
    """
    Translates Shapely geometry to internal buffers for speedup redraws
    :param data: dict
        Input shape data
    :param triangulation: str
        Triangulation engine
    """
    mesh_vertices = []                                              # Vertices for mesh
    mesh_tris = []                                                  # Faces for mesh
    mesh_rgba = np.zeros(4, dtype=np.float32)                       # One face color for the whole shape
    line_pts = []                                                   # Vertices for line
    line_rgba = np.zeros(4, dtype=np.float32)                       # One line color for the whole shape

    geo, color, face_color, tolerance = data['geometry'], data['color'], data['face_color'], data['tolerance']

    if geo is not None and not geo.is_empty:
        simplified_geo = geo.simplify(tolerance) if tolerance else geo      # Simplified shape
        pts = []                                                            # Shape line points
        tri_pts = []                                                        # Mesh vertices
        tri_tris = []                                                       # Mesh faces

        if type(geo) == LineString:
            # Prepare lines
            pts = _linestring_to_segments(simplified_geo.coords)

        elif type(geo) == LinearRing:
            # Prepare lines
            pts = _linearring_to_segments(simplified_geo.coords)

        elif type(geo) == Polygon:
            # Prepare polygon faces
            if face_color is not None:
                if triangulation == 'glu':
                    gt = GLUTess()
                    tri_tris, tri_pts = gt.triangulate(simplified_geo)
                else:
                    print("Triangulation type '%s' isn't implemented. Drawing only edges." % triangulation)

            # Prepare polygon edges
            if color is not None:
                pts = _linearring_to_segments(simplified_geo.exterior.coords)
                if len(simplified_geo.interiors):
                    pts = np.concatenate([pts] + [
                        _linearring_to_segments(ints.coords) for ints in simplified_geo.interiors])

        # Appending data for mesh
        if len(tri_pts) > 0 and len(tri_tris) > 0:
            mesh_tris += tri_tris
            mesh_vertices += tri_pts
            face_color_rgba = (_cached_color_rgba(face_color) if isinstance(face_color, str)
                               else Color(face_color).rgba)
            mesh_rgba = face_color_rgba

        # Appending data for line
        if len(pts) > 0:
            line_pts = pts
            line_rgba = _cached_color_rgba(color) if isinstance(color, str) else Color(color).rgba

    # Store buffers as numpy arrays for faster concatenation in __update()
    data['line_pts'] = np.asarray(line_pts, dtype=np.float32) if len(line_pts) else np.empty((0, 2), dtype=np.float32)
    # The color is stored once per shape. __update() repeats it for every vertex.
    data['line_rgba'] = np.asarray(line_rgba, dtype=np.float32).reshape(4)
    data['mesh_vertices'] = np.array(mesh_vertices, dtype=np.float32) if mesh_vertices else np.empty((0, 2), dtype=np.float32)
    data['mesh_tris'] = np.array(mesh_tris, dtype=np.uint32) if mesh_tris else np.empty(0, dtype=np.uint32)
    data['mesh_rgba'] = np.asarray(mesh_rgba, dtype=np.float32).reshape(4)

    # Clear shapely geometry
    del data['geometry']

    return data


def _linearring_to_segments(arr):
    # Close linear ring
    """
    Translates linear ring to line segments
    :param arr: numpy.array
        Array of linear ring vertices
    :return: numpy.array
        Line segments
    """
    arr = np.asarray(arr)
    if len(arr) and not np.array_equal(arr[0], arr[-1]):
        arr = np.concatenate((arr, arr[:1]))
    return _linestring_to_segments(arr)


def _linestring_to_segments(arr):
    """
    Translates line strip to segments
    :param arr: numpy.array
        Array of line strip vertices
    :return: numpy.array
        Line segments
    """
    arr = np.asarray(arr)
    if len(arr) < 2:
        return np.empty((0, 2), dtype=np.float32)
    segments = np.empty(((len(arr) - 1) * 2, arr.shape[1]), dtype=np.float32)
    segments[0::2] = arr[:-1]
    segments[1::2] = arr[1:]
    return segments


@lru_cache(maxsize=128)
def _cached_hover_buffers(bounds, units, color, face_color):
    xmin, ymin, xmax, ymax = bounds
    shape = Polygon([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])
    shape = shape.buffer(-0.1).buffer(0.2) if units == 'MM' else shape.buffer(-0.00393).buffer(0.00787)
    return _update_shape_buffers({
        'geometry': shape, 'color': color, 'face_color': face_color,
        'alpha': None, 'visible': True, 'layer': 0, 'tolerance': None
    })


class ShapeGroup(object):
    def __init__(self, collection):
        """
        Represents group of shapes in collection
        :param collection: ShapeCollection
            Collection to work with
        """
        self._collection = collection
        self._indexes = []
        self._visible = True
        self._enabled = True
        self._color = None
        # the collection keeps the shapes of a group together (own visuals, own GPU upload)
        self._bucket = next(_BUCKET_IDS)

    def add(self, **kwargs):
        """
        Adds shape to collection and store index in group
        :param kwargs: keyword arguments.
            Arguments for ShapeCollection.add function
        """
        key = self._collection.add(bucket=self._bucket, **kwargs)
        self._indexes.append(key)
        return key

    def add_batch(self, shapes_data, **kwargs):
        """
        Batch adds shapes to collection and stores indexes in group.
        """
        keys = self._collection.add_batch(shapes_data, bucket=self._bucket, **kwargs)
        self._indexes.extend(keys)
        return keys
    
    def remove(self, idx, update=False):
        self._indexes.remove(idx)
        self._collection.remove(idx, False)
        if update:
            self._collection.redraw([])             # Skip waiting results

    def clear(self, update=False):
        """
        Removes group shapes from collection, clear indexes
        :param update: bool
            Set True to redraw collection
        """
        for i in self._indexes:
            self._collection.remove(i, False)

        del self._indexes[:]

        if update:
            self._collection.redraw([])             # Skip waiting results

    def transform(self, matrix, update=True):
        """
        Applies an affine transform (shapely 6-tuple) to the shapes of the group without a new triangulation.

        :return: True if done. False if the caller has to plot the shapes again.
        """
        return self._collection.transform_keys(list(self._indexes), matrix, update)

    def redraw(self, update_colors=None):
        """
        Redraws shape collection
        """
        if update_colors:
            self._collection.redraw(self._indexes, update_colors=update_colors)
        else:
            self._collection.redraw(self._indexes)

    @property
    def visible(self):
        """
        Visibility of group
        :return: bool
        """
        return self._visible

    @visible.setter
    def visible(self, value):
        """
        Visibility of group
        :param value: bool
        """
        self._visible = value
        data = self._collection.data
        for i in self._indexes:
            if i in data:
                data[i]['visible'] = value

        # the collection skips the update if it is not marked dirty
        self._collection.mark_dirty(self._bucket)
        self._collection.redraw([])

    @property
    def enabled(self):
        """
        Another way to toggle visibility on canvas
        :return:
        :rtype:
        """
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        """
        Another way to toggle visibility on canvas
        :param value: bool
        """
        self._collection.enabled = value

    def move_to_top(self):
        """
        Draw the shapes of the group over all the other shapes of the collection
        """
        if self._collection.move_to_top(self._indexes):
            self._collection.redraw([])

    def update_visibility(self, state, indexes=None):
        data = self._collection.data
        if indexes:
            # a set: a membership test on the list is O(n) for each index
            group_indexes = set(self._indexes)
            for i in indexes:
                if i in group_indexes and i in data:
                    data[i]['visible'] = state
        else:
            for i in self._indexes:
                if i in data:
                    data[i]['visible'] = state

        # the collection skips the update if it is not marked dirty
        self._collection.mark_dirty(self._bucket)
        self._collection.redraw([])


class RectangleVisual(CompoundVisual):
    """Keep rubber-band topology and styling; dragging updates only vertex positions."""

    def __init__(self, linewidth):
        self._vertices = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=np.float32)
        self._mesh = MeshVisual(vertices=self._vertices, faces=np.array([(0, 1, 2), (0, 2, 3)]))
        self._line = LineVisual(pos=self._vertices[[0, 1, 1, 2, 2, 3, 3, 0]],
                                connect='segments', width=linewidth, antialias=True)
        # Reversing a drag mirrors the unit square; both windings must remain visible.
        self._mesh.set_gl_state(polygon_offset_fill=True, polygon_offset=(1, 1), cull_face=False, **_BLEND)
        self._line.set_gl_state(**_BLEND)
        self._rect = None
        self._colors = None
        super().__init__([self._mesh, self._line])

    def set_data(self, start, end, color, face_color):
        x0, y0 = start
        x1, y1 = end
        rect = (x0, y0, x1, y1)
        if rect != self._rect:
            self._vertices[:] = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
            self._mesh.mesh_data.set_vertices(self._vertices)
            self._mesh.set_data(meshdata=self._mesh.mesh_data)
            self._line.set_data(pos=self._vertices[[0, 1, 1, 2, 2, 3, 3, 0]])
            self._rect = rect
        colors = (color, face_color)
        if colors != self._colors:
            if color is not None:
                self._line.set_data(color=color)
            if face_color is not None:
                self._mesh.color = face_color
            self._colors = colors
        self._line.visible = color is not None
        self._mesh.visible = face_color is not None and x1 != x0 and y1 != y0


class ShapeCollectionVisual(CompoundVisual):

    def __init__(self, linewidth=1, triangulation='vispy', layers=3, pool=None, fcoptions=None, **kwargs):
        """
        Represents collection of shapes to draw on VisPy scene
        :param linewidth: float
            Width of lines/edges
        :param triangulation: str
            Triangulation method used for polygons translation
            'vispy' - VisPy lib triangulation
            'gpc' - Polygon2 lib
        :param layers: int
            Layers count
            Each layer adds 2 visuals on VisPy scene. Be careful: more layers cause less fps
        :param kwargs:
        """
        self.fc_options = fcoptions

        self.data = {}
        self.last_key = -1
        self._top_keys = set()
        self._rectangle = None
        
        # Dirty flag to track whether buffers need rebuilding
        self._dirty = True

        # Thread locks
        self.key_lock = threading.Lock()
        self.results_lock = threading.Lock()
        self.update_lock = threading.Lock()

        # Process pool
        self.pool = pool
        self.results = {}
        self._batch_results = []  # NEW: list of (keys, AsyncResult) tuples for batch processing

        self._layers = layers
        # Backface culling - safe with CCW winding enforcement in tessellator
        self._cull = True
        if self.fc_options:
            self._cull = self.fc_options.get("global_backface_culling", True)

        # Every ShapeGroup has its own bucket: own visuals per layer. The shapes added without a group are in the
        # default bucket. A bucket that is empty is deleted; its visuals are removed on the next update.
        self._buckets = {}
        self._key_bucket = {}       # shape key: bucket id
        self._dead = []             # empty buckets, their visuals are still in the scene
        self._visual_rank = {}            # id(visual): (layer, 0 mesh | 1 line, bucket creation order)
        self._rank_changed = False
        self._built_width = None

        # Selected objects are an overlay, independent of their normal plotting layer: one global pair of visuals.
        self._top_order = []
        self._top_dirty = False
        self._top_mesh = MeshVisual()
        self._top_line = LineVisual(antialias=True)
        self._visual_rank[id(self._top_mesh)] = (layers, 0, 0)
        self._visual_rank[id(self._top_line)] = (layers, 1, 0)

        self._line_width = linewidth
        self._triangulation = triangulation

        CompoundVisual.__init__(self, [self._top_mesh, self._top_line], **kwargs)

        self._top_mesh.set_gl_state(depth_test=False, cull_face=self._cull, **_BLEND)
        self._top_line.set_gl_state(depth_test=False, **_BLEND)

        self.freeze()

    def _check_layer(self, layer):
        """
        Raise ValueError unless layer is an integer in 0..layers-1.
        """
        if isinstance(layer, bool) or not isinstance(layer, (int, np.integer)) or not 0 <= layer < self._layers:
            raise ValueError("Layer %r is out of range 0..%d." % (layer, self._layers - 1))

    def layer_visuals(self, layer):
        """
        The mesh and the line visuals that paint a layer, in draw order (one per bucket that has shapes there).

        :return: (list of MeshVisual, list of LineVisual)
        """
        buckets = sorted(self._buckets.values(), key=lambda b: b.seq)
        return ([b.meshes[layer] for b in buckets if layer in b.meshes],
                [b.lines[layer] for b in buckets if layer in b.lines])

    def mark_dirty(self, bucket=None):
        """
        The shapes of a bucket (all buckets if None) changed outside of the collection: the next update uploads them.
        """
        for bid, b in list(self._buckets.items()):
            if bucket is None or bid == bucket:
                b.dirty = True
        if self._top_keys:
            self._top_dirty = True
        self._dirty = True

    def _mark_key(self, key):
        """
        The shape changed: the next update uploads the bucket of the shape (and the overlay if it is on top).
        """
        b = self._buckets.get(self._key_bucket.get(key))
        if b is not None:
            b.dirty = True
        if key in self._top_keys:
            self._top_dirty = True
        self._dirty = True

    def _attach(self, keys, bucket):
        """
        Puts new shapes in a bucket. A bucket that was emptied is a new bucket: it draws after the other buckets.
        """
        with self.key_lock:
            b = self._buckets.get(bucket)
            if b is None:
                b = self._buckets[bucket] = _Bucket()
            for k in keys:
                b.keys[k] = True
                self._key_bucket[k] = bucket
            b.dirty = True
        self._dirty = True

    def set_rectangle(self, start, end, color, face_color):
        """Replace selection contents without rebuilding collection buffers on each move."""
        if self.data:
            self.clear(update=True)
        if self._rectangle is None:
            if isinstance(self, VisualNode):
                self._rectangle = Rectangle(self._line_width, parent=self)
            else:
                self._rectangle = RectangleVisual(self._line_width)
                self.add_subvisual(self._rectangle)
        self._rectangle.set_data(start, end, color, face_color)
        if not self._rectangle.visible:
            self._rectangle.visible = True

    def add_hover(self, bounds, units, color, face_color):
        """Reuse rounded hover geometry and triangulation, bounded to 128 styles/bounds."""
        buffers = _cached_hover_buffers(tuple(bounds), units.upper(), color, face_color)
        with self.key_lock:
            self.last_key += 1
            key = self.last_key
        self.data[key] = buffers.copy()
        self._attach([key], _DEFAULT_BUCKET)
        self.redraw()
        return key

    def add(self, shape=None, color=None, face_color=None, alpha=None, visible=True,
            update=False, layer=1, tolerance=0.001, linewidth=None, bucket=_DEFAULT_BUCKET):
        """
        Adds shape to collection
        :return:
        :param shape: shapely.geometry
            Shapely geometry object
        :param color: str, tuple
            Line/edge color
        :param face_color: str, tuple
            Polygon face color
        :param alpha: str
            Polygon transparency
        :param visible: bool
            Shape visibility
        :param update: bool
            Set True to redraw collection
        :param layer: int
            Layer number. 0 - lowest.
        :param tolerance: float
            Geometry simplifying tolerance
        :param linewidth: int
            Width of the line
        :param bucket: int
            Bucket of the shapes (ShapeGroup id). A change of a bucket uploads only the bucket.
        :return: int
            Index of shape
        """
        self._check_layer(layer)

        # Get new key
        self.key_lock.acquire(True)
        self.last_key += 1
        key = self.last_key
        self.key_lock.release()

        # Prepare data for translation
        self.data[key] = {
            'geometry': shape,
            'color': color,
            'alpha': alpha,
            'face_color': face_color,
            'visible': visible,
            'layer': layer,
            'tolerance': tolerance,
            # the following keys are updated in the _update_shape_buffers() method
            'mesh_vertices': np.empty((0, 2), dtype=np.float32),    # Vertices for mesh
            'mesh_tris': np.empty(0, dtype=np.uint32),              # Faces for mesh
            'mesh_rgba': np.zeros(4, dtype=np.float32),             # Face color of the shape
            'line_pts': np.empty((0, 2), dtype=np.float32),         # Vertices for line
            'line_rgba': np.zeros(4, dtype=np.float32)              # Line color of the shape
        }

        if linewidth:
            self._line_width = linewidth

        # Always process synchronously for individual adds (pool IPC overhead > compute)
        self.data[key] = _update_shape_buffers(self.data[key])

        # Mark buffers as dirty
        self._attach([key], bucket)

        if update:
            self.redraw()   # redraw() waits for pool process end

        return key

    def add_batch(self, shapes_data, layer=1, tolerance=0.001, linewidth=None, visible=True, bucket=_DEFAULT_BUCKET):
        """
        Add multiple shapes in one pool call. Dramatically reduces IPC overhead.

        :param shapes_data: list of dicts, each with keys:
            'shape' (required), 'color', 'face_color', 'alpha', 'layer', 'tolerance'
        :param layer: int - default layer for shapes that don't specify one
        :param tolerance: float - default tolerance for shapes that don't specify one
        :param linewidth: int - line width override
        :param visible: bool - visibility for all shapes in the batch
        :param bucket: int - bucket of the shapes (ShapeGroup id)
        :return: list of int - keys for all added shapes (in same order as shapes_data)
        """
        if not shapes_data:
            return []

        # Validate every effective layer before any state changes (lock, last_key, data, line width)
        for item in shapes_data:
            self._check_layer(item.get('layer', layer))

        if linewidth:
            self._line_width = linewidth

        keys = []
        data_list = []

        self.key_lock.acquire(True)
        for item in shapes_data:
            self.last_key += 1
            key = self.last_key
            keys.append(key)
            self.data[key] = {
                'geometry': item.get('shape'),
                'color': item.get('color'),
                'alpha': item.get('alpha'),
                'face_color': item.get('face_color'),
                'visible': visible,
                'layer': item.get('layer', layer),
                'tolerance': item.get('tolerance', tolerance),
                'mesh_vertices': np.empty((0, 2), dtype=np.float32),
                'mesh_tris': np.empty(0, dtype=np.uint32),
                'mesh_rgba': np.zeros(4, dtype=np.float32),
                'line_pts': np.empty((0, 2), dtype=np.float32),
                'line_rgba': np.zeros(4, dtype=np.float32)
            }
            data_list.append(self.data[key])
        self.key_lock.release()

        if self.fc_options and self.fc_options.get("global_graphic_engine_3d_no_mp") is True:
            # Synchronous mode
            for k, d in zip(keys, data_list):
                self.data[k] = _update_shape_buffers(d)
        else:
            try:
                # ONE pool.map_async call for ALL shapes
                # Pool distributes items across workers automatically
                result = self.pool.map_async(_update_shape_buffers, data_list)
                self._batch_results.append((keys, result))
            except Exception:
                # Fallback: process synchronously
                for k, d in zip(keys, data_list):
                    self.data[k] = _update_shape_buffers(d)

        self._attach(keys, bucket)
        return keys

    def add_copy(self, source, source_key, color=None, face_color=None, linewidth=None, bucket=_DEFAULT_BUCKET):
        """
        Adds a shape that is already in a collection (this one or another one) with new colors, without a new
        simplification and triangulation. The position buffers are shared: no code changes them after
        _update_shape_buffers(). Only the color buffers are new.

        :param source:      ShapeCollectionVisual that holds the shape
        :param source_key:  key of the shape in the source
        :param color:       line color of the copy
        :param face_color:  face color of the copy
        :param linewidth:   width of the lines of this collection
        :param bucket:      bucket of the copy (ShapeGroup id)
        :return:            key of the copy, or None if the source has no buffers for this key (yet)
        """
        src = source.data.get(source_key)
        if src is None or 'line_pts' not in src or source_key in source.results:
            return None

        if linewidth:
            self._line_width = linewidth

        def rgba_of(col, rows):
            # a color is parsed only if the shape has vertices to paint
            if not rows:
                return np.zeros(4, dtype=np.float32)
            rgba = _cached_color_rgba(col) if isinstance(col, str) else Color(col).rgba
            return np.asarray(rgba, dtype=np.float32)

        self.key_lock.acquire(True)
        self.last_key += 1
        key = self.last_key
        self.key_lock.release()

        self.data[key] = {
            'color': color,
            'alpha': src.get('alpha'),
            'face_color': face_color,
            'visible': True,
            'layer': src['layer'],
            'tolerance': src.get('tolerance'),
            'mesh_vertices': src['mesh_vertices'],
            'mesh_tris': src['mesh_tris'],
            'mesh_rgba': rgba_of(face_color, len(src['mesh_tris'])),
            'line_pts': src['line_pts'],
            'line_rgba': rgba_of(color, len(src['line_pts']))
        }

        self._attach([key], bucket)
        return key

    def remove(self, key, update=False):
        """
        Removes shape from collection
        :param key: int
            Shape index to remove
        :param update:
            Set True to redraw collection
        """
        # Remove process result
        self.results_lock.acquire(True)
        if key in list(self.results.copy().keys()):
            del self.results[key]
        self.results_lock.release()

        # Remove data
        if key in self.data:
            del self.data[key]

        # Mark buffers as dirty; a bucket without shapes is deleted, its visuals are removed on the update
        with self.key_lock:
            bucket = self._key_bucket.pop(key, None)
            b = self._buckets.get(bucket)
            if b is not None:
                b.keys.pop(key, None)
                b.dirty = True
                if not b.keys:
                    del self._buckets[bucket]
                    self._dead.append(b)
            if key in self._top_keys:
                self._top_keys.discard(key)
                self._top_dirty = True
        self._dirty = True

        if update:
            self.__update()

    def clear(self, update=False):
        """
        Removes all shapes from collection
        :param update: bool
            Set True to redraw collection
        """
        if self._rectangle is not None and self._rectangle.visible:
            self._rectangle.visible = False
        self.last_key = -1
        self.data.clear()
        self._top_keys.clear()
        del self._top_order[:]

        # Mark buffers as dirty; the visuals of the buckets are removed on the update
        with self.key_lock:
            self._dead.extend(self._buckets.values())
            self._buckets.clear()
            self._key_bucket.clear()
        self._top_dirty = True
        self._dirty = True

        if update:
            self.__update()

    def move_to_top(self, keys):
        """
        Move the shapes to the foreground, above every normal plotting layer.
        The shapes keep their keys and their buffers; there is no new tessellation.

        :param keys:    list of shape keys, in the order to draw them
        :return:        True if the order changed, False if the shapes are already on top
        """
        keys = [k for k in keys if k in self.data]
        if not keys:
            return False

        # Foreground membership matters even when these are already the last shapes.
        key_set = set(keys)
        if self._top_keys == key_set and set(itertools.islice(reversed(self.data), len(keys))) == key_set:
            return False

        # Lock sub-visuals updates; a key that is deleted and set again goes to the end of the dict
        self.update_lock.acquire(True)
        try:
            moved = [(k, self.data.pop(k)) for k in keys]
            self.data.update(moved)
            # the buckets of the old and of the new top shapes are uploaded again
            for k in itertools.chain(self._top_keys, keys):
                self._mark_key(k)
                b = self._buckets.get(self._key_bucket.get(k))
                if k in key_set and b is not None and k in b.keys:
                    del b.keys[k]
                    b.keys[k] = True
            self._top_keys = key_set
            self._top_order = list(keys)
            self._top_dirty = True
        finally:
            self.update_lock.release()

        self._dirty = True
        return True

    def update_visibility(self, state: bool, indexes=None) -> None:
        # Lock sub-visuals updates
        self.update_lock.acquire(True)
        wanted = None if indexes is None else set(indexes)
        for k, data in list(self.data.items()):
            if wanted is None or k in wanted:
                data['visible'] = state
                self._mark_key(k)

        self.update_lock.release()

    def update_color(self, new_mesh_color=None, new_line_color=None, indexes=None):
        """
        Paints the given shapes (all if indexes is None) with new colors. Only the buckets that hold these shapes
        get new color arrays; no vertices are uploaded.
        """
        if new_mesh_color is None and new_line_color is None:
            return

        if not self.data:
            return

        # an empty string means: do not change this color
        mesh_color_rgba = Color(new_mesh_color).rgba if new_mesh_color else None
        line_color_rgba = Color(new_line_color).rgba if new_line_color else None
        if mesh_color_rgba is None and line_color_rgba is None:
            return

        # Lock sub-visuals updates
        self.update_lock.acquire(True)
        try:
            if indexes is None:
                keys = list(self.data)
            else:
                keys = [k for k in set(indexes) if k in self.data]

            touched = set()
            top_touched = False
            for k in keys:
                data = self.data[k]
                if not data['visible'] or 'line_pts' not in data:
                    continue
                changed = False
                if mesh_color_rgba is not None and len(data['mesh_tris']) // 3 != 0:
                    data['face_color'] = new_mesh_color
                    # Invalidate cached rgba
                    data['face_color_rgba'] = mesh_color_rgba
                    data['mesh_rgba'] = np.asarray(mesh_color_rgba, dtype=np.float32)
                    changed = True
                if line_color_rgba is not None and len(data['line_pts']) != 0:
                    data['color'] = new_line_color
                    # Invalidate cached rgba
                    data['color_rgba'] = line_color_rgba
                    data['line_rgba'] = np.asarray(line_color_rgba, dtype=np.float32)
                    changed = True
                if changed:
                    if k in self._top_keys:
                        top_touched = True
                    else:
                        touched.add(self._key_bucket.get(k))

            # A bucket that waits for an update gets the new colors with its next upload
            for bid in touched:
                b = self._buckets.get(bid)
                if b is not None and not b.dirty:
                    self._apply_colors(b.meshes, b.lines, self._gather(list(b.keys), False),
                                       mesh_color_rgba is not None, line_color_rgba is not None)
            if top_touched and not self._top_dirty:
                self._apply_colors({0: self._top_mesh}, {0: self._top_line}, self._gather(self._top_order, True),
                                   mesh_color_rgba is not None, line_color_rgba is not None)
        finally:
            self.update_lock.release()

    def _gather(self, keys, top):
        """
        The visible shapes of the keys, in draw order, grouped by layer.

        :param keys:    shape keys
        :param top:     True: only the shapes of the top overlay, in one group. False: only the other shapes.
        :return:        list (one item per layer) of lists of shape data
        """
        per_layer = [[] for _ in range(1 if top else self._layers)]
        top_keys = self._top_keys
        data = self.data
        for k in keys:
            d = data.get(k)
            if d is None or not d['visible'] or 'line_pts' not in d or (k in top_keys) != top:
                continue
            per_layer[0 if top else d['layer']].append(d)
        return per_layer

    @staticmethod
    def _apply_colors(meshes, lines, per_layer, mesh_colors, line_colors):
        """
        Sets new color arrays on the visuals of a bucket (or of the overlay), the vertices stay on the GPU.
        The arrays have the order of the buffers that __update() made.
        """
        for layer, shapes in enumerate(per_layer):
            mesh = meshes.get(layer)
            if mesh_colors and mesh is not None:
                colors = _concat([np.broadcast_to(d['mesh_rgba'], (len(d['mesh_tris']) // 3, 4))
                                  for d in shapes if _has_mesh(d)], (0, 4), np.float32)
                if len(colors) > 0:
                    mesh._meshdata.set_face_colors(colors=colors)
                    mesh.mesh_data_changed()
            line = lines.get(layer)
            if line_colors and line is not None:
                colors = _concat([np.broadcast_to(d['line_rgba'], (len(d['line_pts']), 4)) for d in shapes],
                                 (0, 4), np.float32)
                if len(colors) > 0:
                    line._color = colors
                    line._changed['color'] = True
                    line.update()

    def _layer_visual(self, bucket, kind, layer):
        """
        The mesh (kind 0) or line (kind 1) visual of a bucket for a layer; made and put in the scene if it is missing.
        """
        store = bucket.lines if kind else bucket.meshes
        visual = store.get(layer)
        if visual is None:
            if kind:
                visual = LineVisual(antialias=True)
                visual.set_gl_state(**_BLEND)
            else:
                visual = MeshVisual()
                visual.set_gl_state(polygon_offset_fill=True, polygon_offset=(1, 1), cull_face=self._cull, **_BLEND)
            store[layer] = visual
            self._visual_rank[id(visual)] = (layer, kind, bucket.seq)
            self._rank_changed = True
            self.add_subvisual(visual)
        return visual

    def _drop_visual(self, bucket, kind, layer):
        visual = (bucket.lines if kind else bucket.meshes).pop(layer, None)
        if visual is not None:
            self.remove_subvisual(visual)
            del self._visual_rank[id(visual)]

    def _upload(self, mesh, line, shapes, bucket, layer):
        """
        Merges the buffers of the shapes of one layer and sets them on the visuals of the bucket.

        :param mesh, line:  the visuals of the overlay, or None to get (and remove if not needed) the visuals of
                            the bucket for the layer
        """
        line_pts_chunks = []
        line_colors_chunks = []
        mesh_verts_chunks = []
        mesh_tris_chunks = []
        mesh_colors_chunks = []

        # mesh_tris contains triangle indices into mesh_vertices.
        # When merging multiple shapes, indices must be offset by the
        # cumulative vertex count of all previously merged shapes.
        vert_count = 0

        for data in shapes:
            line_pts_chunks.append(data['line_pts'])
            # one color per shape, repeated for every vertex (a view, copied by np.concatenate)
            line_colors_chunks.append(np.broadcast_to(data['line_rgba'], (len(data['line_pts']), 4)))

            if _has_mesh(data):
                mesh_tris_chunks.append(data['mesh_tris'] + vert_count)
                mesh_verts_chunks.append(data['mesh_vertices'])
                mesh_colors_chunks.append(np.broadcast_to(data['mesh_rgba'], (len(data['mesh_tris']) // 3, 4)))
                vert_count += len(data['mesh_vertices'])

        line_pts = _concat(line_pts_chunks, (0, 2), np.float32)
        line_colors = _concat(line_colors_chunks, (0, 4), np.float32)
        mesh_vertices = _concat(mesh_verts_chunks, (0, 2), np.float32)
        mesh_tris = _concat(mesh_tris_chunks, (0,), np.uint32)
        mesh_colors = _concat(mesh_colors_chunks, (0, 4), np.float32)

        # Updating mesh
        if mesh is None:
            if len(mesh_vertices) > 0:
                mesh = self._layer_visual(bucket, 0, layer)
            else:
                self._drop_visual(bucket, 0, layer)
        if mesh is not None:
            mesh.visible = len(mesh_vertices) > 0
            if len(mesh_vertices) > 0:
                mesh.set_data(
                    vertices=mesh_vertices,
                    faces=mesh_tris.reshape((-1, 3)),
                    face_colors=mesh_colors
                )
            else:
                mesh.set_data()
            mesh._bounds_changed()

        # Updating line
        if line is None:
            if len(line_pts) > 0:
                line = self._layer_visual(bucket, 1, layer)
            else:
                self._drop_visual(bucket, 1, layer)
        if line is not None:
            if len(line_pts) > 0:
                line.visible = True
                line.set_data(
                    pos=line_pts,
                    color=line_colors,
                    width=self._line_width,
                    connect='segments')
            else:
                line.visible = False
            line._bounds_changed()

    def __update(self):
        """
        Merges the internal buffers of the changed buckets, sets data to their visuals, redraws collection on scene.
        A bucket that did not change is not touched.
        """
        # Skip if nothing has changed
        if not self._dirty:
            return

        # Lock sub-visuals updates
        self.update_lock.acquire(True)
        try:
            # Flags are cleared before the buffers are read: a change from another thread during the update marks
            # its bucket again and is not lost
            self._dirty = False

            if self._line_width != self._built_width:
                # the width is the same for all the lines of the collection
                self._built_width = self._line_width
                for b in list(self._buckets.values()):
                    b.dirty = True
                self._top_dirty = True

            # Remove the visuals of the buckets that are empty
            dead, self._dead = self._dead, []
            for b in dead:
                for layer in list(b.meshes):
                    self._drop_visual(b, 0, layer)
                for layer in list(b.lines):
                    self._drop_visual(b, 1, layer)

            # Set GPU state once, outside the loops (Step 1a optimization)
            set_state(polygon_offset_fill=False)

            for b in sorted(list(self._buckets.values()), key=lambda x: x.seq):
                if not b.dirty:
                    continue
                b.dirty = False
                per_layer = self._gather(list(b.keys), False)
                for layer in range(self._layers):
                    self._upload(None, None, per_layer[layer], b, layer)

            if self._top_dirty:
                self._top_dirty = False
                self._upload(self._top_mesh, self._top_line, self._gather(self._top_order, True)[0], None, None)

            if self._rank_changed:
                self._rank_changed = False
                last = (self._layers + 1, 0, 0)     # e.g. the selection rectangle
                # one slice assignment: list.sort() empties the list while it sorts, and the GUI thread can draw then
                self._subvisuals[:] = sorted(self._subvisuals, key=lambda v: self._visual_rank.get(id(v), last))

            self._bounds_changed()
        except Exception:
            # try again with everything on the next update
            self.mark_dirty()
            self._top_dirty = True
            raise
        finally:
            self.update_lock.release()

    def _collect_results(self, indexes=None):
        """
        Stores the finished (or waits for the pending) process pool results in self.data.

        :param indexes: shape keys to get the single-shape (add()) results for; all if empty
        :return:        True if any data was replaced
        """
        # Only one thread can update data
        self.results_lock.acquire(True)

        results_collected = False

        # --- Collect batch results (Step 3c optimization) ---
        for batch_keys, batch_result in self._batch_results:
            try:
                batch_result.wait()
                batch_data = batch_result.get()
                for k, r in zip(batch_keys, batch_data):
                    if k in self.data:
                        self.data[k] = r
                        self._mark_key(k)
                        results_collected = True
            except Exception as e:
                print("VisPyVisuals.ShapeCollectionVisual.redraw() --> Batch error = %s" % str(e))

        self._batch_results.clear()
        # --- End batch results collection ---

        # Existing per-shape result collection (backward compat with add())
        for i in list(self.data.keys()) if not indexes else indexes:
            if i in list(self.results.keys()):
                try:
                    self.results[i].wait()                                  # Wait for process results
                    if i in self.data:
                        self.data[i] = self.results[i].get()[0]             # Store translated data
                        del self.results[i]
                        self._mark_key(i)
                        results_collected = True
                except Exception as e:
                    print("VisPyVisuals.ShapeCollectionVisual.redraw() --> Data error = %s. Indexes = %s" %
                          (str(e), str(indexes)))

        self.results_lock.release()
        return results_collected

    def transform_keys(self, keys, matrix, update=True):
        """
        Applies an affine transform to the already triangulated shapes, by mapping the stored vertex arrays.
        There is no new simplification and triangulation.

        :param keys:    shape keys to transform
        :param matrix:  shapely 6-tuple (a, b, d, e, xoff, yoff): x' = a*x + b*y + xoff; y' = d*x + e*y + yoff
        :param update:  True to redraw the collection
        :return:        True if done. False if a shape has no buffers (yet) or is not a plain buffer shape; nothing
                        is changed then and the caller has to plot again.
        """
        a, b, d, e, xoff, yoff = (float(v) for v in matrix)

        # pool results of the keys (also of the other keys: same wait as in redraw())
        self._collect_results(keys)

        data = self.data
        keys = [k for k in keys if k in data]
        for k in keys:
            if 'geometry' in data[k] or k in self.results:
                return False

        # The position arrays can be shared with other keys (add_copy()): they are never changed in place.
        # Every key gets new arrays; the buffers of all the keys are mapped by ONE matrix multiplication.
        flip = (a * e - b * d) < 0          # mirror: the winding of the triangles is reversed (backface culling)

        def _map(field):
            arrays = [data[k][field] for k in keys]
            lens = np.fromiter((len(x) for x in arrays), dtype=np.int64, count=len(arrays))
            total = int(lens.sum())
            if total == 0:
                return None, lens
            pts = np.concatenate(arrays).astype(np.float64, copy=False)
            out = np.empty((total, 2), dtype=np.float32)
            out[:, 0] = pts[:, 0] * a + pts[:, 1] * b + xoff
            out[:, 1] = pts[:, 0] * d + pts[:, 1] * e + yoff
            return out, lens

        new_line, line_lens = _map('line_pts')
        new_mesh, mesh_lens = _map('mesh_vertices')

        new_tris = None
        tri_lens = None
        if flip:
            tri_arrays = [data[k]['mesh_tris'] for k in keys]
            tri_lens = np.fromiter((len(x) for x in tri_arrays), dtype=np.int64, count=len(tri_arrays))
            if int(tri_lens.sum()):
                all_tris = np.concatenate(tri_arrays).reshape(-1, 3)
                new_tris = np.ascontiguousarray(all_tris[:, (0, 2, 1)]).reshape(-1)

        def _split(arr, lens):
            if arr is None:
                return None
            return np.split(arr, np.cumsum(lens)[:-1])

        line_parts = _split(new_line, line_lens)
        mesh_parts = _split(new_mesh, mesh_lens)
        tri_parts = _split(new_tris, tri_lens) if flip else None

        self.update_lock.acquire(True)
        try:
            for i, k in enumerate(keys):
                dk = data[k]
                if line_parts is not None and line_lens[i]:
                    dk['line_pts'] = line_parts[i]
                if mesh_parts is not None and mesh_lens[i]:
                    dk['mesh_vertices'] = mesh_parts[i]
                if tri_parts is not None and tri_lens[i]:
                    dk['mesh_tris'] = tri_parts[i]
                self._mark_key(k)
        finally:
            self.update_lock.release()

        if update:
            self.__update()
        return True

    def redraw(self, indexes=None, update_colors=None):
        """
        Redraws collection
        :param indexes:     list
            Shape indexes to get from process pool
        :param update_colors:
        """
        # Mark dirty if pool results were collected (data changed)
        self._collect_results(indexes)

        if update_colors is None or update_colors is False:
            self.__update()
        else:
            try:
                self.update_color(
                    new_mesh_color=update_colors[0],
                    new_line_color=update_colors[1],
                    indexes=indexes
                )
            except Exception as e:
                print("VisPyVisuals.ShapeCollectionVisual.redraw() --> Update colors error = %s." % str(e))

    def lock_updates(self):
        self.update_lock.acquire(True)

    def unlock_updates(self):
        self.update_lock.release()


class GridLinesVisual(VisPyGridLinesVisual):
    """Grid with a stable ray-plane intersection at high zoom and oblique angles."""

    _shaders = dict(VisPyGridLinesVisual._shaders, fragment="""
        uniform vec2 image_size;
        uniform int method;
        varying vec2 v_texcoord;

        void main() {
            vec2 texcoord = v_texcoord;
            if (method == 1) {
                vec4 origin = $transform(vec4(v_texcoord, 0, 1));
                // Transform a direction, not a second point half a depth range away.
                // Subtracting those distant points loses the small grid coordinates.
                vec4 direction = $transform(vec4(0, 0, 1, 0));
                if (abs(direction.z) <= 1e-6 * length(direction.xyz)) {
                    discard;
                }
                vec4 point = origin - direction * (origin.z / direction.z);
                texcoord = point.xy / (point.w * image_size);
            }
            gl_FragColor = $color_transform($get_data(texcoord));
        }
    """)

    def __init__(self, scale=(1, 1), color='w', **kwargs):
        super(GridLinesVisual, self).__init__(scale=scale, color=color, **kwargs)
        # Use the actual projected plane footprint, not a constant-depth slice.
        self._grid_color_fn = Function(_GRID_COLOR.replace(
            'vec2 px = vec2(abs(dx.x) + abs(dy.x), abs(dx.y) + abs(dy.y));',
            'vec2 px = fwidth(pos) * $pixel_scale;'
        ))
        self._grid_color_fn['color'] = Color(color).rgba
        self._grid_color_fn['scale'] = scale
        self.shared_program.frag['get_data'] = self._grid_color_fn

    def _prepare_transforms(self, view):
        if view.transforms.canvas is not None:
            self._grid_color_fn['pixel_scale'] = view.transforms.canvas.pixel_scale
        super(GridLinesVisual, self)._prepare_transforms(view)


class TextGroup(object):
    def __init__(self, collection):
        self._collection = collection
        self._index = None
        self._visible = None

    def set(self, **kwargs):
        """
        Adds text to collection and store index
        :param kwargs: keyword arguments
            Arguments for TextCollection.add function
        """
        self._index = self._collection.add(**kwargs)

    def clear(self, update=False):
        """
        Removes text from collection, clear index
        :param update: bool
            Set True to redraw collection
        """

        if self._index is not None:
            self._collection.remove(self._index, False)
            self._index = None

        if update:
            self._collection.redraw()

    def redraw(self):
        """
        Redraws text collection
        """
        self._collection.redraw()

    @property
    def visible(self):
        """
        Visibility of group
        :return: bool
        """
        return self._visible

    @visible.setter
    def visible(self, value):
        """
        Visibility of group
        :param value: bool
        """
        self._visible = value
        if self._index:
            try:
                self._collection.data[self._index]['visible'] = value
            except KeyError as e:
                print("VisPyVisuals.TextGroup.visible --> KeyError --> %s" % str(e))
                pass
            self._collection.redraw()


class TextCollectionVisual(TextVisual):

    def __init__(self, **kwargs):
        """
        Represents collection of shapes to draw on VisPy scene
        :param kwargs: keyword arguments
            Arguments to pass for TextVisual
        """
        self.data = {}
        self.last_key = -1
        self.lock = threading.Lock()
        self.method = 'gpu'
        self._annotation_scale = None
        super(TextCollectionVisual, self).__init__(**kwargs)

        self.freeze()

    def _prepare_draw(self, view):
        result = super(TextCollectionVisual, self)._prepare_draw(view)
        if result is False:
            return False

        transform = view.transforms.get_transform('visual', 'document')
        points = transform.map([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
        points = points[:, :2] / points[:, 3:4]
        # The largest projected scale follows zoom without depending on camera rotation.
        scale = np.linalg.norm(points[1:] - points[0], ord=2)
        if np.isfinite(scale) and scale > 0:
            if self._annotation_scale is None:
                self._annotation_scale = scale
            zoom = min(1.0, scale / self._annotation_scale)
            self.shared_program['u_npix'] = self.font_size / 72. * self.transforms.dpi * zoom

        return result

    def add(self, text, pos, visible=True, update=True, font_size=9, color='black'):
        """
        Adds array of text to collection
        :param text: list
            Array of strings ['str1', 'str2', ... ]
        :param pos: list
            Array of string positions   [(0, 0), (10, 10), ... ]
        :param visible: bool
        |   Set True to make it visible
        :param update: bool
            Set True to redraw collection
        :param font_size: int
            Set font size to redraw collection
        :param color: string
            Set font color to redraw collection
        :return: int
            Index of array
        """
        # Get new key
        self.lock.acquire(True)
        self.last_key += 1
        key = self.last_key
        self.lock.release()

        # Prepare data for translation
        self.data[key] = {'text': text, 'pos': pos, 'visible': visible, 'font_size': font_size, 'color': color}

        if update:
            self.redraw()

        return key

    def remove(self, key, update=False):
        """
        Removes shape from collection
        :param key: int
            Shape index to remove
        :param update:
            Set True to redraw collection
        """
        del self.data[key]

        if update:
            self.__update()

    def clear(self, update=False):
        """
        Removes all shapes from collection
        :param update: bool
            Set True to redraw collection
        """
        self.data.clear()
        if update:
            self.__update()

    def __update(self):
        """
        Merges internal buffers, sets data to visuals, redraws collection on scene
        """
        labels = []
        pos = []
        font_s = 9
        color = 'black'

        # Merge buffers
        for data in list(self.data.values()):
            if data['visible']:
                try:
                    labels += data['text']
                    pos += data['pos']
                    font_s = data['font_size']
                    color = data['color']
                except Exception as e:
                    print("VisPyVisuals.TextCollectionVisual._update() --> Data error. %s" % str(e))

        # Updating text
        if len(labels) > 0:
            self.text = labels
            self.pos = pos
            self.font_size = font_s
            self.color = color
        else:
            self.text = None
            self.pos = (0, 0)

        self._bounds_changed()

    def redraw(self):
        """
        Redraws collection
        """
        self.__update()


class CursorTextVisual(TextVisual):
    """Avoid rebuilding editor cursor glyphs when text and anchors haven't changed."""

    @TextVisual.text.setter
    def text(self, value):
        value = [] if value is None else value
        if getattr(self, '_text', None) != value:
            TextVisual.text.fset(self, value)

    @TextVisual.anchors.setter
    def anchors(self, value):
        if getattr(self, '_anchors', None) != value:
            TextVisual.anchors.fset(self, value)


class CursorVisual(MarkersVisual):
    """Keep marker styling and its buffer bindings when only the cursor moves."""

    def __init__(self, *args, **kwargs):
        self._cursor_style = None
        super().__init__(*args, **kwargs)

    def set_data(self, pos=None, size=10., edge_width=None, edge_width_rel=None,
                 edge_color='black', face_color='white', symbol='o'):
        style = []
        for value in (size, edge_width, edge_width_rel,
                      getattr(edge_color, 'rgba', edge_color),
                      getattr(face_color, 'rgba', face_color), symbol):
            if isinstance(value, (np.ndarray, list, tuple)):
                array = np.asarray(value)
                value = (array.shape, array.dtype, array.tobytes())
            style.append(value)
        style = tuple(style)
        if isinstance(pos, np.ndarray) and pos.shape == (1, 2) and \
                self._data is not None and len(self._data) == 1 and \
                style == self._cursor_style:
            position = pos.astype(np.float32, copy=False)[0]
            current = self._data['a_position'][0]
            if current[0] != position[0] or current[1] != position[1] or current[2] != 0:
                current[:2] = position
                current[2] = 0
                self._vbo.set_data(self._data)
                self.events.data_updated()
                self.update()
            return

        super().set_data(pos=pos, size=size, edge_width=edge_width, edge_width_rel=edge_width_rel,
                         edge_color=edge_color, face_color=face_color, symbol=symbol)
        self._cursor_style = style


# Add 'enabled' property to visual nodes
def create_fast_node(subclass):
    # Create a new subclass of Node.

    # Decide on new class name
    clsname = subclass.__name__
    if not (clsname.endswith('Visual') and issubclass(subclass, visuals.BaseVisual)):
        raise RuntimeError('Class "%s" must end with Visual, and must '
                           'subclass BaseVisual' % clsname)
    clsname = clsname[:-6]

    # Generate new docstring based on visual docstring
    try:
        doc = generate_docstring(subclass, clsname)
    except Exception:
        # If parsing fails, just return the original Visual docstring
        doc = subclass.__doc__

    # New __init__ method
    def __init__(self, *args, **kwargs):
        parent = kwargs.pop('parent', None)
        name = kwargs.pop('name', None)
        self.name = name  # to allow __str__ before Node.__init__
        self._visual_superclass = subclass

        # parent: property,
        # _parent: attribute of Node class
        # __parent: attribute of fast_node class
        self.__parent = parent
        self._enabled = False

        subclass.__init__(self, *args, **kwargs)
        self.unfreeze()
        VisualNode.__init__(self, parent=parent, name=name)
        self.freeze()

    # Create new class
    cls = type(
        clsname, (VisualNode, subclass), {'__init__': __init__, '__doc__': doc}
    )

    # 'Enabled' property clears/restores 'parent' property of Node class
    # Scene will be painted quicker than when using 'visible' property
    def get_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        if enabled:
            self.parent = self.__parent                 # Restore parent
        else:
            if self.parent:                             # Store parent
                self.__parent = self.parent
            self.parent = None

    cls.enabled = property(get_enabled, set_enabled)

    return cls


ShapeCollection = create_fast_node(ShapeCollectionVisual)
Rectangle = create_fast_node(RectangleVisual)
GridLines = create_fast_node(GridLinesVisual)
TextCollection = create_fast_node(TextCollectionVisual)
Cursor = create_fast_node(CursorVisual)
CursorText = create_fast_node(CursorTextVisual)
