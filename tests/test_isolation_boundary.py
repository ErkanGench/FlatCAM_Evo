"""Isolation limited to a boundary (e.g. the board outline).

camlib.outline_area() makes the area enclosed by an outline (an Edge Cuts band, closed lines, a drawn polygon),
clip_paths_to_area() cuts the paths to it. GerberObject.isolate() (the isolate Tcl command) and the Isolation Plugin
clip each pass to the boundary and stop at the first pass that is completely outside it; when that is the first pass,
no isolation is made. The isolation tests use the headless fixtures of test_unify_characterization and its mixed
Gerber (about 31 x 34 mm of copper).
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import shapely
from PyQt6 import sip
from shapely.geometry import LinearRing, LineString, Point, Polygon, box
from shapely.ops import unary_union

from appObjects.GeometryObject import GeometryObject
from appPlugins.ToolIsolation import ToolIsolation
from camlib import area_outline_paths, boundary_passes_message, clip_paths_to_area, outline_area
from defaults import AppDefaults
from tclCommands.TclCommandIsolate import TclCommandIsolate

from test_plugin_geometry_bases import make_tool_app
from test_unify_characterization import _headless_qt, app, make_gerber  # noqa: F401  (fixtures)

DIA = 0.5
OVERLAP = 0  # percent
PASSES = 100
NO_PATH_INSIDE = '[ERROR_NOTCL] %s: No isolation path is inside the boundary. Check that the boundary object is the ' \
                 'outline of this board.'


def board_of(gerber, margin=1.0):
    minx, miny, maxx, maxy = unary_union(gerber.solid_geometry).bounds
    return box(minx - margin, miny - margin, maxx + margin, maxy + margin)


def far_box_of(gerber):
    # e.g. the outline of another board: not even the first pass reaches into it
    minx, miny, maxx, maxy = unary_union(gerber.solid_geometry).bounds
    return box(maxx + 50, maxy + 50, maxx + 90, maxy + 90)


def length_outside(paths, area):
    return unary_union(paths).difference(area.buffer(1e-9)).length


def reports(app):
    return [c.args[0] for c in app.inform.emit.call_args_list if 'boundary' in str(c.args[0])]


# ---------------------------------------------------------------------------------------------------------- camlib

def test_edge_cuts_band_gives_the_board_area():
    # an outline drawn with a 0.1 mm line, as in an Edge Cuts Gerber: a band (a polygon with a hole)
    band = LinearRing([(0, 0), (40, 0), (40, 90), (0, 90)]).buffer(0.05)
    area = outline_area([band])
    assert area.area == pytest.approx(40.1 * 90.1, abs=0.5)
    assert area.contains(Point(20, 45))


def test_closed_line_pieces_enclose_an_area():
    pieces = [LineString([(0, 0), (10, 0)]), LineString([(10, 0), (10, 5)]), LineString([(10, 5), (0, 5), (0, 0)])]
    assert outline_area(pieces).area == pytest.approx(50.0)


def test_the_holes_of_a_polygon_are_filled():
    assert outline_area(box(0, 0, 10, 10).difference(box(4, 4, 6, 6))).area == pytest.approx(100.0)


def test_an_open_line_encloses_no_area():
    assert outline_area([LineString([(0, 0), (10, 0), (10, 10)])]) is None


def test_the_band_of_an_outline_with_a_gap_encloses_no_area():
    # filled, the band without a hole would be a 0.1 mm wide boundary that removes nearly all the isolation
    band = LineString([(0, 0), (40, 0), (40, 90), (0, 90), (0, 1)]).buffer(0.05)
    assert len(band.interiors) == 0
    assert outline_area([band]) is None


CHAMFERED_BOARD = [(0, 0), (50, 0), (50, 30), (40, 40), (0, 40), (0, 0)]


def test_the_segments_of_an_unbuffered_outline_give_the_board_area():
    # a Gerber loaded with Buffering = No keeps one polygon for each segment of the outline; the chamfer segment
    # alone covers less than OUTLINE_BAND_RATIO of its bounding box
    segments = [LineString([a, b]).buffer(0.05) for a, b in zip(CHAMFERED_BOARD, CHAMFERED_BOARD[1:])]
    area = outline_area(segments)
    assert area.area == pytest.approx(Polygon(CHAMFERED_BOARD).buffer(0.05).area, abs=0.01)
    assert area.contains(Point(25, 20))


def test_the_segments_of_an_outline_with_a_gap_enclose_no_area():
    segments = [LineString([a, b]).buffer(0.05) for a, b in zip(CHAMFERED_BOARD, CHAMFERED_BOARD[1:])]
    del segments[2]   # the chamfer
    assert outline_area(segments) is None


def test_drawn_shapes_and_narrow_boards_are_areas():
    assert outline_area(Polygon([(0, 0), (10, 0), (10, 10)])).area == pytest.approx(50.0)
    assert outline_area(box(0, 0, 50, 1)).area == pytest.approx(50.0)


def test_clip_keeps_the_paths_inside_and_cuts_the_crossing_ones():
    area = box(0, 0, 10, 10)
    inside = Point(5, 5).buffer(1)
    crossing = Point(10, 5).buffer(2)
    outside = Point(30, 30).buffer(1)
    paths = clip_paths_to_area([inside, crossing, outside], area)
    assert sum(1 for p in paths if p.equals(inside.exterior)) == 1
    assert length_outside(paths, area) == pytest.approx(0.0)
    assert unary_union(paths).length > inside.exterior.length


def test_clip_of_paths_outside_the_area_is_empty():
    assert clip_paths_to_area([Point(30, 30).buffer(1)], box(0, 0, 10, 10)) == []


@pytest.mark.parametrize('ccw, start_inside', [(True, True), (True, False), (False, True), (False, False)],
                         ids=['ccw_start_inside', 'ccw_start_outside', 'cw_start_inside', 'cw_start_outside'])
def test_the_clipped_parts_keep_the_milling_direction(ccw, start_inside):
    # the direction of a ring is the milling direction (climb / conventional): the parts must not be reversed
    area = box(0, 0, 10, 10)
    circle = list(Point(10, 5).buffer(2).exterior.coords)[:-1]
    if LinearRing(circle).is_ccw != ccw:
        circle.reverse()
    # start at (8, 5), inside the area, or at (12, 5), outside it
    k = min(range(len(circle)), key=lambda i: circle[i][0] if start_inside else -circle[i][0])
    circle = circle[k:] + circle[:k]
    ring = LinearRing(circle)
    assert ring.is_ccw == ccw

    paths = clip_paths_to_area([ring], area)
    assert sum(p.length for p in paths) == pytest.approx(ring.intersection(area).length)
    for part in paths:
        # the vertices of the part (between its 2 points on the edge of the area) follow the ring
        inner = list(part.coords)[1:-1]
        i = (circle + circle).index(inner[0])
        assert (circle + circle)[i:i + len(inner)] == inner


def test_area_outline_paths_are_the_exteriors():
    paths = area_outline_paths(shapely.MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)]))
    assert [Polygon(p).area for p in paths] == [1.0, 1.0]
    assert all(isinstance(p, LinearRing) for p in paths)


def test_the_report_tells_if_the_area_is_cleared():
    assert boundary_passes_message('iso', 7, 50) == \
        '[success] iso: 7 of 50 passes, the area inside the boundary is cleared.'
    assert boundary_passes_message('iso', 3, 3).startswith('[WARNING_NOTCL] iso: all 3 passes made')
    # not even the first pass reaches into the boundary: an error, not "cleared"
    assert boundary_passes_message('iso', 0, 50) == NO_PATH_INSIDE % 'iso'


# --------------------------------------------------------------------------------------------- GerberObject.isolate

def run_isolate(app, gerber, **kwargs):
    """Calls isolate(); returns ({object name: Geometry object}, the pass numbers of the computed envelopes)."""
    created = {}

    def new_object(kind, name, initialize, plot=True, **kw):
        obj = GeometryObject(name, app)
        assert initialize(obj, app) != 'fail'
        created[name] = obj
        return 'ok'

    app.app_obj.new_object = Mock(side_effect=new_object)
    envelope = Mock(wraps=gerber.generate_envelope)
    gerber.generate_envelope = envelope
    gerber.isolate(dia=DIA, overlap=OVERLAP, iso_type=2, plot=False, **kwargs)
    return created, [c.kwargs['nr_passes'] for c in envelope.call_args_list]


def test_combined_passes_stop_at_the_boundary(app):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    created, computed = run_isolate(app, gerber, passes=PASSES, combine=True, outname='iso', boundary=board)

    # the last pass computed is the first one completely outside the board; it is not kept
    made = len(computed) - 1
    assert 1 < made < PASSES
    paths = created['iso'].solid_geometry
    assert paths and all(isinstance(p, (LineString, LinearRing)) for p in paths)
    assert length_outside(paths, board) == pytest.approx(0.0)
    assert created['iso'].tools[1]['solid_geometry'] == paths
    assert reports(app) == ['[success] iso: %d of %d passes, the area inside the boundary is cleared.' %
                            (made, PASSES)]


def test_without_a_boundary_all_the_passes_are_made(app):
    gerber = make_gerber(app, name='g')
    created, computed = run_isolate(app, gerber, passes=3, combine=True, outname='iso')
    assert computed == [0, 1, 2]
    assert reports(app) == []
    # the envelopes are kept as they are (polygons), not clipped to paths
    assert all(isinstance(g, Polygon) for g in created['iso'].solid_geometry)


def test_the_report_warns_when_all_the_passes_are_inside(app):
    gerber = make_gerber(app, name='g')
    run_isolate(app, gerber, passes=2, combine=True, outname='iso', boundary=board_of(gerber))
    assert len(reports(app)) == 1
    assert reports(app)[0].startswith('[WARNING_NOTCL] iso: all 2 passes made')


def test_trace_the_boundary_adds_its_outline_once(app):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    created, __ = run_isolate(app, gerber, passes=3, combine=True, outname='iso', boundary=board,
                              trace_boundary=True)
    traced = [g for g in created['iso'].solid_geometry if isinstance(g, LinearRing) and Polygon(g).equals(board)]
    assert len(traced) == 1


def test_separate_passes_stop_at_the_boundary(app):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    created, computed = run_isolate(app, gerber, passes=PASSES, combine=False, boundary=board)
    assert len(created) == len(computed) - 1 < PASSES
    for obj in created.values():
        assert length_outside(obj.solid_geometry, board) == pytest.approx(0.0)
    assert reports(app)[-1].startswith('[success] g: %d of %d passes' % (len(created), PASSES))


@pytest.mark.parametrize('combine', [True, False], ids=['combined', 'separate'])
def test_no_pass_inside_the_boundary_fails(app, combine):
    gerber = make_gerber(app, name='g')
    initialized = []

    def new_object(kind, name, initialize, plot=True, **kw):
        initialized.append(initialize(GeometryObject(name, app), app))
        return 'fail' if initialized[-1] == 'fail' else 'ok'

    app.app_obj.new_object = Mock(side_effect=new_object)
    # with trace_boundary an object holding only the outline must not be made either
    result = gerber.isolate(dia=DIA, passes=PASSES, overlap=OVERLAP, iso_type=2, plot=False, combine=combine,
                            outname='iso' if combine else None, boundary=far_box_of(gerber), trace_boundary=True)
    assert result == 'fail'
    assert initialized == (['fail'] if combine else [])
    assert reports(app) == [NO_PATH_INSIDE % ('iso' if combine else 'g')]


# ------------------------------------------------------------------------------------------------ Tcl isolate command

def run_tcl(app, gerber, edge, *argv):
    app.shell = Mock()
    objects = {'g': gerber, 'edge': edge}
    app.collection.get_by_name = Mock(side_effect=objects.get)
    cmd = TclCommandIsolate(app)
    args, unnamed = cmd.check_args(('g', '-dia', str(DIA), '-overlap', str(OVERLAP)) + argv)
    return cmd.execute(args, unnamed)


def test_tcl_boundary_is_the_area_enclosed_by_the_outline_object(app):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    # the outline as drawn in an Edge Cuts Gerber: a 0.1 mm band
    edge = SimpleNamespace(obj_options={'name': 'edge'}, solid_geometry=[board.exterior.buffer(0.05)])
    created = {}

    def new_object(kind, name, initialize, plot=True, **kw):
        obj = GeometryObject(name, app)
        assert initialize(obj, app) != 'fail'
        created[name] = obj

    app.app_obj.new_object = Mock(side_effect=new_object)
    run_tcl(app, gerber, edge, '-passes', str(PASSES), '-boundary', 'edge', '-trace_boundary', '1')

    area = outline_area(edge.solid_geometry)
    paths = created['g_iso'].solid_geometry
    assert length_outside(paths, area) == pytest.approx(0.0)
    assert sum(1 for g in paths if isinstance(g, LinearRing) and Polygon(g).equals(area)) == 1
    assert reports(app)[0].startswith('[success] g_iso: ')


def test_tcl_boundary_errors(app):
    gerber = make_gerber(app, name='g')
    with pytest.raises(ValueError, match='Object not found: missing'):
        run_tcl(app, gerber, None, '-boundary', 'missing')

    open_outline = SimpleNamespace(obj_options={'name': 'edge'},
                                   solid_geometry=[LineString([(0, 0), (40, 0), (40, 40)]).buffer(0.05)])
    with pytest.raises(ValueError, match='no outline that encloses an area'):
        run_tcl(app, gerber, open_outline, '-boundary', 'edge')
    app.app_obj.new_object.assert_not_called()


@pytest.mark.parametrize('combine', ['1', '0'], ids=['combined', 'separate'])
def test_tcl_fails_when_no_pass_is_inside_the_boundary(app, combine):
    gerber = make_gerber(app, name='g')
    edge = SimpleNamespace(obj_options={'name': 'edge'}, solid_geometry=[far_box_of(gerber).exterior.buffer(0.05)])
    app.app_obj.new_object = Mock(side_effect=lambda kind, name, initialize, plot=True, **kw:
                                  initialize(GeometryObject(name, app), app))
    result = run_tcl(app, gerber, edge, '-passes', str(PASSES), '-combine', combine, '-boundary', 'edge',
                     '-trace_boundary', '1')
    # a script stops here instead of making the CNC job of an empty (or outline only) isolation
    with pytest.raises(ValueError, match='Command failed: isolate'):
        TclCommandIsolate(app).check_result(result)


# -------------------------------------------------------------------------------------------------- Isolation Plugin

@pytest.fixture
def plugin(_headless_qt):  # noqa: F811
    tool = ToolIsolation(make_tool_app())
    tool.decimals = 4
    yield tool
    # delete the widgets now, while this module's QApplication is alive
    sip.delete(tool)


def run_plugin(plugin, gerber, combine, passes=PASSES, e_passes=0, boundary=None, trace_boundary=False,
               envelope=None, **kwargs):
    """Calls isolate(); envelope: a stand-in for generate_envelope(), else the real one is used."""
    data = {k: deepcopy(v) for k, v in AppDefaults().defaults.items() if k.startswith('tools_')}
    data.update(tools_iso_isotype='full', tools_iso_passes=passes, tools_iso_overlap=OVERLAP,
                tools_iso_milling_type='cl')
    storage = {1: {'tooldia': DIA, 'data': data, 'solid_geometry': []}}
    created = {}

    def new_object(kind, name, initialize, **kwargs):
        obj = SimpleNamespace(obj_options={'name': name})
        if initialize(obj, plugin.app) == 'fail':
            return 'fail'
        created[name] = obj

    plugin.app.app_obj.new_object.side_effect = new_object
    spy = Mock(side_effect=envelope) if envelope else Mock(wraps=plugin.generate_envelope)
    plugin.generate_envelope = spy
    # geometry: the whole object (with None the separate passes need the fix of the 'All' selection)
    options = dict(iso_except=False, e_passes=e_passes, area_except=False, area_shape='square', rest=False,
                   sel_type=0, tip_shape='C1', iso_simplification=False, simplification_tol=0.001,
                   boundary=boundary, trace_boundary=trace_boundary)
    options.update(kwargs)
    plugin.isolate(gerber, [1], storage, geometry=gerber.solid_geometry, plot=False, combine=combine, **options)
    return created, [c.kwargs['nr_passes'] for c in spy.call_args_list]


def test_plugin_combined_passes_stop_at_the_boundary(app, plugin):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    created, computed = run_plugin(plugin, gerber, combine=True, boundary=board, trace_boundary=True)

    made = len(computed) - 1
    assert 1 < made < PASSES
    paths = created['g_iso_combined'].solid_geometry
    assert length_outside(paths, board) == pytest.approx(0.0)
    assert sum(1 for g in paths if isinstance(g, LinearRing) and Polygon(g).equals(board)) == 1
    messages = [c.args[0] for c in plugin.app.inform.emit.call_args_list]
    assert '[success] g_0.5000: %d of %d passes, the area inside the boundary is cleared.' % (made, PASSES) \
        in messages


def test_plugin_pad_passes_start_after_the_last_pass_made(plugin):
    # the passes are discs growing around the centre of a 10 x 10 board (radius 1 + pass number): pass 7 (radius 8)
    # is the first one completely outside it, so 7 passes are made
    board = box(0, 0, 10, 10)
    # a pad flash that records the offsets of its extra pad passes
    pad = SimpleNamespace(buffer=Mock(side_effect=lambda offset, steps: Point(5, 5).buffer(0.5 + offset)))
    source = SimpleNamespace(obj_options={'name': 'g'}, solid_geometry=[Point(5, 5).buffer(0.5)],
                             isolation_buffers=Mock(return_value=None),
                             tools={10: {'geometry': [{'solid': pad, 'follow': Point(5, 5)}]}})
    __, computed = run_plugin(plugin, source, combine=True, e_passes=2, boundary=board,
                              envelope=lambda iso_obj, offset, invert, nr_passes=0, **kw:
                              [Point(5, 5).buffer(1 + nr_passes)])
    assert len(computed) - 1 == 7

    # the pad passes are the passes number 7 and 8, not 100 and 101 (after the requested passes)
    offsets = [c.args[0] for c in pad.buffer.call_args_list]
    assert offsets == pytest.approx([DIA * (2 * nr_pass + 1) / 2.0 for nr_pass in (7, 8)])


def test_plugin_separate_passes_stop_at_the_boundary(app, plugin):
    gerber = make_gerber(app, name='g')
    board = board_of(gerber)
    created, computed = run_plugin(plugin, gerber, combine=False, boundary=board, trace_boundary=True)
    assert len(created) == len(computed) - 1 < PASSES
    for obj in created.values():
        assert length_outside(obj.solid_geometry, board) == pytest.approx(0.0)
    # the boundary is traced once, as a closed path, in the object of the first pass
    traced = [[g for g in obj.solid_geometry if isinstance(g, LinearRing) and Polygon(g).equals(board)]
              for obj in created.values()]
    assert [len(t) for t in traced] == [1] + [0] * (len(created) - 1)


@pytest.mark.parametrize('combine', [True, False], ids=['combined', 'separate'])
def test_plugin_no_pass_inside_the_boundary_makes_no_object(app, plugin, combine):
    gerber = make_gerber(app, name='g')
    created, computed = run_plugin(plugin, gerber, combine=combine, boundary=far_box_of(gerber), trace_boundary=True)
    assert computed == [0]
    # not even an object that holds only the traced outline
    assert created == {}
    messages = [c.args[0] for c in plugin.app.inform.emit.call_args_list]
    assert NO_PATH_INSIDE % 'g_0.5000' in messages
    assert not any(m.startswith('[success]') for m in messages)


def test_plugin_without_a_boundary_makes_all_the_passes(app, plugin):
    gerber = make_gerber(app, name='g')
    __, computed = run_plugin(plugin, gerber, combine=True, passes=3)
    assert computed == [0, 1, 2]


def test_plugin_boundary_from_the_ui(plugin):
    edge = SimpleNamespace(obj_options={'name': 'edge'}, solid_geometry=[box(0, 0, 40, 30).exterior.buffer(0.05)])
    # (the collection model itself stays: the object comboboxes use it)
    plugin.app.collection.get_by_name = Mock()
    assert plugin.get_boundary_area() is None

    plugin.ui.boundary_cb.set_value(True)
    plugin.app.collection.get_by_name.return_value = edge
    assert plugin.get_boundary_area().equals(outline_area(edge.solid_geometry))

    edge.solid_geometry = [LineString([(0, 0), (40, 0), (40, 30)]).buffer(0.05)]
    assert plugin.get_boundary_area() == 'fail'
    plugin.app.collection.get_by_name.return_value = None
    assert plugin.get_boundary_area() == 'fail'
    messages = [c.args[0] for c in plugin.app.inform.emit.call_args_list]
    assert messages == ['[ERROR_NOTCL] The boundary object has no outline that encloses an area: edge',
                        '[ERROR_NOTCL] No boundary object is selected.']


@pytest.mark.parametrize('mode', ['combined', 'separate', 'rest'])
@pytest.mark.parametrize('restriction', ['selection', 'exclusion'])
def test_boundary_trace_respects_machining_scope(app, plugin, mode, restriction):
    gerber = make_gerber(app, name='g')
    gerber.solid_geometry = [Point(4, 5).buffer(0.5)]
    board = box(0, 0, 10, 10)
    allowed = box(0, 0, 5, 10)
    options = dict(limited_area=[allowed])
    if restriction == 'exclusion':
        excluded = box(5, -1, 11, 11)
        plugin.app.collection.get_by_name = Mock(return_value=SimpleNamespace(solid_geometry=[excluded]))
        plugin.ui.except_cb.set_value(True)
        options = dict(iso_except=True)
    if mode == 'rest':
        plugin.ui.tools_table = SimpleNamespace(
            selectedItems=lambda: [SimpleNamespace(row=lambda: 0)],
            item=lambda row, col: SimpleNamespace(text=lambda: str(DIA)))
    created, __ = run_plugin(plugin, gerber, combine=mode != 'separate', passes=3,
                             boundary=board, trace_boundary=True, rest=mode == 'rest', **options)
    assert created
    for obj in created.values():
        assert length_outside(obj.solid_geometry, allowed) == pytest.approx(0.0)
        for tool in obj.tools.values():
            assert length_outside(tool['solid_geometry'], allowed) == pytest.approx(0.0)


@pytest.mark.parametrize('mode', ['combined', 'separate', 'rest'])
def test_simplified_boundary_paths_stay_inside_the_boundary(app, plugin, mode):
    gerber = make_gerber(app, name='g')
    gerber.solid_geometry = [Point(4, 5).buffer(0.5)]
    board = Polygon([(0, 0), (10, 0), (10, 10), (5.1, 10), (5, 9.95), (4.9, 10), (0, 10)])
    if mode == 'rest':
        plugin.ui.tools_table = SimpleNamespace(
            selectedItems=lambda: [SimpleNamespace(row=lambda: 0)],
            item=lambda row, col: SimpleNamespace(text=lambda: str(DIA)))
    created, __ = run_plugin(plugin, gerber, combine=mode != 'separate', passes=3,
                             boundary=board, trace_boundary=True, rest=mode == 'rest',
                             iso_simplification=True, simplification_tol=0.1)
    assert created
    for obj in created.values():
        assert length_outside(obj.solid_geometry, board) == pytest.approx(0.0)
        for tool in obj.tools.values():
            assert length_outside(tool['solid_geometry'], board) == pytest.approx(0.0)


@pytest.mark.parametrize('combine', [True, False], ids=['combined', 'separate'])
@pytest.mark.parametrize('use_plugin', [True, False], ids=['plugin', 'object'])
def test_empty_pass_does_not_skip_a_disconnected_boundary(app, plugin, combine, use_plugin):
    gerber = make_gerber(app, name='g')
    gerber.solid_geometry = [Point(0, 0).buffer(0.5)]
    second = box(5, -1, 7, 1)
    board = shapely.MultiPolygon([box(-1, -1, 1, 1), second])
    if use_plugin:
        created, __ = run_plugin(plugin, gerber, combine=combine, passes=20, boundary=board)
    else:
        created, __ = run_isolate(app, gerber, combine=combine, passes=20, boundary=board)
    paths = [g for obj in created.values() for g in obj.solid_geometry]
    assert unary_union(paths).intersection(second).length > 0


@pytest.mark.parametrize('combine', [True, False], ids=['combined', 'separate'])
@pytest.mark.parametrize('use_plugin', [True, False], ids=['plugin', 'object'])
def test_disconnected_boundary_reports_the_last_pass_with_paths(app, plugin, combine, use_plugin):
    # path radii 0.75, 1.25, ...: the passes 10 to 13 (radius 5.25 to 6.75) reach the second box; the pass 14
    # (radius 7.25) encloses the whole boundary, so the passes stop there
    gerber = make_gerber(app, name='g')
    gerber.solid_geometry = [Point(0, 0).buffer(0.5)]
    board = shapely.MultiPolygon([box(-1, -1, 1, 1), box(5, -1, 7, 1)])
    if use_plugin:
        plugin.app.inform.emit.reset_mock()
        __, computed = run_plugin(plugin, gerber, combine=combine, passes=20, boundary=board)
        messages = [c.args[0] for c in plugin.app.inform.emit.call_args_list if 'passes' in str(c.args[0])]
    else:
        app.inform.emit.reset_mock()
        __, computed = run_isolate(app, gerber, combine=combine, passes=20, boundary=board, outname='iso')
        messages = reports(app)
    assert messages == ['[success] %s: 13 of 20 passes, the area inside the boundary is cleared.' %
                        messages[0].split(': ')[0].split('] ')[1]]
    assert len(computed) == 14


@pytest.mark.parametrize('combine', [True, False], ids=['combined', 'separate'])
def test_unreached_disconnected_boundary_makes_no_trace_only_object(app, plugin, combine):
    gerber = make_gerber(app, name='g')
    board = shapely.MultiPolygon([far_box_of(gerber), box(200, 200, 210, 210)])
    created, __ = run_plugin(plugin, gerber, combine=combine, passes=3, boundary=board, trace_boundary=True)
    assert not created
