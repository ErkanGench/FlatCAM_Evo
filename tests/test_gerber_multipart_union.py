"""Gerber parse: poly_buffer entries that are MultiPolygons must not break the union step.

A macro aperture with two separate circles flashes as a MultiPolygon. ``MultiPolygon(poly_buffer)`` in the union step
accepts only Polygons, so ``parse_lines`` flattens ``poly_buffer`` once before the union.

Evidence rules: the fixture must really put a MultiPolygon into poly_buffer (spy on create_flash_geometry, which feeds poly_buffer), and each union
branch must be reached (spy on the MultiPolygon constructor / unary_union). Patching fuse_parts is only the way to
reach the GEOS fallback; it is not the evidence.
"""

import math
from unittest.mock import patch

import pytest
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

import appParsers.ParseGerber as pg
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


class _CtorSpy(type):
    """Stands in for the MultiPolygon name in ParseGerber: records constructor calls, keeps isinstance working."""

    def __call__(cls, *args, **kwargs):
        cls.calls.append(args[0] if args else None)
        return MultiPolygon(*args, **kwargs)

    def __instancecheck__(cls, obj):
        return isinstance(obj, MultiPolygon)


def _make_spy():
    return _CtorSpy('MultiPolygonSpy', (), {'calls': []})


def _parse(tmp_path, buffering, use_buffer, fuse=None, spy_union=False):
    app = make_app()
    app.options['gerber_buffering'] = buffering
    app.options['gerber_use_buffer_for_union'] = use_buffer
    path = tmp_path / 'multipart.gbr'
    path.write_text(TEXT)

    # every geometry that create_flash_geometry hands to poly_buffer (works on the old code too)
    flatten_inputs = []
    real_flash = pg.Gerber.create_flash_geometry

    def flash_spy(self, *a, **k):
        res = real_flash(self, *a, **k)
        flatten_inputs.append([res])
        return res

    ctor = _make_spy()
    union_calls = []

    def union_spy(geoms, *a, **k):
        union_calls.append(list(geoms))
        return unary_union(geoms, *a, **k)

    patches = [
        patch.object(pg.Gerber, 'create_flash_geometry', flash_spy),
        patch.object(pg, 'MultiPolygon', ctor),
        patch.object(pg, 'unary_union', union_spy),
    ]
    if fuse is not None:
        patches.append(patch.object(pg, 'fuse_parts', fuse))
    for p in patches:
        p.start()
    try:
        obj = GerberObject('mp', app)
        assert obj.parse_file(str(path)) is None
    finally:
        for p in reversed(patches):
            p.stop()
    return obj, flatten_inputs, ctor, union_calls


def _assert_fixture_has_multipolygon(flatten_inputs):
    """poly_buffer receives (macro flash result) at least 1 MultiPolygon (otherwise the test proves nothing)."""
    buffers = [b for b in flatten_inputs if any(isinstance(g, MultiPolygon) for g in b)]
    assert buffers, 'fixture never put a MultiPolygon into poly_buffer'


def _assert_valid_result(obj):
    geo = unary_union(obj.solid_geometry)
    assert geo.is_valid
    assert geo.area == pytest.approx(EXPECTED_AREA, rel=0.01)
    parts = list(geo.geoms) if hasattr(geo, 'geoms') else [geo]
    assert len(parts) == 3
    assert all(isinstance(p, Polygon) for p in parts)


def test_clipper_branch_full_buffering(tmp_path):
    """use_buffering == 'full' with a successful fuse: MultiPolygon(fused) only."""
    sentinel = []

    def fuse(parts):
        sentinel.append(list(parts))
        return [g for p in parts for g in (p.geoms if hasattr(p, 'geoms') else [p])]

    obj, flatten_inputs, ctor, union_calls = _parse(tmp_path, 'full', True, fuse=fuse)
    _assert_fixture_has_multipolygon(flatten_inputs)
    assert len(sentinel) == 1
    assert all(type(g) is Polygon for g in sentinel[0])
    assert len(ctor.calls) == 1 and ctor.calls[0] is not sentinel[0]
    assert not union_calls
    assert unary_union(obj.solid_geometry).area == pytest.approx(EXPECTED_AREA, rel=0.01)


