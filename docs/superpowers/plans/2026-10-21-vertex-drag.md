# Vertex Dragging in the Geometry Editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the Select tool of the Geometry Editor, the user drags grips to move, insert and remove the vertices of
1 selected shape (all rings, multipart shapes included). Each drag is 1 Undo step.

**Architecture:** Pure Shapely functions in `appEditors/vertex_ops.py` (no Qt, no editor). A `VertexGrips` class in
`appEditors/vertex_grips.py` holds the grip and drag state; the editor keeps 1 instance as `self.vertex_grips`.
`AppGeoEditor.apply_vertex_edit` uses `vertex_ops`, so the drag and the Edit vertices dialog share 1 path and 1 Undo
system. 3 short hooks in the mouse handlers send the events to `vertex_grips` first.

**Tech Stack:** Python 3.11+, PyQt6, VisPy, Shapely 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-vertex-drag-design.md`

---

## Rules for the worker

- Run Python only with the venv, from PowerShell: `.venv\Scripts\python.exe -m pytest ...`. Git Bash cannot start
  the venv Python, and the system Python has no `rasterio`.
- **Do not commit.** `appEditors/appGeoEditor.py` and `CHANGELOG.md` hold other uncommitted work of the user. The
  user commits at the end.
- Do not add mixins. Do not add `Co-Authored-By` lines anywhere.
- Run only the tests that each task names. The full suite is slow.

## Deviations from the spec (decided while planning)

1. `check_vertex_result(geom, address)` takes the edited geometry and the address, not `(old, new)`. It checks only
   the edited part and ring, so a shape with an old invalid part elsewhere can still be edited.
2. The spec moves the "inside the segment" rule for insert to the dialog only. The plan keeps the rule in
   `apply_vertex_edit` behind a new argument `on_segment=True` (the dialog path). `VertexGrips` passes
   `on_segment=False`. This keeps the current tests of the dialog unchanged.
3. `apply_vertex_edit` keeps its `index` argument. It accepts a plain `int` (the current calls and tests) or a
   `(part, ring, index)` tuple. A plain `int` on a multipart shape fails with a message that names `LineString`.
4. Corner snap: if the snapped point is the start point of the dragged vertex, `VertexGrips` uses the raw cursor
   point (no grid snap for that 1 move event).

## File map

| File | Status | Responsibility |
|---|---|---|
| `appEditors/vertex_ops.py` | create | grips list, address rules, edit, result check, contrast color |
| `appEditors/vertex_grips.py` | create | `VertexGrips`: grip display, hit test, drag, preview, commit call |
| `appEditors/appGeoEditor.py` | modify | `apply_vertex_edit`, `vertex_edit_target`, dialog, hooks, `__init__`, `deactivate`, `on_tool_select`, `plot_all`, `plot_changes` |
| `tests/test_vertex_ops.py` | create | pure function tests |
| `tests/test_vertex_grips.py` | create | `VertexGrips` with a fake editor |
| `tests/test_geo_editor_vertex_drag.py` | create | real `apply_vertex_edit` + history, and the mouse hooks |
| `tests/test_geo_editor_vertices.py` | keep | must still pass |
| `CHANGELOG.md` | modify | 1 entry |

---

### Task 1: `vertex_ops.py` — grips, address, edit and result check

**Files:**
- Create: `appEditors/vertex_ops.py`
- Test: `tests/test_vertex_ops.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vertex_ops.py`:

```python
"""Pure vertex edits addressed as (part, ring, index). No Qt."""
import pytest
from shapely.geometry import LineString, LinearRing, Polygon, MultiLineString, MultiPolygon, box

from appEditors.vertex_ops import (vertex_grips, vertex_address, ring_after_edit, edit_vertex, check_vertex_result,
                                   contrast_color)

SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]
HOLE = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]


def kinds(grips, kind):
    return [(address, point) for k, address, point in grips if k == kind]


def test_grips_of_open_line():
    grips = vertex_grips(LineString([(0, 0), (2, 0), (2, 2)]))
    assert kinds(grips, 'vertex') == [((0, 0, 0), (0, 0)), ((0, 0, 1), (2, 0)), ((0, 0, 2), (2, 2))]
    assert kinds(grips, 'mid') == [((0, 0, 0), (1, 0)), ((0, 0, 1), (2, 1))]


@pytest.mark.parametrize('factory', [LinearRing, Polygon])
def test_closing_coordinate_has_no_own_grip(factory):
    grips = vertex_grips(factory(SQUARE))
    assert [address for address, __ in kinds(grips, 'vertex')] == [(0, 0, i) for i in range(4)]
    assert [address for address, __ in kinds(grips, 'mid')] == [(0, 0, i) for i in range(4)]
    assert kinds(grips, 'mid')[3] == ((0, 0, 3), (0, 2))


def test_grips_of_polygon_hole_and_multipolygon():
    grips = vertex_grips(MultiPolygon([Polygon(SQUARE, [HOLE]), box(10, 10, 11, 11)]))
    rings = {address[:2] for address, __ in kinds(grips, 'vertex')}
    assert rings == {(0, 0), (0, 1), (1, 0)}


def test_vertex_address():
    assert vertex_address(LineString([(0, 0), (1, 0)]), 1) == (0, 0, 1)
    assert vertex_address(LineString([(0, 0), (1, 0)]), (0, 0, 1)) == (0, 0, 1)
    with pytest.raises(ValueError, match='LineString'):
        vertex_address(MultiLineString([[(0, 0), (1, 0)], [(2, 0), (3, 0)]]), 0)


@pytest.mark.parametrize('action,address,point,expected', [
    ('move', (0, 0, 1), (2, 1), [(0, 0), (2, 1), (4, 0)]),
    ('insert', (0, 0, 0), (1, 0), [(0, 0), (1, 0), (2, 0), (4, 0)]),
    ('remove', (0, 0, 1), None, [(0, 0), (4, 0)]),
])
def test_edit_open_line(action, address, point, expected):
    result = edit_vertex(LineString([(0, 0), (2, 0), (4, 0)]), action, address, point)
    assert list(result.coords) == expected


@pytest.mark.parametrize('index', [0, 4])
def test_move_vertex_zero_or_closing_alias_moves_both_ends(index):
    result = edit_vertex(Polygon(SQUARE), 'move', (0, 0, index), (-1, -1))
    coords = list(result.exterior.coords)
    assert coords[0] == coords[-1] == (-1, -1) and len(coords) == 5


def test_edit_hole_keeps_exterior():
    result = edit_vertex(Polygon(SQUARE, [HOLE]), 'move', (0, 1, 0), (1.5, 0.5))
    assert list(result.exterior.coords) == SQUARE
    assert list(result.interiors[0].coords)[0] == (1.5, 0.5)


def test_edit_one_part_keeps_other_parts():
    multi = MultiPolygon([box(0, 0, 1, 1), box(1, 1, 2, 2)])
    result = edit_vertex(multi, 'move', (0, 0, 1), (0.9, 0.9))
    assert isinstance(result, MultiPolygon)
    assert result.geoms[1].equals_exact(multi.geoms[1], 0.0)
    assert (0.9, 0.9) in list(result.geoms[0].exterior.coords)


def test_insert_off_segment_needs_on_segment_false():
    line = LineString([(0, 0), (2, 0)])
    with pytest.raises(ValueError):
        edit_vertex(line, 'insert', (0, 0, 0), (1, 1), on_segment=True)
    assert list(edit_vertex(line, 'insert', (0, 0, 0), (1, 1)).coords) == [(0, 0), (1, 1), (2, 0)]


@pytest.mark.parametrize('geometry,action,address,point', [
    (LineString([(0, 0), (1, 0)]), 'remove', (0, 0, 0), None),
    (Polygon([(0, 0), (4, 0), (0, 4)]), 'remove', (0, 0, 0), None),
    (LineString([(0, 0), (2, 0)]), 'move', (0, 0, 0), (float('nan'), 0)),
    (LineString([(0, 0), (2, 0)]), 'move', (0, 0, 0), (1,)),
    (LineString([(0, 0), (2, 0)]), 'move', (0, 0, 2), (1, 0)),
    (LineString([(0, 0), (2, 0)]), 'move', (1, 0, 0), (1, 0)),
    (LineString([(0, 0), (2, 0)]), 'move', (0, 1, 0), (1, 0)),
    (LineString([(0, 0), (2, 0)]), 'move', (0, 0, 0.5), (1, 0)),
    (LineString([(0, 0), (2, 0)]), 'insert', (0, 0, 1), (1, 0)),
    (LineString([(0, 0), (2, 0)]), 'unknown', (0, 0, 0), (1, 0)),
    (box(0, 0, 4, 4), 'move', (0, 0, 1), (4, 0)),
    (LineString([(0, 0, 1), (2, 0, 1)]), 'move', (0, 0, 0), (1, 1)),
])
def test_bad_edits_raise(geometry, action, address, point):
    with pytest.raises(ValueError):
        edit_vertex(geometry, action, address, point)


def test_ring_after_edit_does_not_check_the_result():
    coords = ring_after_edit(box(0, 0, 4, 4), 'move', (0, 0, 1), (4, 0))
    assert coords[0] == coords[-1]
    assert (4, 0) in coords


@pytest.mark.parametrize('geometry', [
    LineString([(0, 0), (2, 0), (2, 2), (1, -1)]),
    Polygon(SQUARE, [[(3, 3), (5, 3), (5, 5), (3, 5)]]),
])
def test_check_vertex_result_rejects_invalid(geometry):
    with pytest.raises(ValueError):
        check_vertex_result(geometry, (0, 0, 0))


def test_check_vertex_result_ignores_other_parts():
    crossing = MultiLineString([[(0, 0), (2, 2)], [(0, 2), (2, 0)], [(5, 0), (6, 0)]])
    check_vertex_result(crossing, (2, 0, 0))


def test_contrast_color():
    assert contrast_color('#FF8000FF', ['#00000080', '#0000FF80', '#FFFFFF']) == '#FF8000FF'
    assert contrast_color('#FF0000FF', ['#F01010FF']) == '#00FFFFFF'
    assert contrast_color('#FF0000FF', ['', None, 'bad']) == '#FF0000FF'
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py -q`
Expected: error `ModuleNotFoundError: No module named 'appEditors.vertex_ops'`.

- [ ] **Step 3: Write `appEditors/vertex_ops.py`**

```python
"""
Vertex edits on Shapely geometry, addressed as (part, ring, index).

No Qt and no editor code: the Geometry Editor uses these functions now, the Gerber Editor later.
part: 0 for a single geometry, else the index in .geoms. ring: 0 for a line or a polygon exterior, 1+ for the holes.
index: the vertex in the full coordinate list of the ring; the closing coordinate of a closed ring is an alias of 0.
"""
import math
import gettext
import builtins

from shapely import LineString, LinearRing, Polygon, MultiLineString, MultiPolygon, Point

import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

SUPPORTED_TYPES = (LineString, LinearRing, Polygon, MultiLineString, MultiPolygon)
# RGB distance (0 - 441) under which 2 colors are too near to tell apart on the canvas
COLOR_CLASH_DIST = 100


def parts_of(geom):
    return list(geom.geoms) if isinstance(geom, (MultiLineString, MultiPolygon)) else [geom]


def rings_of(part):
    return [part.exterior, *part.interiors] if isinstance(part, Polygon) else [part]


def vertex_grips(geom):
    """[(kind, address, (x, y))]: 1 'vertex' grip for each vertex, 1 'mid' grip for each segment."""
    grips = []
    for part_nr, part in enumerate(parts_of(geom)):
        for ring_nr, ring in enumerate(rings_of(part)):
            coords = [tuple(coord[:2]) for coord in ring.coords]
            closed = len(coords) > 1 and coords[0] == coords[-1]
            vertices = coords[:-1] if closed else coords
            grips.extend(('vertex', (part_nr, ring_nr, index), point) for index, point in enumerate(vertices))
            for index, (a, b) in enumerate(zip(coords, coords[1:])):
                grips.append(('mid', (part_nr, ring_nr, index), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
    return grips


def vertex_address(geom, index):
    """A plain index edits a single contour; multipart shapes need a (part, ring, index) address."""
    if isinstance(index, tuple):
        return index
    if isinstance(geom, (MultiLineString, MultiPolygon)):
        raise ValueError(_("A plain vertex index edits one LineString, LinearRing or polygon exterior.\n"
                           "Multipart shapes need a part and a ring index."))
    return 0, 0, index


def ring_after_edit(geom, action, address, point=None, on_segment=False):
    """The full coordinate list of the edited ring. Checks the input, not the result (the preview draws it)."""
    if action not in ('move', 'insert', 'remove'):
        raise ValueError(_("Choose move, insert or remove."))
    if not isinstance(geom, SUPPORTED_TYPES) or geom.is_empty:
        raise ValueError(_("Vertex editing supports LineString, LinearRing, Polygon and their multipart shapes."))
    if geom.has_z:
        raise ValueError(_("Vertex editing supports two-dimensional coordinates only."))
    if len(address) != 3 or any(type(value) is not int for value in address):
        raise ValueError(_("Choose a valid vertex index."))
    part_nr, ring_nr, index = address
    parts = parts_of(geom)
    if not 0 <= part_nr < len(parts):
        raise ValueError(_("Choose a valid part index."))
    rings = rings_of(parts[part_nr])
    if not 0 <= ring_nr < len(rings):
        raise ValueError(_("Choose a valid ring index."))
    coords = [tuple(coord) for coord in rings[ring_nr].coords]
    if not 0 <= index < len(coords):
        raise ValueError(_("Choose a valid vertex index."))
    closed = coords[0] == coords[-1]
    if action != 'remove':
        if point is None or len(point) != 2:
            raise ValueError(_("Enter numeric X and Y coordinates."))
        point = tuple(float(value) for value in point)
        if not all(math.isfinite(value) for value in point):
            raise ValueError(_("Coordinates must be finite numbers."))
    if action == 'insert':
        if index >= len(coords) - 1:
            raise ValueError(_("Choose a segment start index, not the final vertex."))
        if on_segment:
            segment = LineString(coords[index:index + 2])
            candidate = Point(point)
            if (point in coords[index:index + 2] or
                    not 0 < segment.project(candidate) < segment.length or
                    segment.distance(candidate) > 1e-9 * max(1.0, segment.length)):
                raise ValueError(_("The new vertex must lie inside the chosen segment."))
    if closed:
        coords.pop()
        if index == len(coords):
            index = 0  # the duplicated closing coordinate is the first vertex
    if action == 'remove':
        if len(coords) <= (3 if closed else 2):
            raise ValueError(_("Removal would leave too few vertices for a valid contour."))
        del coords[index]
    elif action == 'insert':
        coords.insert(index + 1, point)
    else:
        coords[index] = point
    if closed:
        coords.append(coords[0])
    return coords


def edit_vertex(geom, action, address, point=None, on_segment=False):
    """The new geometry, same type, with only the addressed ring changed."""
    coords = ring_after_edit(geom, action, address, point, on_segment)
    if any(a == b for a, b in zip(coords, coords[1:])):
        raise ValueError(_("The edit would create a zero-length segment."))
    part_nr, ring_nr, __ = address
    parts = parts_of(geom)
    part = parts[part_nr]
    if isinstance(part, Polygon):
        rings = [list(ring.coords) for ring in rings_of(part)]
        rings[ring_nr] = coords
        new_part = Polygon(rings[0], rings[1:])
    else:
        new_part = type(part)(coords)
    if isinstance(geom, (MultiLineString, MultiPolygon)):
        parts[part_nr] = new_part
        return type(geom)(parts)
    return new_part


def check_vertex_result(geom, address):
    """Raise ValueError if the edited part or ring is not valid. The other parts are not checked."""
    part_nr, ring_nr, __ = address
    part = parts_of(geom)[part_nr]
    ring = LineString(rings_of(part)[ring_nr].coords)
    coords = list(ring.coords)
    if (geom.is_empty or not part.is_valid or not ring.is_simple or
            (coords[0] == coords[-1] and not Polygon(coords).is_valid) or
            (isinstance(geom, MultiPolygon) and not geom.is_valid)):
        raise ValueError(_("The edit would create invalid geometry."))


def _rgb(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def contrast_color(preferred, used_colors):
    """preferred ('#RRGGBBAA'), or its opposite color if it is too near one of used_colors."""
    rgb = _rgb(preferred)
    for used in used_colors:
        try:
            near = math.dist(rgb, _rgb(used)) < COLOR_CLASH_DIST
        except (AttributeError, TypeError, ValueError):
            continue
        if near:
            return '#%02X%02X%02X%s' % (255 - rgb[0], 255 - rgb[1], 255 - rgb[2], preferred[7:9])
    return preferred
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py -q`
Expected: all pass. If `test_check_vertex_result_rejects_invalid` fails for the polygon case, look at the hole: it
must cross the exterior (`(3,3)-(5,5)` crosses `(4,0)-(4,4)`), so `part.is_valid` is `False`.

---

### Task 2: `apply_vertex_edit` and `vertex_edit_target` use `vertex_ops`

**Files:**
- Modify: `appEditors/appGeoEditor.py` (`vertex_edit_target` near line 966, `apply_vertex_edit` near line 981, the
  imports near line 40)
- Test: `tests/test_geo_editor_vertex_drag.py` (create), `tests/test_geo_editor_vertices.py` (keep)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_geo_editor_vertex_drag.py`:

```python
"""Vertex edits with an address and vertex drags go through apply_vertex_edit: 1 drag is 1 Undo step."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtWidgets
from shapely.geometry import MultiPolygon, Polygon, box

from appEditors.appGeoEditor import AppGeoEditor
from tests.test_geo_editor_vertices import vertex_editor


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_address_edits_a_hole_with_one_undo_step():
    hole = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
    editor, original = vertex_editor(Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [hole]))
    assert editor.apply_vertex_edit('move', (0, 1, 0), (1.5, 0.5)) != 'fail'
    assert list(editor.selected[0].geo.interiors[0].coords)[0] == (1.5, 0.5)
    assert editor.undo()
    assert editor.selected == [original]


def test_address_edits_one_part_of_a_multipolygon():
    editor, original = vertex_editor(MultiPolygon([box(0, 0, 1, 1), box(3, 3, 4, 4)]))
    assert editor.apply_vertex_edit('move', (1, 0, 0), (4.5, 3)) != 'fail'
    result = editor.selected[0].geo
    assert result.geoms[0].equals_exact(original.geo.geoms[0], 0.0)
    assert (4.5, 3) in list(result.geoms[1].exterior.coords)


def test_insert_off_segment_only_without_the_segment_rule():
    editor, original = vertex_editor(Polygon([(0, 0), (4, 0), (4, 4), (0, 4)]))
    assert editor.apply_vertex_edit('insert', (0, 0, 0), (2, -1)) == 'fail'
    assert editor.apply_vertex_edit('insert', (0, 0, 0), (2, -1), on_segment=False) != 'fail'
    assert (2, -1) in list(editor.selected[0].geo.exterior.coords)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py -q`
Expected: 3 failures (`'fail'` returned, or `TypeError` for `on_segment`).

- [ ] **Step 3: Add the import**

In `appEditors/appGeoEditor.py`, under the line
`from appEditors.editor_corner import corner_point, next_bend_mode, bend_mode_...` (near line 40), add:

```python
from appEditors.vertex_ops import (vertex_address, edit_vertex, check_vertex_result, parts_of, rings_of,
                                   SUPPORTED_TYPES)
```

- [ ] **Step 4: Change `vertex_edit_target`**

Replace the method body (near line 966) with:

```python
    def vertex_edit_target(self, target=None):
        """Vertex editing never guesses a selected contour: exactly 1 selected shape."""
        if len(self.selected) != 1:
            raise ValueError(_("Select exactly one shape to edit vertices."))
        shape = self.selected[0]
        if (target is not None and shape is not target) or id(shape) not in self.storage.indexes:
            raise ValueError(_("The selected shape changed. Reopen the vertex editor."))
        if not isinstance(shape.geo, SUPPORTED_TYPES) or shape.geo.is_empty:
            raise ValueError(_("Vertex editing supports LineString, LinearRing, Polygon and their multipart shapes.\n"
                               "Collections are not supported."))
        if shape.geo.has_z:
            raise ValueError(_("Vertex editing supports two-dimensional coordinates only."))
        return shape
```

- [ ] **Step 5: Change `apply_vertex_edit`**

Replace the method from `@geometry_operation` / `def apply_vertex_edit` down to the line
`result_geo = type(geometry)(coords)` and its validity check (the whole `try` / `except` block) with:

```python
    @geometry_operation
    def apply_vertex_edit(self, action, index, point=None, target=None, on_segment=True):
        """
        Validate a complete replacement before touching storage or recording history.

        :param index:       a vertex index of a single contour, or a (part, ring, index) address
        :param on_segment:  True (the dialog): an inserted vertex must lie inside the chosen segment
        """
        try:
            shape = AppGeoEditor.vertex_edit_target(self, target)
            geometry = shape.geo
            address = vertex_address(geometry, index)
            result_geo = edit_vertex(geometry, action, address, point, on_segment=on_segment)
            check_vertex_result(result_geo, address)
        except (ValueError, TypeError, OverflowError, shapely.errors.GEOSException) as err:
            self.app.inform.emit('[WARNING_NOTCL] %s' % str(err))
            return 'fail'
```

Keep the rest of the method unchanged:

```python
        if result_geo.equals_exact(geometry, 0.0):
            return
        result = DrawToolShape(result_geo)
        result.data = shape.data.copy()
        result.data['bounds'] = result.bounds()
        if self.replace_shapes(removed=[shape], inserted=[result], selected=[result]) == 'fail':
            return 'fail'
        self.build_ui_sig.emit()
        self.plot_changes()
```

- [ ] **Step 6: Run the new and the current tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py -q`
Expected: all pass. `test_unsupported_and_ambiguous_selection_are_explained` passes because the message of
`vertex_address` names `LineString`.

---

### Task 3: `VertexGrips` class

**Files:**
- Create: `appEditors/vertex_grips.py`
- Test: `tests/test_vertex_grips.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vertex_grips.py`:

```python
"""VertexGrips with a fake editor: display, hit test, drag threshold, preview, commit call, cancel."""
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore
from shapely.geometry import LineString, MultiPolygon, box

from appEditors.vertex_grips import VertexGrips, GRIP_COLOR, INVALID_COLOR

NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier
CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
PIXEL = 0.01  # canvas units for each screen pixel: the hit radius is 0.06


class FakeCollection:
    def __init__(self):
        self.items = []
        self.enabled = True

    def add(self, shape=None, **kwargs):
        self.items.append((shape, kwargs))
        return len(self.items)

    def clear(self, update=False):
        self.items = []

    def redraw(self):
        pass


def make_grips(geometry, grid=False, snap=None, busy=False):
    shape = SimpleNamespace(geo=geometry)
    app = SimpleNamespace(grid_status=lambda: grid, inform=SimpleNamespace(emit=Mock()),
                          options={'global_sel_line': '#0000ffbf'},
                          plotcanvas=SimpleNamespace(new_shape_collection=lambda layers: FakeCollection()))
    editor = SimpleNamespace(selected=[shape], active_tool=SimpleNamespace(name='select'), app=app,
                             apply_vertex_edit=Mock(return_value=None), reject_busy=lambda: busy,
                             snap=snap or (lambda x, y: (x, y)), active_snap_type=None,
                             canvas=SimpleNamespace(pixel_size=lambda: PIXEL), tool_shape=FakeCollection(),
                             get_draw_color=lambda: '#00000080', get_sel_color=lambda: '#0000FF80')
    grips = VertexGrips(editor)
    grips.sync()
    return grips, editor, shape


def drag(grips, start, end):
    """Press at the canvas point start, move 20 px, release at the canvas point end."""
    assert grips.press((0, 0), start, NO_MOD)
    grips.move((20, 0), end)
    return grips.release((20, 0), end)


def test_sync_shows_grips_for_one_selected_shape_in_select_tool_only():
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.shape is shape
    assert len(grips.collection().items) == 5  # 3 vertices + 2 midpoints
    editor.active_tool = SimpleNamespace(name='move')
    grips.sync()
    assert grips.shape is None and grips.collection().items == []
    editor.active_tool = SimpleNamespace(name='select')
    editor.selected = [shape, SimpleNamespace(geo=LineString([(5, 5), (6, 6)]))]
    grips.sync()
    assert grips.shape is None


def test_too_many_vertices_shows_no_grips_and_tells_the_user(monkeypatch):
    monkeypatch.setattr('appEditors.vertex_grips.GRIP_LIMIT', 2)
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.shape is None
    editor.app.inform.emit.assert_called_once()
    grips.sync()
    editor.app.inform.emit.assert_called_once()  # no repeat for the same shape


def test_vertex_grip_wins_over_a_nearer_midpoint_grip():
    grips, editor, shape = make_grips(LineString([(0, 0), (0.08, 0)]))
    assert grips.hit((0.03, 0)) == ('vertex', (0, 0, 0), (0, 0))
    assert grips.hit((1, 1)) is None


def test_tie_at_a_touch_point_takes_the_lower_address():
    grips, editor, shape = make_grips(MultiPolygon([box(0, 0, 1, 1), box(1, 1, 2, 2)]))
    kind, address, point = grips.hit((1, 1))
    assert kind == 'vertex' and address[0] == 0 and point == (1, 1)


def test_click_below_the_drag_threshold_changes_nothing():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0), (0, 0), NO_MOD)
    assert grips.move((3, 0), (0.03, 0))
    assert grips.release((3, 0), (0.03, 0))
    editor.apply_vertex_edit.assert_not_called()


def test_drag_of_a_vertex_commits_one_move():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert drag(grips, (2, 0), (2, 1))
    editor.apply_vertex_edit.assert_called_once_with('move', (0, 0, 1), (2.0, 1.0), target=shape,
                                                     on_segment=False)
    assert editor.tool_shape.items == []


def test_drag_of_a_midpoint_inserts_a_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert drag(grips, (1, 0), (1, 1))
    editor.apply_vertex_edit.assert_called_once_with('insert', (0, 0, 0), (1.0, 1.0), target=shape,
                                                     on_segment=False)


def test_ctrl_click_removes_a_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (1, 0), (2, 0)]))
    assert grips.press((0, 0), (1, 0), CTRL)
    assert grips.release((0, 0), (1, 0))
    editor.apply_vertex_edit.assert_called_once_with('remove', (0, 0, 1), target=shape)


def test_cancel_drops_the_drag():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0), (2, 0), NO_MOD)
    grips.move((20, 0), (2, 1))
    assert editor.tool_shape.items
    grips.cancel()
    assert editor.tool_shape.items == []
    assert not grips.release((20, 0), (2, 1))
    editor.apply_vertex_edit.assert_not_called()


def test_preview_color_shows_an_invalid_result():
    grips, editor, shape = make_grips(box(0, 0, 4, 4))
    assert grips.press((0, 0), (4, 0), NO_MOD)
    grips.move((20, 0), (5, 0))
    assert editor.tool_shape.items[-1][1]['color'] == GRIP_COLOR
    grips.move((40, 0), (4, 4))  # onto the next vertex: zero-length segment
    assert editor.tool_shape.items[-1][1]['color'] == INVALID_COLOR


def test_corner_snap_ignores_the_dragged_vertex():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True, snap=lambda x, y: (2, 0))
    editor.active_snap_type = 'corner'
    assert drag(grips, (2, 0), (2.03, 0.04))
    assert editor.apply_vertex_edit.call_args.args[2] == (2.03, 0.04)


def test_grid_snap_applies_during_the_drag():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), grid=True, snap=lambda x, y: (3, 1))
    editor.active_snap_type = 'grid'
    assert drag(grips, (2, 0), (2.9, 1.1))
    assert editor.apply_vertex_edit.call_args.args[2] == (3, 1)


def test_busy_editor_does_not_take_the_press():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]), busy=True)
    assert not grips.press((0, 0), (2, 0), NO_MOD)


def test_four_value_canvas_points_are_cut_to_x_and_y():
    grips, editor, shape = make_grips(LineString([(0, 0), (2, 0)]))
    assert grips.press((0, 0, 0, 1), (2, 0, 0, 1), NO_MOD)
    grips.move((20, 0, 0, 1), (2, 1, 0, 1))
    assert grips.release((20, 0, 0, 1), (2, 1, 0, 1))
    assert editor.apply_vertex_edit.call_args.args[2] == (2.0, 1.0)
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_grips.py -q`
Expected: error `ModuleNotFoundError: No module named 'appEditors.vertex_grips'`.

- [ ] **Step 3: Write `appEditors/vertex_grips.py`**

```python
"""
Grips on the vertices of 1 selected shape: drag a vertex grip to move the vertex, drag a midpoint grip to insert a
vertex, Ctrl+click a vertex grip to remove the vertex.

The editor keeps 1 instance as `vertex_grips` and calls sync(), press(), move(), release() and cancel(). Each commit
goes through editor.apply_vertex_edit(), so 1 drag is 1 Undo step. Only x and y of each point are used: VisPy
translate_coords() returns (x, y, z, w).
"""
import math
import gettext
import builtins

from PyQt6 import QtCore
from shapely import LineString, box
from shapely.errors import GEOSException

from appEditors.vertex_ops import SUPPORTED_TYPES, vertex_grips, ring_after_edit, edit_vertex, \
    check_vertex_result, contrast_color
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

GRIP_HIT_PX = 6             # hit radius of a grip, in screen pixels
GRIP_SIZE_PX = 4            # half the side of a vertex grip square, in screen pixels
GRIP_LIMIT = 5000           # shapes with more vertices get no grips
CLICK_DRAG_THRESHOLD_PX = 5
GRIP_COLOR = '#FF8000FF'
INVALID_COLOR = '#FF0000FF'


def xy(pos):
    return float(pos[0]), float(pos[1])


class VertexGrips:

    def __init__(self, editor):
        self.editor = editor
        self.shape = None       # the shape with grips
        self.grips = []         # [(kind, address, (x, y))] of self.shape
        self.pressed = None     # (kind, address, grip point, screen point, Ctrl held) of the pressed grip
        self.dragging = False
        self.candidate = None   # (action, address, point) of the last preview with valid input
        self._key = None        # (id(shape), id(shape.geo)) of the last sync()
        self._pixel = None      # pixel size of the last draw()
        self._collection = None

    def collection(self):
        if self._collection is None:
            self._collection = self.editor.app.plotcanvas.new_shape_collection(layers=1)
        return self._collection

    def pixel(self):
        return self.editor.canvas.pixel_size()

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
        editor = self.editor
        selected = list(editor.selected)
        shape = selected[0] if len(selected) == 1 and getattr(editor.active_tool, 'name', None) == 'select' else None
        key = None if shape is None else (id(shape), id(shape.geo))
        if key == self._key:
            return
        self.hide()
        if shape is not None:
            self.show(shape)

    def show(self, shape):
        self.hide()
        geo = shape.geo
        self._key = (id(shape), id(geo))
        if not isinstance(geo, SUPPORTED_TYPES) or geo.is_empty or geo.has_z:
            return
        grips = vertex_grips(geo)
        if sum(1 for grip in grips if grip[0] == 'vertex') > GRIP_LIMIT:
            self.editor.app.inform.emit('[WARNING_NOTCL] %s' %
                                        _("The shape has too many vertices for grips. Use Edit vertices."))
            return
        self.shape, self.grips = shape, grips
        self.collection().enabled = True
        self.draw()

    def hide(self):
        self.cancel()
        self.shape, self.grips, self._key, self._pixel = None, [], None, None
        if self._collection is not None:
            self._collection.clear(update=True)
            self._collection.enabled = False

    def draw(self):
        collection = self.collection()
        collection.clear(update=False)
        self._pixel = pixel = self.pixel()
        color = self.colors()[0]
        for kind, __, (x, y) in self.grips:
            half = GRIP_SIZE_PX * pixel * (1.0 if kind == 'vertex' else 0.6)
            square = box(x - half, y - half, x + half, y + half)
            if kind == 'vertex':
                collection.add(shape=square, color=color, face_color=color, update=False, layer=0, tolerance=None)
            else:
                collection.add(shape=square.exterior, color=color, update=False, layer=0, tolerance=None)
        collection.redraw()

    def hit(self, point):
        """(kind, address, grip point) of the grip under point, or None. Vertex grips first, then the nearest grip,
        then the lower address (2 parts that touch at 1 vertex)."""
        radius = GRIP_HIT_PX * self.pixel()
        best = None
        for kind, address, grip in self.grips:
            dist = math.dist(point, grip)
            if dist > radius:
                continue
            rank = (kind != 'vertex', dist, address)
            if best is None or rank < best[0]:
                best = (rank, kind, address, grip)
        return None if best is None else best[1:]

    def press(self, screen_pos, canvas_pos, modifiers):
        """True if a grip took the press."""
        self.cancel()
        if self.shape is None or self.editor.reject_busy():
            return False
        found = self.hit(xy(canvas_pos))
        if found is None:
            return False
        ctrl = bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier)
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
        if kind == 'vertex' and snapped == start and getattr(editor, 'active_snap_type', None) == 'corner':
            return x, y
        return snapped

    def move(self, screen_pos, canvas_pos):
        """True while a grip is pressed: the editor must not run its own move code."""
        if self.shape is not None and self._pixel is not None and self.pixel() != self._pixel:
            self.draw()  # the zoom changed: keep the grips at their size in pixels
        if self.pressed is None:
            return False
        kind, address, __, press_screen, __ = self.pressed
        if not self.dragging:
            if math.dist(xy(screen_pos), press_screen) < CLICK_DRAG_THRESHOLD_PX:
                return True
            self.dragging = True
        action = 'insert' if kind == 'mid' else 'move'
        point = self.target(canvas_pos)
        self.preview(action, address, point)
        return True

    def preview(self, action, address, point):
        tool_shape = self.editor.tool_shape
        tool_shape.clear(update=False)
        grip_color, invalid_color = self.colors()
        geo = self.shape.geo
        try:
            coords = ring_after_edit(geo, action, address, point)
        except (ValueError, TypeError, OverflowError, GEOSException):
            self.candidate = None
            tool_shape.redraw()
            return
        self.candidate = (action, address, point)
        try:
            check_vertex_result(edit_vertex(geo, action, address, point), address)
            color = grip_color
        except (ValueError, TypeError, OverflowError, GEOSException):
            color = invalid_color
        tool_shape.add(shape=LineString(coords), color=color, update=False, layer=0, tolerance=None)
        tool_shape.redraw()

    def release(self, screen_pos, canvas_pos):
        """True if a grip took the release. A drag commits; a Ctrl+click on a vertex grip removes the vertex."""
        if self.pressed is None:
            return False
        if self.dragging:
            self.move(screen_pos, canvas_pos)
        kind, address, __, __, ctrl = self.pressed
        dragging, candidate, shape = self.dragging, self.candidate, self.shape
        self.cancel()
        if not dragging:
            if ctrl and kind == 'vertex':
                self.editor.apply_vertex_edit('remove', address, target=shape)
            return True
        if candidate is not None:
            action, address, point = candidate
            self.editor.apply_vertex_edit(action, address, point, target=shape, on_segment=False)
        return True

    def cancel(self):
        if self.dragging:
            self.editor.tool_shape.clear(update=True)
        self.pressed, self.dragging, self.candidate = None, False, None
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_grips.py tests/test_vertex_ops.py -q`
Expected: all pass.

---

### Task 4: Connect `VertexGrips` to the Geometry Editor

**Files:**
- Modify: `appEditors/appGeoEditor.py`: imports, `__init__` (near line 331), `deactivate` (near line 1572),
  `on_tool_select` (near line 2222), `on_canvas_click` (near line 2292), `on_canvas_click_release` (near line 2361),
  `on_canvas_move` (near line 2555), `plot_all` (near line 2958), `plot_changes` (near line 3035)
- Test: `tests/test_geo_editor_vertex_drag.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_geo_editor_vertex_drag.py`:

```python
from appEditors.vertex_grips import VertexGrips
from tests.test_vertex_grips import FakeCollection

PIXEL = 0.01


def drag_editor(geometry):
    """A history editor with real apply_vertex_edit, real VertexGrips and a VisPy-like 4-value translate_coords."""
    editor, original = vertex_editor(geometry)
    editor.active_tool = SimpleNamespace(name='select')
    editor.canvas = SimpleNamespace(pixel_size=lambda: PIXEL, translate_coords=lambda pos: (pos[0], pos[1], 0, 1))
    editor.tool_shape = FakeCollection()
    editor.get_draw_color = lambda: '#00000080'
    editor.get_sel_color = lambda: '#0000FF80'
    editor.reject_busy = lambda: AppGeoEditor.reject_busy(editor)
    editor.snap = lambda x, y: (x, y)
    editor.app.grid_status = lambda: False
    editor.app.plotcanvas = SimpleNamespace(new_shape_collection=lambda layers: FakeCollection())
    editor.vertex_grips = VertexGrips(editor)
    editor.vertex_grips.sync()
    return editor, original


def test_one_drag_is_one_undo_step():
    editor, original = drag_editor(box(0, 0, 4, 4))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (4, 0), QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), (5, -1))
    assert grips.release((20, 0), (5, -1))
    assert (5, -1) in list(editor.selected[0].geo.exterior.coords)
    assert len(editor._history_undo) == 1
    assert grips.shape is editor.selected[0]  # plot_changes() ran sync(): grips on the new shape
    assert editor.undo()
    assert editor.selected == [original]


def test_invalid_drag_does_not_change_the_shape():
    editor, original = drag_editor(box(0, 0, 4, 4))
    grips = editor.vertex_grips
    assert grips.press((0, 0), (4, 0), QtCore.Qt.KeyboardModifier.NoModifier)
    grips.move((20, 0), (0, 4))  # across the square: self-intersection
    assert grips.release((20, 0), (0, 4))
    assert editor.selected == [original]
    assert not editor._history_undo
    assert editor.app.inform.emit.called


def test_canvas_click_hook_gives_the_press_to_the_grips():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock(press=Mock(return_value=True))
    event = SimpleNamespace(pos=(4, 0), button=1)
    assert AppGeoEditor.on_canvas_click(editor, event) is None
    editor.vertex_grips.press.assert_called_once()
    assert editor.press_pos_raw == (4, 0)


def test_canvas_click_release_hook_gives_the_release_to_the_grips():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock(release=Mock(return_value=True))
    editor.press_pos_raw, editor.press_pos_screen = (4, 0), (4, 0)
    event = SimpleNamespace(pos=(5, 0), button=1)
    assert AppGeoEditor.on_canvas_click_release(editor, event) is None
    editor.vertex_grips.release.assert_called_once()
    assert editor.press_pos_raw is None and editor.press_pos_screen is None


def test_right_button_press_cancels_the_drag():
    editor, original = drag_editor(box(0, 0, 4, 4))
    editor.vertex_grips = Mock()
    editor.app.ui = SimpleNamespace(rel_position_label=Mock(), popMenu=SimpleNamespace(mouse_is_panning=False))
    AppGeoEditor.on_canvas_click(editor, SimpleNamespace(pos=(4, 0), button=2))
    editor.vertex_grips.cancel.assert_called_once()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py -q`
Expected: `test_one_drag_is_one_undo_step` fails (`grips.shape` is not the new shape), and the 3 hook tests fail.
If a hook test fails on an attribute that the code reads before the hook, add that attribute to the test editor;
do not move the hook.

- [ ] **Step 3: Import and create the helper**

In the imports of `appEditors/appGeoEditor.py`, under the `vertex_ops` import of Task 2, add:

```python
from appEditors.vertex_grips import VertexGrips
```

In `__init__`, under `self.tool_shape = self.app.plotcanvas.new_shape_collection(layers=1)`, add:

```python
        # grips to drag the vertices of 1 selected shape in the Select tool
        self.vertex_grips = VertexGrips(self)
```

- [ ] **Step 4: Sync the grips after each plot**

In `plot_all`, after the last line `self._render_state = self.get_render_state()`, add:

```python
        grips = getattr(self, 'vertex_grips', None)
        if grips is not None:
            grips.sync()
```

In `plot_changes`, after its last line `self._render_state = self.get_render_state()`, add the same 3 lines.
(`plot_changes` returns early only through `self.plot_all()`, which syncs.) The `getattr` keeps the tests that build
an editor without `vertex_grips` working.

- [ ] **Step 5: Sync on a tool change and hide on deactivate**

In `on_tool_select`, as the first line after the `self.app.log.debug(...)` line, add:

```python
        grips = getattr(self, 'vertex_grips', None)
        if grips is not None:
            grips.cancel()
```

At the end of `on_tool_select` (after the `if tool in self.tools:` block, at method level), add:

```python
        if grips is not None:
            grips.sync()
```

The Esc key of the Geometry Editor calls `select_tool('select')` (`appGUI/MainGUI.py:3731`), which calls
`on_tool_select`, so Esc cancels a drag.

In `deactivate`, before the line `self.clear()`, add:

```python
        grips = getattr(self, 'vertex_grips', None)
        if grips is not None:
            grips.hide()
```

- [ ] **Step 6: Hook the press**

In `on_canvas_click`, replace:

```python
        if event.button == 1:
            self.press_pos_raw = (self.pos[0], self.pos[1])
            self.press_pos_screen = (event_pos[0], event_pos[1])
```

with:

```python
        grips = getattr(self, 'vertex_grips', None)
        if event.button == 1:
            self.press_pos_raw = (self.pos[0], self.pos[1])
            self.press_pos_screen = (event_pos[0], event_pos[1])
            if grips is not None and grips.press(event_pos, self.pos, QtWidgets.QApplication.keyboardModifiers()):
                return
        elif grips is not None:
            grips.cancel()
```

- [ ] **Step 7: Hook the release**

In `on_canvas_click_release`, after the block that sets `pos` (the `if not AppGeoEditor._tool_wants_raw_pick(self)
and self.app.grid_status():` / `else:` block) and before `try:`, add:

```python
        grips = getattr(self, 'vertex_grips', None)
        if event.button == 1 and grips is not None and grips.release(event_pos, pos_canvas):
            self.press_pos_raw = self.press_pos_screen = None
            return
```

- [ ] **Step 8: Hook the move**

In `on_canvas_move`, directly before the comment `# ### Selection area on canvas section ###`, add:

```python
        grips = getattr(self, 'vertex_grips', None)
        if grips is not None and grips.move(event_pos, pos):
            return
```

`pos` there is the raw result of `translate_coords` (4 values); `VertexGrips` keeps only x and y. The cursor and the
coordinate labels update above this line, so they follow the drag.

- [ ] **Step 9: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py tests/test_vertex_grips.py tests/test_vertex_ops.py tests/test_geo_editor_vertices.py -q`
Expected: all pass.

- [ ] **Step 10: Run the Geometry Editor tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_improvements.py tests/test_geo_editor_snapping.py tests/test_vispy_only_geo_editor.py tests/test_geo_editor_history.py tests/test_geo_editor_delete_plot.py tests/test_editor_move_batch.py -q`
Expected: all pass. A failure with `AttributeError: ... 'vertex_grips'` means a hook does not use `getattr`; fix the
hook, not the test.

---

### Task 5: Part and Ring fields in the Edit vertices dialog

**Files:**
- Modify: `appEditors/appGeoEditor.py` (`on_edit_vertices`, near line 1044)
- Test: `tests/test_geo_editor_vertex_drag.py`, `tests/test_geo_editor_vertices.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_geo_editor_vertex_drag.py`:

```python
def test_dialog_edits_a_hole_through_part_and_ring_fields(monkeypatch):
    from appEditors.appGeoEditor import AppGeoEditorUI
    hole = [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]
    editor, original = vertex_editor(Polygon([(0, 0), (6, 0), (6, 6), (0, 6)], [hole]))
    editor.decimals = 4
    app = SimpleNamespace(decimals=4, app_units='mm', resource_location='', on_editing_finished=Mock())
    editor.ui = AppGeoEditorUI(app)
    editor.ui.vertex_edit_btn.clicked.connect(lambda: AppGeoEditor.on_edit_vertices(editor))

    def exercise(dialog):
        part = dialog.findChild(QtWidgets.QSpinBox, 'vertex_part')
        ring = dialog.findChild(QtWidgets.QSpinBox, 'vertex_ring')
        index = dialog.findChild(QtWidgets.QSpinBox, 'vertex_index')
        x = dialog.findChild(QtWidgets.QLineEdit, 'vertex_x')
        y = dialog.findChild(QtWidgets.QLineEdit, 'vertex_y')
        assert part.maximum() == 0 and ring.maximum() == 1
        ring.setValue(1)
        assert float(x.text()) == 1 and float(y.text()) == 1
        x.setText('1.5')
        y.setText('0.5')
        dialog.findChild(QtWidgets.QPushButton, 'vertex_apply').click()
        assert list(editor.selected[0].geo.interiors[0].coords)[0] == (1.5, 0.5)
        dialog.reject()
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, 'exec', exercise)
    editor.ui.vertex_edit_btn.click()
    assert editor.undo()
    assert editor.selected == [original]
```

- [ ] **Step 2: Run the test and see it fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py::test_dialog_edits_a_hole_through_part_and_ring_fields -q`
Expected: FAIL (`part` is `None`).

- [ ] **Step 3: Change the dialog**

In `on_edit_vertices`, replace the `hint` text:

```python
        hint = FCLabel(_("Indexes start at 0. Ring 0 is the line or the polygon exterior; rings 1+ are the holes.\n"
                         "Insert uses the segment from index to index + 1.\n"
                         "The closing coordinate is an alias of vertex 0."))
```

Replace the block from `index_entry = QtWidgets.QSpinBox()` down to `grid.addWidget(close_btn, 5, 1)` with:

```python
        part_entry, ring_entry, index_entry = QtWidgets.QSpinBox(), QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        part_entry.setObjectName('vertex_part')
        ring_entry.setObjectName('vertex_ring')
        index_entry.setObjectName('vertex_index')
        x_entry, y_entry = FCEntry(), FCEntry()
        x_entry.setObjectName('vertex_x')
        y_entry.setObjectName('vertex_y')
        action_entry = QtWidgets.QComboBox()
        for label, action in [(_("Move"), 'move'), (_("Insert"), 'insert'), (_("Remove"), 'remove')]:
            action_entry.addItem(label, action)
        for row, (label, widget) in enumerate([(_("Part"), part_entry), (_("Ring"), ring_entry),
                                                (_("Vertex / segment index"), index_entry),
                                                ('X', x_entry), ('Y', y_entry),
                                                (_("Operation"), action_entry)], 1):
            grid.addWidget(FCLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
        apply_btn, close_btn = FCButton(_("Apply")), FCButton(_("Close"))
        apply_btn.setObjectName('vertex_apply')
        grid.addWidget(apply_btn, 7, 0)
        grid.addWidget(close_btn, 7, 1)
```

Replace `load_vertex` and `apply` with:

```python
        def load_vertex():
            parts = parts_of(target.geo)
            part_entry.setMaximum(len(parts) - 1)
            rings = rings_of(parts[part_entry.value()])
            ring_entry.setMaximum(len(rings) - 1)
            coords = list(rings[ring_entry.value()].coords)
            index_entry.setMaximum(len(coords) - 1)
            x_entry.setText(str(coords[index_entry.value()][0]))
            y_entry.setText(str(coords[index_entry.value()][1]))

        def apply():
            nonlocal target
            address = (part_entry.value(), ring_entry.value(), index_entry.value())
            if self.apply_vertex_edit(action_entry.currentData(), address,
                                      (x_entry.text(), y_entry.text()), target=target) == 'fail':
                return
            target = self.selected[0]
            load_vertex()
```

Under `index_entry.valueChanged.connect(load_vertex)`, add:

```python
        part_entry.valueChanged.connect(load_vertex)
        ring_entry.valueChanged.connect(load_vertex)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py -q`
Expected: all pass, `test_numeric_dialog_loads_index_and_applies_through_real_button` included.

---

### Task 6: Changelog and final check

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the changelog entry**

In `CHANGELOG.md`, under the date `21.10.2026`, add a section after the "Align Objects Plugin" section:

```markdown
Geometry Editor - vertex grips:

- in the Select tool, 1 selected shape shows grips on its vertices (filled squares) and on the middle of its segments (small hollow squares)
- drag a vertex grip to move the vertex; drag a midpoint grip to insert a vertex; Ctrl+click a vertex grip to remove the vertex; Esc or the right mouse button cancels the drag
- works on all rings (the exterior and the holes) and on multipart shapes; grid snap and corner snap apply during the drag
- the preview is red if the result is not valid; the release then leaves the shape as it was and tells the reason; if red is near an editor color, the opposite color is used (the same rule for the orange grips)
- each drag is 1 Undo step; shapes with more than 5000 vertices get no grips (use Edit vertices)
- Edit vertices dialog: new Part and Ring fields, so the dialog also edits holes and multipart shapes
```

- [ ] **Step 2: Run the targeted tests one more time**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vertex_ops.py tests/test_vertex_grips.py tests/test_geo_editor_vertex_drag.py tests/test_geo_editor_vertices.py tests/test_geo_editor_improvements.py tests/test_geo_editor_snapping.py tests/test_vispy_only_geo_editor.py tests/test_geo_editor_history.py -q`
Expected: all pass. Report the exact pass count.

- [ ] **Step 3: Report to the user (no commit)**

Report the changed and new files and the test result. List these manual GUI checks for the user:

1. Open a Geometry object in the editor. Select 1 polygon. Grips show on the vertices and the segment middles.
2. Drag a vertex. The preview follows the cursor. Release. The shape changes. Ctrl+Z gives the old shape.
3. Drag a midpoint grip. A new vertex appears.
4. Ctrl+click a vertex grip. The vertex goes away.
5. Drag a vertex across the shape. The preview is red. Release. The shape does not change. The status bar shows the reason.
6. Press Esc and the right button during a drag. The preview goes away.
7. Zoom in and out. The grips keep their size in pixels after the next mouse move.
8. Select 2 shapes, or start the Move tool. The grips go away.
9. Change the editor draw color to red in Preferences. The invalid preview is cyan.
```
