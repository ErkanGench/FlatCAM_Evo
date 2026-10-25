"""Isolation plugin: isolate() with the passes not combined and no specific geometry.

With 'Combine' off and the selection 'All' or 'Area Selection', ToolIsolation.isolate() gets geometry=None. It called
flatten_shapely_geometry(None), which raises NotImplementedError, so no Geometry object was made. The tests build the
real ToolIsolation headless and isolate a parsed Gerber object (fixtures of tests.helpers_objects).
"""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from defaults import AppDefaults
from appObjects.GeometryObject import GeometryObject
from appPlugins.ToolIsolation import ToolIsolation

from test_plugin_geometry_bases import make_tool_app
from tests.helpers_objects import app, _headless_qt, make_gerber  # noqa: F401,E402

DIA = 0.2


def tools_storage(passes):
    data = {k: deepcopy(v) for k, v in AppDefaults().defaults.items() if k.startswith('tools_')}
    data.update(tools_iso_passes=passes, tools_iso_overlap=10, tools_iso_isotype='full',
                tools_iso_milling_type='cl')
    return {1: {'tooldia': DIA, 'data': data, 'solid_geometry': []}}


@pytest.fixture(scope='module')
def tool(_headless_qt):  # noqa: F811
    return ToolIsolation(make_tool_app())


class Created(dict):
    """{object name: Geometry object built by the init callback}; .result is what isolate() returned."""
    result = None


def run_isolate(tool, app, gerber, passes, storage=None, sel_tools=(1,), **kwargs):
    """Calls the plugin isolate() (combine off unless given)."""
    created = Created()

    def new_object(kind, name, initialize, plot=True, **kw):
        assert kind == 'geometry'
        obj = GeometryObject(name, app)
        if initialize(obj, app) == 'fail':
            return 'fail'
        created[name] = obj
        return 'ok'

    tool.app.app_obj.new_object = Mock(side_effect=new_object)
    options = dict(combine=False, iso_except=False, e_passes=0, area_except=False, area_shape='square', rest=False,
                   sel_type=0, tip_shape='C1', iso_simplification=False, simplification_tol=0.001)
    options.update(kwargs)
    created.result = tool.isolate(isolated_obj=gerber, sel_tools=list(sel_tools), plot=False,
                                  tools_storage=storage if storage is not None else tools_storage(passes), **options)
    return created


def two_tools(passes=1):
    """Tool 1 (0.2) and tool 2 (0.5)."""
    storage = tools_storage(passes)
    storage[2] = deepcopy(storage[1])
    storage[2]['tooldia'] = 0.5
    return storage


def pads_gerber(app):
    """2 pads 20 mm apart (the second one is not selected in the tests) and a clear flash without 'solid'."""
    gerber = make_gerber(app, name='g')
    pad_a, pad_b = Point(0, 0).buffer(1), Point(20, 0).buffer(1)
    gerber.solid_geometry = [pad_a, pad_b]
    gerber.tools = {10: {'geometry': [{'solid': pad_a, 'follow': Point(0, 0)},
                                      {'solid': pad_b, 'follow': Point(20, 0)},
                                      {'follow': Point(5, 5)}]}}
    return gerber, pad_a, pad_b


def wkb_set(geometries):
    return sorted(g.wkb_hex for g in geometries if not g.is_empty)


@pytest.mark.parametrize('passes', [1, 3])
def test_whole_object_makes_one_geometry_per_pass(tool, app, passes):
    created = run_isolate(tool, app, make_gerber(app, name='g'), passes)

    names = ['g_0.2000_iso'] if passes == 1 else ['g_0.2000_iso%d' % (i + 1) for i in range(passes)]
    assert sorted(created) == names
    for obj in created.values():
        assert len(obj.solid_geometry) > 0
        assert obj.tools[1]['tooldia'] == DIA
        assert obj.tools[1]['solid_geometry'] == obj.solid_geometry


def test_area_selection_with_separate_passes(tool, app):
    gerber = make_gerber(app, name='g')
    xmin, ymin, xmax, ymax = unary_union(gerber.solid_geometry).bounds
    area = box(xmin - 1, ymin - 1, (xmin + xmax) / 2, ymax + 1)

    created = run_isolate(tool, app, gerber, 2, limited_area=area)

    assert sorted(created) == ['g_0.2000_iso1', 'g_0.2000_iso2']
    for obj in created.values():
        assert len(obj.solid_geometry) > 0
        assert unary_union(obj.solid_geometry).within(area.buffer(1e-6))


# ------------------------------------------------------------------------------------------- the run and its tools

def test_a_run_leaves_the_plugin_tools_as_they_are_and_gives_each_object_its_own_data(tool, app):
    for combine in (False, True):
        storage = two_tools(2)
        storage[2]['solid_geometry'] = [box(0, 0, 1, 1)]  # kept from an earlier run
        before = deepcopy(storage)

        created = run_isolate(tool, app, make_gerber(app, name='g'), 2, storage=storage, combine=combine)

        assert created
        assert storage == before
        for name, obj in created.items():
            # only the selected tool, with the geometry of this run
            assert list(obj.tools) == [1]
            assert len(obj.tools[1]['solid_geometry']) > 0
            assert obj.tools[1]['data'] is not storage[1]['data']
            assert combine or obj.tools[1]['data']['name'] == name
        assert len({id(obj.tools[1]['data']) for obj in created.values()}) == len(created)


def test_no_object_is_made_for_an_empty_selection_a_stop_or_an_empty_area(tool, app, monkeypatch):
    gerber = make_gerber(app, name='g')
    # an empty selection is not the whole board
    for geometry in ([], Polygon()):
        for mode in (dict(), dict(combine=True), dict(combine=True, rest=True)):
            created = run_isolate(tool, app, gerber, 1, geometry=geometry, **mode)
            assert created.result == 'fail'
            assert not created
    # no geometry inside the area
    for combine in (False, True):
        assert not run_isolate(tool, app, gerber, 1, combine=combine, limited_area=box(900, 900, 901, 901))
    # a stop by the user
    monkeypatch.setattr(tool.app, 'abort_flag', True)
    for combine in (False, True):
        created = run_isolate(tool, app, gerber, 2, combine=combine)
        assert created.result == 'fail'
        assert not created


def test_the_object_diameter_is_the_one_of_its_largest_tool(tool, app):
    for order in ([1, 2], [2, 1]):
        created = run_isolate(tool, app, make_gerber(app, name='g'), 1, storage=two_tools(), sel_tools=order,
                              combine=True)

        (obj,) = created.values()
        assert sorted(obj.tools) == [1, 2]
        assert obj.obj_options['tools_mill_tooldia'] == '0.5'


# ------------------------------------------------------------------------------------------------------- pad passes

def test_pad_passes_follow_only_the_isolated_pads_and_start_after_the_last_pass(tool, app):
    gerber, pad_a, pad_b = pads_gerber(app)

    for combine in (False, True):
        (obj,) = run_isolate(tool, app, gerber, 1, geometry=[pad_a], combine=combine, e_passes=2).values()
        # the pass and the 2 pad rings of the first pad, nothing around the second pad
        assert len(obj.solid_geometry) == 3
        assert unary_union(obj.solid_geometry).bounds[2] < 3

    created = run_isolate(tool, app, gerber, 3, geometry=[pad_a], e_passes=1)
    first, second, last = (created['g_0.2000_iso%d' % n] for n in (1, 2, 3))
    assert len(first.solid_geometry) == len(second.solid_geometry) == 1
    assert len(last.solid_geometry) == 2
    # pass offsets 0.1, 0.28, 0.46 and the pad ring after them 0.64
    assert unary_union(second.solid_geometry).bounds[2] == pytest.approx(1.28, abs=0.02)
    assert unary_union(last.solid_geometry).bounds[2] == pytest.approx(1.64, abs=0.02)


# ------------------------------------------------------------------------------------------------- rest machining

def test_rest_machining_uses_the_selected_tools_largest_first_and_survives_a_failed_geometry(tool, app, monkeypatch):
    gerber, __, __ = pads_gerber(app)

    # the smaller tool first, as in the Tool Table: the 0.5 tool still goes first and isolates both pads
    for geometry in (None, MultiPolygon([Point(0, 0).buffer(1), Point(20, 0).buffer(1)])):
        created = run_isolate(tool, app, gerber, 1, storage=two_tools(), sel_tools=[1, 2], geometry=geometry,
                              combine=True, rest=True, forced_rest=False, order=1)

        (obj,) = created.values()
        assert list(obj.tools) == [2]
        assert unary_union(obj.solid_geometry).bounds[2] == pytest.approx(21.25, abs=0.02)

    monkeypatch.setattr(tool, 'generate_rest_geometry', Mock(return_value=('fail', 'fail')))
    created = run_isolate(tool, app, gerber, 1, combine=True, rest=True, forced_rest=False, order=0)
    assert created.result == 'fail'
    assert not created


def test_generate_buffer_takes_a_list_with_multipolygons(tool, app, monkeypatch):
    gerber, pad_a, pad_b = pads_gerber(app)
    gerber.solid_geometry = [MultiPolygon([pad_a, pad_b]), box(5, 5, 6, 6)]
    monkeypatch.setattr(tool.app, 'collection', Mock(get_by_name=Mock(return_value=gerber)))
    monkeypatch.setattr(tool.app.worker_task, 'emit', lambda task: task['fcn'](*task['params']))

    tool.on_generate_buffer()

    assert unary_union(gerber.solid_geometry).area == pytest.approx(unary_union([pad_a, pad_b]).area + 1, rel=1e-3)


# ------------------------------------------------------------------------------------ Area / Polygon selection modes

class FakeShapes:
    """The tool_shapes collection: {id: shape}."""
    def __init__(self):
        self.shapes, self.last = {}, 0

    def add_batch(self, items, **kw):
        ids = []
        for item in items:
            self.last += 1
            self.shapes[self.last] = item['shape']
            ids.append(self.last)
        return ids

    def remove(self, key, update=False):
        del self.shapes[key]

    def clear(self, update=False):
        self.shapes.clear()

    def redraw(self, *a, **kw):
        pass


class FakeSnapButton:
    def __init__(self, checked):
        self.checked = checked

    def isChecked(self):
        return self.checked

    def trigger(self):
        self.checked = not self.checked


class Click:
    def __init__(self, pos, button=1):
        self.pos, self.button = pos, button


@pytest.fixture
def sel_tool(tool, monkeypatch):
    """The plugin with a three pad object (centers 0, 10, 20 on x) and a fake canvas / shape collection."""
    gerber, __, __ = pads_gerber(None) if False else (None, None, None)
    pads = [Point(x, 0).buffer(1) for x in (0, 10, 20)]
    tool.grb_obj = Mock(solid_geometry=pads)
    tool.app.tool_shapes = FakeShapes()
    tool.app.selection_type = None
    tool.app.event_is_dragging = False
    tool.app.grid_status = lambda: False
    tool.app.plotcanvas.translate_coords = lambda p: (p[0], p[1])
    tool.app.ui.grid_snap_btn = FakeSnapButton(True)
    tool.area_sel_disconnect_flag = tool.poly_sel_disconnect_flag = False
    tool.end_selection_mode()
    monkeypatch.setattr(tool, '_selected_tool_ids', lambda: [1])
    monkeypatch.setattr(tool, 'isolate', Mock())
    monkeypatch.setattr(tool, 'draw_tool_selection_shape', Mock())
    tool.pads = pads
    yield tool
    tool.end_selection_mode()


def test_area_rectangle_and_select_all_select_each_polygon_once(sel_tool):
    sel_tool.selection_area_handler((-1.5, -1.5), (11.5, 1.5), True)
    assert len(sel_tool.poly_dict) == 2

    sel_tool.end_selection_mode()
    sel_tool.selection_area_handler((-1.5, -1.5), (9.5, 1.5), False)     # touches the pad at 10, not enclosing it
    assert len(sel_tool.poly_dict) == 2
    sel_tool.selection_area_handler((-1.5, -1.5), (9.5, 1.5), True)      # nothing new enclosed
    assert len(sel_tool.poly_dict) == 2

    sel_tool.end_selection_mode()
    sel_tool.grb_obj.solid_geometry = [MultiPolygon(sel_tool.pads[:2]), sel_tool.pads[2]]
    sel_tool.ui.object_combo.currentText = lambda: 'g'
    sel_tool.app.collection = Mock(get_by_name=Mock(return_value=sel_tool.grb_obj))
    sel_tool.on_select_all_polygons()
    sel_tool.on_select_all_polygons()
    assert len(sel_tool.poly_dict) == 3 == len(sel_tool.app.tool_shapes.shapes)


def test_polygon_clicks_add_and_remove_and_the_right_click_isolates_in_the_worker(sel_tool):
    tasks = []
    sel_tool.app.worker_task.emit = tasks.append
    sel_tool.on_poly_mouse_click_release(Click((10, 0.5)))
    sel_tool.on_poly_mouse_click_release(Click((20, 0)))
    assert sorted(p.centroid.x for p in sel_tool.poly_dict.values()) == pytest.approx([10, 20])

    sel_tool.on_poly_mouse_click_release(Click((10, 0.5)))
    assert [p.centroid.x for p in sel_tool.poly_dict.values()] == pytest.approx([20])
    assert len(sel_tool.app.tool_shapes.shapes) == 1

    sel_tool.ui.combine_passes_cb.set_value(True)
    sel_tool.on_poly_mouse_click_release(Click((0, 0), button=2))
    sel_tool.ui.combine_passes_cb.set_value(False)    # after the click: the run keeps the value of the click
    sel_tool.isolate.assert_not_called()
    assert not sel_tool.poly_dict and not sel_tool.app.tool_shapes.shapes
    (task,) = tasks
    task['fcn'](*task['params'])
    assert len(sel_tool.isolate.call_args.kwargs['geometry']) == 1
    assert sel_tool.isolate.call_args.kwargs['combine'] is True


def test_square_first_corner_is_the_clicked_point_and_escape_ends_the_selection(sel_tool):
    sel_tool.app.plotcanvas.translate_coords = lambda p: (p[0] * 2, p[1] * 2)   # the scene position of a click
    sel_tool.ui.area_shape_radio.set_value('square')
    sel_tool.on_mouse_release(Click((1, 3)))
    assert tuple(sel_tool.cursor_pos) == (2, 6)
    assert sel_tool.first_click is True

    sel_tool.on_key_press(Mock(key='Escape'))
    sel_tool.on_mouse_release(Click((5, 5)))
    assert sel_tool.first_click is True and sel_tool.sel_rect == []


def test_area_right_click_isolates_in_the_worker_and_leaves_clean_state(sel_tool):
    tasks = []
    sel_tool.app.worker_task.emit = tasks.append
    sel_tool.ui.area_shape_radio.set_value('square')
    for pos in [(0, 0), (4, 4), (0, 0, 2)]:
        sel_tool.on_mouse_release(Click(pos[:2], button=pos[2] if len(pos) > 2 else 1))

    sel_tool.isolate.assert_not_called()
    assert sel_tool.sel_rect == [] and sel_tool.first_click is False
    (task,) = tasks
    task['fcn'](*task['params'])
    assert sel_tool.isolate.call_args.kwargs['limited_area'].area == pytest.approx(16)


def test_polygon_mode_restores_the_grid_snap_once_whatever_the_generate_clicks(sel_tool):
    sel_tool.ui.select_combo.set_value(2)
    snap = sel_tool.app.ui.grid_snap_btn

    sel_tool.start_selection_mode(sel_tool.grb_obj, 2)
    sel_tool.start_selection_mode(sel_tool.grb_obj, 2)
    assert snap.isChecked() is False
    sel_tool.on_key_press(Mock(key='Escape'))

    assert snap.isChecked() is True


# ------------------------------------------------------------------ several Gerber objects in one run

@pytest.mark.parametrize('multi, selection, expected', [
    (True, 0, ['a_0.2000_iso', 'b_0.2000_iso']),
    (True, 3, ['a_0.2000_iso', 'b_0.2000_iso']),
    (False, 0, ['a_0.2000_iso']),
])
def test_selected_gerbers_are_isolated_in_one_run(tool, app, multi, selection, expected):
    gerber_a, gerber_b = make_gerber(app, name='a'), make_gerber(app, name='b')
    created = Created()

    def new_object(kind, name, initialize, plot=True, **kw):
        obj = GeometryObject(name, app)
        if initialize(obj, app) == 'fail':
            return 'fail'
        created[name] = obj
        return 'ok'

    objects = {'a': gerber_a, 'b': gerber_b}
    tool.app.app_obj.new_object = Mock(side_effect=new_object)
    tool.app.worker_task.emit = lambda task: task['fcn'](*task['params'])
    tool.app.collection.get_by_name = lambda name: objects.get(name)
    tool.app.collection.get_selected = lambda: [gerber_a, gerber_b]
    tool.iso_tools = tools_storage(1)
    tool.build_ui()
    tool.ui.tools_table.selectAll()
    tool.ui.object_combo.currentText = lambda: 'a'
    tool.ui.valid_cb.set_value(False)
    tool.ui.combine_passes_cb.set_value(False)
    tool.ui.rest_cb.set_value(False)
    tool.ui.except_cb.set_value(False)
    tool.ui.simplify_cb.set_value(False)
    tool.ui.pad_passes_entry.set_value(0)
    tool.ui.select_combo.set_value(selection)
    tool.ui.multi_objects_cb.set_value(multi)
    if selection == 3:
        tool.ui.reference_combo.get_value = lambda: 'ref'
        objects['ref'] = make_gerber(app, name='ref')
        objects['ref'].solid_geometry = []

    tool.on_iso_button_click()

    assert sorted(created) == expected


def test_the_run_uses_the_widget_values_of_the_generate_click(tool, app):
    gerber = make_gerber(app, name='a')
    created = Created()

    def new_object(kind, name, initialize, plot=True, **kw):
        obj = GeometryObject(name, app)
        created[name] = obj if initialize(obj, app) != 'fail' else None
        return 'ok'

    tasks = []
    tool.app.app_obj.new_object = Mock(side_effect=new_object)
    tool.app.worker_task.emit = tasks.append
    tool.app.collection.get_by_name = lambda name: gerber
    tool.app.collection.get_selected = lambda: []
    tool.iso_tools = tools_storage(2)
    tool.build_ui()
    tool.ui.tools_table.selectAll()
    tool.ui.object_combo.currentText = lambda: 'a'
    for cb, value in ((tool.ui.valid_cb, False), (tool.ui.combine_passes_cb, True), (tool.ui.rest_cb, False),
                      (tool.ui.except_cb, False), (tool.ui.simplify_cb, False), (tool.ui.pad_passes_entry, 0),
                      (tool.ui.select_combo, 0), (tool.ui.multi_objects_cb, False)):
        cb.set_value(value)

    tool.on_iso_button_click()
    tool.ui.combine_passes_cb.set_value(False)      # before the worker runs
    (task,) = tasks
    task['fcn'](*task['params'])

    assert sorted(created) == ['a_iso_combined']
