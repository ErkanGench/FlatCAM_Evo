"""Pure vertex edits addressed as (part, ring, index). No Qt."""
import math

import pytest
from shapely import BufferJoinStyle
from shapely.geometry import LineString, LinearRing, Point, Polygon, MultiLineString, MultiPolygon, box

from appEditors.vertex_ops import (vertex_grips, vertex_address, ring_after_edit, edit_vertex, check_vertex_result,
                                   contrast_color, circle_center, arc_middle, arc_points, find_arcs, ring_skeleton,
                                   expand_skeleton)

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


ROUNDED = box(1, 1, 9, 5).buffer(1, join_style=BufferJoinStyle.round)   # 4 corner arcs of radius 1
CORNERS = [(1, 1), (9, 1), (9, 5), (1, 5)]


def ring_vertices(ring):
    coords = [tuple(coord) for coord in ring.coords]
    return coords[:-1] if coords[0] == coords[-1] else coords


def s_curve():
    """An open line: 1 straight segment, 2 quarter arcs that share the vertex (1, 1), 1 straight segment."""
    half = math.sqrt(0.5)
    first = arc_points((0, 0), (1 - half, half), (1, 1), 64)
    second = arc_points((1, 1), (1 + half, 2 - half), (2, 2), 64)
    return [(-3, 0)] + first + second[1:] + [(2, 5)]


def test_circle_center_and_collinear_points():
    assert circle_center((1, 0), (0, 1), (-1, 0)) == pytest.approx((0, 0))
    assert circle_center((0, 0), (1, 0), (2, 0)) is None


def test_arc_middle_is_at_the_half_angle():
    through = (math.cos(0.3), math.sin(0.3))
    assert arc_middle((1, 0), through, (0, 1)) == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    assert arc_middle((0, 0), (1, 0), (2, 0)) == (1, 0)   # on 1 line: the middle of the segment


def test_arc_points_follow_the_circle_steps():
    points = arc_points((1, 0), (math.sqrt(0.5), math.sqrt(0.5)), (0, 1), 32)
    assert len(points) == 9   # a quarter of 32 steps
    assert points[0] == (1, 0) and points[-1] == (0, 1)
    assert all(math.dist(point, (0, 0)) == pytest.approx(1) for point in points)
    assert len(arc_points((1, 0), (math.cos(0.05), math.sin(0.05)), (math.cos(0.1), math.sin(0.1)), 32)) == 4
    assert len(arc_points((1, 0), (0, 1), (-1, 0), 4)) == 7   # 4 steps: 2 segments, but at most 30 degrees each
    assert arc_points((0, 0), (1, 0), (2, 0), 32) == [(0, 0), (2, 0)]


def test_find_arcs_rounded_rectangle_has_4_corner_arcs():
    vertices = ring_vertices(ROUNDED.exterior)
    arcs = find_arcs(vertices, True)
    assert len(arcs) == 4 and not any(arc.full for arc in arcs)
    for arc in arcs:
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        assert math.dist(center, vertices[arc.start]) == pytest.approx(1)
        assert min(math.dist(center, corner) for corner in CORNERS) == pytest.approx(0, abs=1e-9)


def test_find_arcs_line_buffer_has_2_end_arcs():
    assert len(find_arcs(ring_vertices(LineString([(0, 0), (10, 0)]).buffer(1).exterior), True)) == 2


def test_find_arcs_full_circle():
    arcs = find_arcs(ring_vertices(Point(0, 0).buffer(2).exterior), True)
    assert len(arcs) == 1 and arcs[0].full


def test_find_arcs_arc_across_the_ring_start():
    vertices = ring_vertices(ROUNDED.exterior)
    first = find_arcs(vertices, True)[0]
    middle = (first.start + first.end) // 2
    rotated = vertices[middle:] + vertices[:middle]   # vertex 0 is now inside an arc
    arcs = find_arcs(rotated, True)
    assert len(arcs) == 4
    assert sum(1 for arc in arcs if arc.end < arc.start) == 1


def test_find_arcs_s_curve_arcs_share_a_vertex():
    vertices = s_curve()
    arcs = find_arcs(vertices, False)
    assert len(arcs) == 2
    assert arcs[0].end == arcs[1].start
    assert vertices[arcs[0].end] == (1, 1)


@pytest.mark.parametrize('vertices,closed', [
    ([(0, 0), (1, 0), (1, 1), (0, 1)], True),                       # a square: 90 degree corners
    ([(0, 0), (4, 0), (5, 2), (3, 5), (0, 3)], True),               # a plain polygon
    ([(0, 0), (1, 0), (1.99, 0.14)], False),                        # only 2 equal segments
    ([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)], False),              # a straight run of equal segments
])
def test_find_arcs_finds_no_arc(vertices, closed):
    assert find_arcs(vertices, closed) == []


def test_skeleton_round_trip_of_a_rounded_rectangle():
    vertices = ring_vertices(ROUNDED.exterior)
    nodes, links = ring_skeleton(vertices, True)
    assert len(nodes) == 8 and len(links) == 8
    assert sum(1 for link in links if link is not None) == 4
    rebuilt = expand_skeleton([vertices[node] for node in nodes], links, True, 64)
    assert rebuilt[0] == rebuilt[-1]
    assert Polygon(rebuilt).symmetric_difference(ROUNDED).area < 1e-9


def test_skeleton_of_an_open_s_curve_and_of_a_full_circle():
    vertices = s_curve()
    nodes, links = ring_skeleton(vertices, False)
    assert nodes == [0, 1, 17, 33, 34]
    assert [link is None for link in links] == [True, False, False, True]
    assert ring_skeleton(ring_vertices(Point(0, 0).buffer(2).exterior), True) == ([], [])


def grips_of(geometry, kind):
    return [(address, point) for k, address, point in vertex_grips(geometry) if k == kind]


def on_some_arc(ring, point, closed=True):
    """True if point is on the circle of 1 of the arcs of ring. A point on the circle is not always on the chords."""
    vertices = ring_vertices(ring)
    for arc in find_arcs(vertices, closed):
        center = circle_center(vertices[arc.start], arc.middle, vertices[arc.end])
        if abs(math.dist(center, point) - math.dist(center, vertices[arc.start])) < 1e-9:
            return True
    return False


def test_grips_of_a_rounded_rectangle():
    assert len(grips_of(ROUNDED, 'arc_end')) == 8
    assert grips_of(ROUNDED, 'vertex') == []
    assert len(grips_of(ROUNDED, 'mid')) == 4
    arc_mids = grips_of(ROUNDED, 'arc_mid')
    assert len(arc_mids) == 4 and all(len(address) == 4 for address, __ in arc_mids)
    assert all(on_some_arc(ROUNDED.exterior, point) for __, point in arc_mids)


def test_grips_of_a_full_circle():
    radius_grips = grips_of(Point(0, 0).buffer(2), 'radius')
    assert [address for address, __ in radius_grips] == [(0, 0, 0)] * 4
    assert [value for __, point in radius_grips for value in point] == pytest.approx([2, 0, 0, 2, -2, 0, 0, -2])
    assert len(vertex_grips(Point(0, 0).buffer(2))) == 4


def test_arc_mid_bends_the_arc_through_the_cursor():
    address, middle = grips_of(ROUNDED, 'arc_mid')[0]
    cursor = (middle[0] - 0.3, middle[1] - 0.3)
    result = edit_vertex(ROUNDED, 'arc_mid', address, cursor, steps=64)
    check_vertex_result(result, address)
    assert on_some_arc(result.exterior, cursor)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 4


def test_arc_end_moves_the_end_and_keeps_the_middle():
    (address, point), = [(a, p) for a, p in grips_of(ROUNDED, 'arc_end') if p == (1.0, 0.0)]
    middle = arc_middle((1, 0), (1 - math.sqrt(0.5), 1 - math.sqrt(0.5)), (0, 1))
    result = edit_vertex(ROUNDED, 'arc_end', address, (1.3, 0), steps=64)
    check_vertex_result(result, address)
    assert (1.3, 0) in list(result.exterior.coords)
    assert on_some_arc(result.exterior, middle)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 4


def test_arc_end_on_a_shared_vertex_changes_both_arcs():
    line = LineString(s_curve())
    result = edit_vertex(line, 'arc_end', (0, 0, 17), (1.2, 1), steps=64)
    arcs = find_arcs(list(result.coords), False)
    assert len(arcs) == 2 and arcs[0].end == arcs[1].start
    assert result.coords[arcs[0].end] == (1.2, 1)


def test_arc_flatten_makes_a_straight_segment():
    address, __ = grips_of(ROUNDED, 'arc_mid')[0]
    vertices = ring_vertices(ROUNDED.exterior)
    begin, end = vertices[address[2]], vertices[address[3]]
    result = edit_vertex(ROUNDED, 'arc_flatten', address)
    coords = list(result.exterior.coords)
    assert any(pair in ((begin, end), (end, begin)) for pair in zip(coords, coords[1:]))
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 3


def test_arc_mid_on_the_chord_makes_a_straight_segment():
    address, __ = grips_of(ROUNDED, 'arc_mid')[0]
    vertices = ring_vertices(ROUNDED.exterior)
    begin, end = vertices[address[2]], vertices[address[3]]
    chord_middle = ((begin[0] + end[0]) / 2, (begin[1] + end[1]) / 2)
    result = edit_vertex(ROUNDED, 'arc_mid', address, chord_middle, steps=64)
    assert len(find_arcs(ring_vertices(result.exterior), True)) == 3


def test_arc_radius_scales_a_full_circle():
    circle = Point(1, 1).buffer(2)
    result = edit_vertex(circle, 'arc_radius', (0, 0, 0), (4, 1))
    assert len(result.exterior.coords) == len(circle.exterior.coords)
    assert all(math.dist(coord, (1, 1)) == pytest.approx(3) for coord in result.exterior.coords)


@pytest.mark.parametrize('geometry,action,address,point', [
    (box(0, 0, 4, 4), 'arc_end', (0, 0, 1), (5, 0)),               # not the end of an arc
    (ROUNDED, 'arc_mid', (0, 0, 1, 2), (0, 0)),                     # not an arc
    (ROUNDED, 'arc_mid', (0, 0, 1), (0, 0)),                        # an arc address has 4 values
    (box(0, 0, 4, 4), 'arc_radius', (0, 0, 0), (5, 0)),             # not a full circle
    (ROUNDED, 'arc_mid', (0, 0, 1, 17), None),                      # no point
])
def test_bad_arc_edits_raise(geometry, action, address, point):
    with pytest.raises(ValueError):
        edit_vertex(geometry, action, address, point)
