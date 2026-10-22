"""
appIO.export_svg(): the viewBox of the SVG has to contain the drawing.

The exported shapes keep their FlatCAM coordinates and are put in a group with ``transform="scale(1,-1)"`` so that
the Y axis points up in Inkscape and similar programs. After the flip the drawing spans y from ``-ymax`` to ``-ymin``,
so the viewBox has to start at ``-ymax``. It started at ``ymin - height``, which is the same value only when
``ymin == 0``: for every other drawing the viewBox did not contain the drawing and a viewer showed an empty page.
"""

import re
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, Mock

import pytest
from PyQt6 import QtWidgets
from shapely.affinity import translate
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from appHandlers.appIO import appIO
from appParsers.SVG.reader import svg_to_shapes
from camlib import Geometry
from tests.helpers_objects import make_app_0b as make_app  # noqa: F401,E402

NUMBER = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')


@pytest.fixture(scope='module')
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _export(qt_app, geometry, tmp_path):
    """Export a Geometry with appIO.export_svg() and return the path of the file."""
    app = make_app()
    app.new_project_signal = Mock()
    app.file_opened = Mock()
    app.file_saved = Mock()
    app.proc_container = MagicMock()

    obj = Geometry(app)
    obj.kind, obj.multigeo = 'geometry', False    # set by GeometryObject
    obj.units = 'MM'
    obj.solid_geometry = geometry
    app.collection = Mock()
    app.collection.get_by_name.return_value = obj

    path = tmp_path / 'out.svg'
    assert appIO(app).export_svg('geo', str(path)) != 'fail'
    return path


def _view_box(path):
    root = ET.parse(str(path)).getroot()
    x, y, width, height = (float(v) for v in root.get('viewBox').split())
    return x, y, width, height


def _flipped_content_bounds(path):
    """The bounds of the drawing after the group transform scale(1,-1): what a viewer shows."""
    root = ET.parse(str(path)).getroot()
    group = [e for e in root.iter() if e.tag.endswith('}g') or e.tag == 'g'][0]
    assert group.get('transform') == 'scale(1,-1)'
    xs, ys = [], []
    for element in group.iter():
        data = element.get('d') or element.get('points') or ''
        numbers = [float(v) for v in NUMBER.findall(data)]
        xs += numbers[0::2]
        ys += numbers[1::2]
    return min(xs), -max(ys), max(xs), -min(ys)


# (xmin, ymin, xmax, ymax); the 2nd and the 3rd start above and below y = 0, the last one is the only old working case
BOXES = [(10, 20, 40, 30), (-5, -30, 7, -10), (0, 0, 10, 5), (134.4, 73.79, 154.6, 124.16)]


@pytest.mark.parametrize('bounds', BOXES)
def test_the_view_box_contains_the_drawing(qt_app, tmp_path, bounds):
    path = _export(qt_app, [box(*bounds)], tmp_path)

    vx, vy, vw, vh = _view_box(path)
    cx0, cy0, cx1, cy1 = _flipped_content_bounds(path)

    assert vw == pytest.approx(bounds[2] - bounds[0])
    assert vh == pytest.approx(bounds[3] - bounds[1])
    assert vx == pytest.approx(cx0)
    assert vy == pytest.approx(cy0)
    assert vx + vw == pytest.approx(cx1)
    assert vy + vh == pytest.approx(cy1)


def test_a_line_drawing_is_inside_the_view_box_too(qt_app, tmp_path):
    path = _export(qt_app, [LineString([(100, 200), (150, 260)])], tmp_path)

    vx, vy, vw, vh = _view_box(path)
    cx0, cy0, cx1, cy1 = _flipped_content_bounds(path)

    assert (vx, vy, vx + vw, vy + vh) == pytest.approx((cx0, cy0, cx1, cy1))


@pytest.mark.parametrize('bounds', BOXES)
def test_the_exported_file_is_read_back_with_the_same_size_and_orientation(qt_app, tmp_path, bounds):
    # a rectangle with a small box at its lower left corner and one at its upper right corner: not symmetric, so a
    # mirrored or moved drawing is noticed
    original = box(*bounds).union(box(bounds[0], bounds[1], bounds[0] + 1, bounds[1] + 3))
    original = original.union(box(bounds[2] - 2, bounds[3] - 1, bounds[2], bounds[3]))
    path = _export(qt_app, [original], tmp_path)

    # a Geometry object is exported as its outlines
    imported = unary_union(svg_to_shapes(str(path), object_type='geometry', units='MM'))

    # the importer puts the origin of the viewBox at (0, 0): the drawing comes back moved to the origin, not mirrored
    expected = translate(original.boundary, -original.bounds[0], -original.bounds[1])
    assert imported.bounds == pytest.approx(expected.bounds, abs=1e-6)
    assert imported.hausdorff_distance(expected) == pytest.approx(0, abs=1e-6)
