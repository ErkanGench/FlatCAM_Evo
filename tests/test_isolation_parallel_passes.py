"""Isolation passes buffered ahead in parallel threads (camlib.PassBuffers) give the same paths as one pass at a time.

Geometry.isolation_geometry() buffers the features of a pass one by one in a Python loop, and the passes were made one
after the other, on one processor core. PassBuffers buffers a batch of passes in threads (the vectorized Shapely calls
release the GIL). The result must be identical, so the G-code does not change. The object tests use the headless
fixtures of test_unify_characterization.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from appCommon.Common import GracefulException
from appObjects.GeometryObject import GeometryObject
from appPlugins.ToolIsolation import ToolIsolation
from camlib import PassBuffers, flatten_shapely_geometry

from test_unify_characterization import _headless_qt, app, make_gerber  # noqa: F401  (fixtures)

DIA = 0.2
OVERLAP = 10  # percent
OFFSETS = [0.1 * ((2 * nr + 1) / 2.0) - nr * 0.1 * 0.1 for nr in range(20)]


def features():
    # pads and traces close to each other, so the buffers of the passes merge
    geo = [Point(x * 1.3, y * 1.1).buffer(0.4, 16) for x in range(12) for y in range(9)]
    geo += [LineString([(0, y * 1.1), (14, y * 1.1 + 0.3)]).buffer(0.1, 16) for y in range(9)]
    geo.append(box(20, 0, 26, 3).difference(box(21, 1, 25, 2)))
    return geo


def one_pass(geo, offset, quad_segs=16):
    """The loop of Geometry.isolation_geometry() over the features."""
    return unary_union([g.buffer(offset, quad_segs, join_style='round') for g in geo])


def wkb_list(geometries):
    return [g.wkb for g in flatten_shapely_geometry(geometries)]


@pytest.fixture
def three_threads():
    """3 threads (batches of 3 passes); yields the mock that counts the passes taken from PassBuffers."""
    real_get = PassBuffers.get
    with patch('camlib.os.cpu_count', return_value=3), \
            patch.object(PassBuffers, 'get', autospec=True, side_effect=real_get) as get:
        yield get


# ---------------------------------------------------------------------------------------------------------------
# PassBuffers
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('workers', [1, 3, 8])
def test_same_geometry_as_one_pass_at_a_time(workers):
    geo = features()
    buffers = PassBuffers(geo, OFFSETS, 16, workers=workers)
    for nr_pass, offset in enumerate(OFFSETS):
        assert buffers.get(nr_pass).wkb == one_pass(geo, offset).wkb, 'pass %d' % nr_pass


def test_passes_are_buffered_in_batches_of_the_number_of_workers():
    buffered = []

    def fake_buffer(self, nr_pass):
        buffered.append(nr_pass)
        return nr_pass

    buffers = PassBuffers(features(), OFFSETS[:10], 16, workers=4)
    with patch.object(PassBuffers, '_buffer', autospec=True, side_effect=fake_buffer):
        assert buffers.get(0) == 0
        assert sorted(buffered) == [0, 1, 2, 3]
        assert [buffers.get(nr) for nr in range(1, 5)] == [1, 2, 3, 4]
        assert sorted(buffered) == list(range(8))
        # the last batch stops at the last pass
        assert [buffers.get(nr) for nr in range(5, 10)] == list(range(5, 10))
    assert sorted(buffered) == list(range(10))


def test_one_pass_is_buffered_in_the_calling_thread():
    with patch('camlib.ThreadPoolExecutor') as executor:
        buffers = PassBuffers(features(), OFFSETS[:1], 16, workers=8)
        assert not buffers.get(0).is_empty
    executor.assert_not_called()


def test_abort_is_raised_in_the_caller():
    buffers = PassBuffers(features(), OFFSETS, 16, workers=4, abort=lambda: True)
    with pytest.raises(GracefulException):
        buffers.get(0)


def test_zero_offset_and_empty_geometry():
    geo = features()
    assert PassBuffers(geo, [0.0, 0.1], 16, workers=2).get(0).wkb == unary_union(geo).wkb
    assert PassBuffers([], OFFSETS[:2], 16, workers=2).get(0).is_empty


# ---------------------------------------------------------------------------------------------------------------
# GerberObject.isolate() (Tcl isolate)
# ---------------------------------------------------------------------------------------------------------------

def run_isolate(app, gerber, **kwargs):
    """Calls isolate() and returns {object name: Geometry object built by the init callback}."""
    created = {}

    def new_object(kind, name, initialize, plot=True, **kw):
        obj = GeometryObject(name, app)
        assert initialize(obj, app) != 'fail'
        created[name] = obj
        return 'ok'

    app.app_obj.new_object = Mock(side_effect=new_object)
    gerber.isolate(dia=DIA, overlap=OVERLAP, iso_type=2, milling_type='cl', plot=False, **kwargs)
    return created


@pytest.mark.parametrize('combine', [True, False])
def test_isolate_makes_the_same_paths_as_one_pass_at_a_time(app, three_threads, combine):
    gerber = make_gerber(app, name='g')
    passes = 7
    expected = []
    for nr in range(passes):
        offset = DIA * ((2 * nr + 1) / 2.0) - nr * (OVERLAP / 100.0) * DIA
        expected += wkb_list(gerber.generate_envelope(offset, 1, geometry=gerber.solid_geometry, nr_passes=nr))
    assert three_threads.call_count == 0

    created = run_isolate(app, gerber, passes=passes, combine=combine)

    assert three_threads.call_count == passes
    assert len(created) == (1 if combine else passes)
    assert [w for obj in created.values() for w in wkb_list(obj.solid_geometry)] == expected


def test_activity_text_shows_the_pass_and_is_cleared_after_it(app):
    # one vectorized call per pass: the pass number is shown instead of the progress of the features
    gerber = make_gerber(app, name='g')
    buffers = gerber.isolation_buffers(OFFSETS[:2], geometry=gerber.solid_geometry)
    app.proc_container.update_view_text.reset_mock()

    gerber.isolation_geometry(OFFSETS[1], geometry=gerber.solid_geometry, passes=1, buffers=buffers)

    texts = [c.args[0] for c in app.proc_container.update_view_text.call_args_list]
    assert texts == [' Pass 2', '']


# ---------------------------------------------------------------------------------------------------------------
# Isolation Plugin
# ---------------------------------------------------------------------------------------------------------------

def make_tool(app):
    tool = SimpleNamespace(app=app, decimals=4, validation_status=True, temp_shapes=Mock())
    tool.generate_envelope = lambda *args, **kwargs: ToolIsolation.generate_envelope(tool, *args, **kwargs)
    return tool


def tools_storage(passes, milling_type):
    return {1: {'tooldia': DIA, 'data': {
        'tools_iso_isotype': 'full', 'tools_iso_passes': passes, 'tools_iso_overlap': OVERLAP,
        'tools_iso_milling_type': milling_type, 'tools_mill_offset_type': 0, 'tools_mill_offset_value': 0.0,
        'tools_mill_tool_shape': 0}}}


def plugin_one_pass_at_a_time(tool, gerber, passes, mill_dir, negative_dia=False):
    expected = []
    for nr in range(passes):
        offset = DIA * ((2 * nr + 1) / 2.0000001) - nr * (OVERLAP / 100.0) * DIA
        if negative_dia:
            offset = -offset
        expected += wkb_list(ToolIsolation.generate_envelope(tool, gerber, offset, mill_dir,
                                                             geometry=gerber.solid_geometry, nr_passes=nr))
    return expected


@pytest.mark.parametrize('negative_dia', [False, True])
def test_plugin_combined_passes_are_the_same_as_one_pass_at_a_time(app, three_threads, negative_dia):
    gerber = make_gerber(app, name='g')
    tool = make_tool(app)
    tool.new_object = Mock()
    passes = 7
    expected = plugin_one_pass_at_a_time(tool, gerber, passes, 0, negative_dia=negative_dia)

    storage = tools_storage(passes, 'cl')
    ToolIsolation.combined_normal(tool, iso_obj=gerber, iso2geo=gerber.solid_geometry, tools_storage=storage,
                                  lim_area=None, sel_tools=[1], iso_except=False, extra_passes=0,
                                  negative_dia=negative_dia, plot=False, prog_plot='normal')

    assert three_threads.call_count == passes
    assert wkb_list(storage[1]['solid_geometry']) == expected
    tool.new_object.assert_called_once()


def test_plugin_separate_passes_are_the_same_as_one_pass_at_a_time(app, three_threads):
    gerber = make_gerber(app, name='g')
    tool = make_tool(app)
    passes = 7
    expected = plugin_one_pass_at_a_time(tool, gerber, passes, 1)
    created = []

    def new_object(kind, name, initialize, **kwargs):
        obj = SimpleNamespace(obj_options={'name': name})
        assert initialize(obj, app) != 'fail'
        created.append(obj)
        return obj

    tool.new_object = new_object
    ToolIsolation.isolate(tool, gerber, [1], tools_storage(passes, 'cv'), geometry=gerber.solid_geometry,
                          plot=False, combine=False, iso_except=False, e_passes=0, area_except=False,
                          area_shape='square', rest=False, sel_type=0, tip_shape='C1',
                          iso_simplification=False, simplification_tol=0.001)

    assert three_threads.call_count == passes
    assert len(created) == passes
    assert [w for obj in created for w in wkb_list(obj.solid_geometry)] == expected
