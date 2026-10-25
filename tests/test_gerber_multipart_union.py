"""Gerber parse: poly_buffer entries that are MultiPolygons must not break the union step.

A macro aperture with two separate circles flashes as a MultiPolygon. ``MultiPolygon(poly_buffer)`` in the union step
accepts only Polygons, so ``parse_lines`` flattens ``poly_buffer`` once before the union.

The test parses the file for real in the 'full' buffering mode and checks the copper: 3 valid circles.
"""

import math
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from appObjects.GerberObject import GerberObject
from tests.helpers_objects import _headless_qt, make_app  # noqa: F401,E402

# one flash of a macro made of 2 separate circles (r=0.5 at x=0 and x=3, 1 mm apart) and a plain C flash at x=10
TEXT = """%FSLAX46Y46*%
%MOMM*%
%AMTWO*
1,1,1.0,0,0*
1,1,1.0,3,0*%
%ADD10TWO*%
%ADD11C,1.0*%
G01*
%LPD*%
D10*
X0Y0D03*
D11*
X10000000Y0D03*
M02*
"""

EXPECTED_AREA = 3 * math.pi * 0.25  # 3 circles of diameter 1


def test_clipper_branch_full_buffering(tmp_path):
    """gerber_buffering == 'full': the macro flash of 2 separate circles (a MultiPolygon) must not break the union."""
    app = make_app()
    app.options['gerber_buffering'] = 'full'
    app.options['gerber_use_buffer_for_union'] = True
    path = tmp_path / 'multipart.gbr'
    path.write_text(TEXT)

    obj = GerberObject('mp', app)
    assert obj.parse_file(str(path)) is None

    geo = unary_union(obj.solid_geometry)
    assert geo.is_valid
    assert geo.area == pytest.approx(EXPECTED_AREA, rel=0.01)
    parts = list(geo.geoms) if hasattr(geo, 'geoms') else [geo]
    assert len(parts) == 3
    assert all(isinstance(p, Polygon) for p in parts)
