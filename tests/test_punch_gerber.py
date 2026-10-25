import math
import sys
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest
from shapely import Point, LineString, box
from shapely.ops import unary_union

from appParsers.feature_access import iter_features
from appPlugins.ToolPunchGerber.PunchGerber import ToolPunchGerber
from appPlugins.ToolPunchGerber.PunchGerberGen import punch_geometry
from tests.helpers_objects import _headless_qt, make_app, make_gerber  # noqa: F401

PUNCH_MODULE = sys.modules['appPlugins.ToolPunchGerber.PunchGerber']
ALL_ON = [True] * 5


def _circle_ap(x, y, size=1.0):
    pt = Point(x, y)
    return {'type': 'C', 'size': size, 'geometry': [{'follow': pt, 'solid': pt.buffer(size / 2, quad_segs=16)}]}


def _obround_ap(x, y, w=1.0, h=0.6):
    pt = Point(x, y)
    return {'type': 'O', 'size': math.hypot(w, h), 'width': w, 'height': h,
            'geometry': [{'follow': pt, 'solid': box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)}]}


def _am_ap(x, y, w=1.0, h=0.8):
    pt = Point(x, y)
    return {'type': 'AM', 'geometry': [{'follow': pt, 'solid': box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)}]}


def _solid(tools):
    return unary_union([r['solid'] for t in tools.values() for r in t['geometry'] if 'solid' in r])


def _clears(apertures):
    return [(a['size'], r['clear']) for a in apertures.values() for r in a['geometry'] if 'clear' in r]


def _run(tools, method='fixed', value=0.4, selected=None, **kw):
    return punch_geometry(_solid(tools), tools, list(tools) if selected is None else selected, method, value, 4,
                          ALL_ON, **kw)


def _exc(drills=(), slots=(), dia=0.4):
    tool = {'tooldia': dia, 'drills': list(drills), 'slots': list(slots)}
    geo = [p.buffer(dia / 2) for p in drills] + [LineString(s).buffer(dia / 2) for s in slots]
    return geo, {1: tool}


class FakeCollection:
    def __init__(self):
        self.items = []

    def get_list(self):
        return list(self.items)

    def get_active(self):
        return None

    def get_by_name(self, name):
        return next((o for o in self.items if o.obj_options['name'] == name), None)

    def index(self, row, column, parent=None):
        return SimpleNamespace(internalPointer=lambda: SimpleNamespace(obj=self.items[row]))


class Entry:
    def __init__(self, value=None):
        self.value = value

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value


class FakeTable:
    def __init__(self, apids):
        self.apids = apids

    def selectedItems(self):
        return [SimpleNamespace(text=lambda a=a: str(a)) for a in self.apids]

    def rowCount(self):
        return 0


@pytest.fixture
def setup():
    app = make_app()
    app.collection = FakeCollection()
    app.event_is_dragging = False
    app.plotcanvas = Mock()
    app.plotcanvas.translate_coords = lambda pos: pos
    app.on_mouse_click_over_plot = Mock()
    app.on_mouse_click_release_over_plot = Mock()
    app.ui = MagicMock()
    app.ui.grid_snap_btn.isChecked.return_value = False
    app.options['global_selection_shape'] = True
    counter = iter(range(1, 1000))
    app.tool_shapes = Mock()
    app.tool_shapes.add = Mock(side_effect=lambda **kw: next(counter))
    app.created = []

    def new_object(kind, name, initialize, **kwargs):
        obj = SimpleNamespace(obj_options={'name': name}, tools={}, solid_geometry=None,
                              regenerate_source=lambda name=None: None)
        initialize(obj, app)
        app.created.append(obj)
        return obj

    app.app_obj.new_object = new_object
    source = make_gerber(app, name='src')
    source.drawing_tolerance = 0.01
    source.clear_plot_apertures = Mock()
    app.collection.items.append(source)

    tool = ToolPunchGerber.__new__(ToolPunchGerber)
    tool.app = app
    tool.decimals = 4
    tool.old_name = ''
    tool.grb_obj = None
    tool.grid_status_memory = False
    tool.poly_sel_disconnect_flag = False
    tool.poly_dict = {}
    tool.manual_pads = []
    tool.old_selection_status = None
    tool.delete_moving_selection_shape = Mock()
    tool.delete_tool_selection_shape = Mock()
    tool.ui = SimpleNamespace(
        punch_type_radio=Entry('m'), method_punch=Entry('fixed'), dia_entry=Entry(0.1),
        circular_ring_entry=Entry(0.1), oblong_ring_entry=Entry(0.1), square_ring_entry=Entry(0.1),
        rectangular_ring_entry=Entry(0.1), other_ring_entry=Entry(0.1), factor_entry=Entry(50.0),
        circular_cb=Entry(True), oblong_cb=Entry(True), square_cb=Entry(True), rectangular_cb=Entry(True),
        other_cb=Entry(True), apertures_table=FakeTable(list(source.tools)),
        gerber_object_combo=SimpleNamespace(currentIndex=lambda: 0, rootModelIndex=lambda: None),
        exc_combo=SimpleNamespace(currentIndex=lambda: 0, rootModelIndex=lambda: None))
    tool.grb_obj = source
    return tool, app, source


def pads_of(tool, source):
    tool.grb_obj = source
    sel = [int(i.text()) for i in tool.ui.apertures_table.selectedItems()]
    return [(r.item_key, r.feature_index, r.solid.representative_point()) for r in iter_features(source)
            if r.item_key in sel and r.polarity == 'dark' and isinstance(r.follow, Point)]


def click(tool, point, button=1):
    tool.on_single_poly_mouse_release(SimpleNamespace(pos=(point.x, point.y), button=button))


def start_manual(tool):
    tool.on_punch_object_click()


def notebook_disabled(app):
    return app.ui.notebook.setDisabled.call_args[0][0]


def test_fixed_punches_circle_and_records_clear_and_aperture():
    tools = {10: _circle_ap(0, 0)}
    solid, aps = _run(tools, value=0.4)
    assert solid.area == pytest.approx(math.pi * (0.25 - 0.04), rel=0.02)
    assert not solid.intersects(Point(0, 0))
    assert not aps[10]['geometry'][0]['solid'].intersects(Point(0, 0))
    assert tools[10]['geometry'][0]['solid'].intersects(Point(0, 0))   # input untouched
    clears = _clears(aps)
    assert len(clears) == 1 and clears[0][0] == 0.4 and clears[0][1].equals(Point(0, 0))
    # hole almost as big as the pad still gets its clear record
    _, aps = _run(tools, value=0.99)
    assert len(_clears(aps)) == 1


@pytest.mark.parametrize('method,value,code', [
    ('fixed', 0.9, 'size'),            # smaller than diagonal 1.166 but not than the 0.6 side
    ('prop', 1.0, 'size'),
    ('ring', [0.0] * 5, 'size'),
    ('ring', [0.5] * 5, 'zero'),
    ('prop', 0.0, 'zero'),
])
def test_obround_error_codes(method, value, code):
    with pytest.raises(ValueError) as err:
        _run({10: _obround_ap(0, 0)}, method=method, value=value)
    assert err.value.args[0] == code


def test_ring_and_prop_hole_sizes():
    tools = {10: _circle_ap(0, 0)}
    _, aps = _run(tools, method='ring', value=[0.1] * 5)
    assert _clears(aps)[0][0] == pytest.approx(0.8)
    _, aps = _run(tools, method='prop', value=0.5)
    assert _clears(aps)[0][0] == pytest.approx(0.5)


def test_aperture_macro_fixed_uses_own_bounds():
    tools = {10: _am_ap(0, 0)}
    solid, aps = _run(tools, value=0.5)
    assert not solid.intersects(Point(0, 0))
    assert len(_clears(aps)) == 1
    with pytest.raises(ValueError) as err:
        _run(tools, value=0.8)
    assert err.value.args[0] == 'size'


def test_aperture_macro_first_record_clear_does_not_crash():
    tools = {10: _am_ap(0, 0)}
    tools[10]['geometry'].insert(0, {'clear': box(5, 5, 6, 6)})
    solid, _ = _run(tools, method='prop', value=0.5)
    assert not solid.intersects(Point(0, 0))


def test_empty_tools_and_nothing_to_punch():
    with pytest.raises(ValueError) as err:
        punch_geometry(box(0, 0, 1, 1), {}, [], 'fixed', 0.1, 4, ALL_ON)
    assert err.value.args[0] == 'empty'
    tools = {10: _circle_ap(0, 0)}
    for kw in ({'selected': []}, {'manual_pads': []}):
        with pytest.raises(ValueError) as err:
            _run(tools, **kw)
        assert err.value.args[0] == 'nothing'


def test_checkbox_off_skips_in_auto_but_not_in_manual():
    tools = {10: _circle_ap(0, 0), 11: _obround_ap(5, 0)}
    enabled = [False, True, True, True, True]
    solid, _ = punch_geometry(_solid(tools), tools, [10, 11], 'prop', 0.5, 4, enabled)
    assert solid.intersects(Point(0, 0)) and not solid.intersects(Point(5, 0))
    solid, _ = punch_geometry(_solid(tools), tools, [], 'prop', 0.5, 4, enabled,
                              manual_pads=[{'apid': 10, 'idx': 0}])
    assert not solid.intersects(Point(0, 0)) and solid.intersects(Point(5, 0))


def test_clear_flash_and_geometry_outside_tools_are_kept():
    tools = {10: _circle_ap(0, 0), 11: {'type': 'C', 'size': 1.0, 'geometry': [{'clear': Point(5, 0)}]}}
    extra = box(10, 10, 12, 12)
    src = unary_union([_solid({10: tools[10]}), extra])
    solid, aps = punch_geometry(src, tools, [10, 11], 'fixed', 0.4, 4, ALL_ON)
    assert solid.contains(Point(11, 11))
    assert len(_clears(aps)) == 2          # the original clear flash + the new hole
    assert aps[11]['geometry'] == [{'clear': Point(5, 0)}]


def test_nested_and_multipolygon_solid_geometry():
    tools = {10: _circle_ap(0, 0)}
    nested = [[tools[10]['geometry'][0]['solid']], [box(10, 10, 11, 11), [box(20, 20, 21, 21)]]]
    solid, _ = punch_geometry(nested, tools, [10], 'fixed', 0.4, 4, ALL_ON)
    assert solid.contains(Point(20.5, 20.5)) and not solid.intersects(Point(0, 0))


def test_steps_control_hole_smoothness():
    tools = {10: _circle_ap(0, 0, 2.0)}
    coarse, _ = _run(tools, value=1.0, steps=8)
    fine, _ = _run(tools, value=1.0, steps=128)
    hole_c = tools[10]['geometry'][0]['solid'].difference(coarse).area
    hole_f = tools[10]['geometry'][0]['solid'].difference(fine).area
    assert hole_c < hole_f < math.pi * 0.25 + 1e-6


def test_excellon_keeps_clear_features_cuts_only_selected_and_clears_slots():
    tools = {10: _circle_ap(0, 0), 11: _circle_ap(5, 0)}
    tools[12] = {'type': 'C', 'size': 1.0, 'geometry': [{'clear': box(8, 8, 9, 9)}]}
    drills = [Point(0, 0), Point(5, 0)]
    geo, dtools = _exc(drills, slots=[(Point(-0.2, 0), Point(0.2, 0))])
    src = unary_union([_solid({10: tools[10], 11: tools[11]}), box(20, 20, 21, 21)])
    solid, aps = punch_geometry(src, tools, [10], 'exc', None, 4, ALL_ON, drill_geometry=geo, drill_tools=dtools)
    assert not solid.intersects(Point(0, 0)) and solid.intersects(Point(5, 0))
    assert solid.contains(Point(20.5, 20.5))
    clears = [c for c in _clears(aps) if c[0] == 0.4]
    assert any(isinstance(g, Point) for _, g in clears) and any(isinstance(g, LineString) for _, g in clears)
    assert len(clears) == 2
    assert not aps[10]['geometry'][0]['solid'].intersects(Point(0, 0))


def test_excellon_manual_and_nothing():
    tools = {10: _circle_ap(0, 0), 11: _circle_ap(5, 0)}
    geo, dtools = _exc([Point(0, 0), Point(5, 0)])
    solid, aps = punch_geometry(_solid(tools), tools, [], 'exc', None, 4, ALL_ON, manual_pads=[{'apid': 11, 'idx': 0}],
                                drill_geometry=geo, drill_tools=dtools)
    assert solid.intersects(Point(0, 0)) and not solid.intersects(Point(5, 0))
    geo2, dtools2 = _exc([Point(50, 50)])
    with pytest.raises(ValueError) as err:
        punch_geometry(_solid(tools), tools, [10], 'exc', None, 4, ALL_ON, drill_geometry=geo2, drill_tools=dtools2)
    assert err.value.args[0] == 'nothing'


def test_right_click_with_pads_creates_punched_and_exits(setup):
    tool, app, source = setup
    pads = pads_of(tool, source)
    start_manual(tool)
    assert notebook_disabled(app) is True
    click(tool, pads[0][2])
    click(tool, pads[0][2], button=2)
    assert [o.obj_options['name'] for o in app.created] == ['src_punched']
    assert notebook_disabled(app) is False
    assert app.options['global_selection_shape'] is True
    app.plotcanvas.graph_event_connect.assert_any_call('mouse_press', app.on_mouse_click_over_plot)
    app.plotcanvas.graph_event_connect.assert_any_call('mouse_release', app.on_mouse_click_release_over_plot)


def test_empty_right_click_creates_nothing_and_exits(setup):
    tool, app, source = setup
    start_manual(tool)
    click(tool, Point(0, 0), button=2)
    assert app.created == []
    assert notebook_disabled(app) is False


def test_exception_in_punch_still_enables_notebook(setup):
    tool, app, source = setup
    pads = pads_of(tool, source)
    start_manual(tool)
    click(tool, pads[0][2])
    tool.on_manual_punch = Mock(side_effect=RuntimeError('boom'))
    with pytest.raises(RuntimeError):
        click(tool, pads[0][2], button=2)
    assert notebook_disabled(app) is False


def test_escape_exits_and_next_manual_punch_ignores_old_pads(setup):
    tool, app, source = setup
    pads = pads_of(tool, source)
    start_manual(tool)
    click(tool, pads[0][2])
    tool.on_key_press(SimpleNamespace(key='Escape'))
    assert notebook_disabled(app) is False
    start_manual(tool)
    click(tool, Point(0, 0), button=2)
    assert app.created == []


def test_second_click_on_only_pad_removes_highlight(setup):
    tool, app, source = setup
    pads = pads_of(tool, source)
    start_manual(tool)
    click(tool, pads[0][2])
    click(tool, pads[0][2])
    app.tool_shapes.remove.assert_called_once()


def test_select_all_after_click_has_every_pad_once(setup):
    tool, app, source = setup
    pads = pads_of(tool, source)
    start_manual(tool)
    click(tool, pads[0][2])
    tool.on_manual_sel_all()
    keys = [(p['apid'], p['idx']) for p in tool.manual_pads]
    assert len(keys) == len(set(keys)) == len(pads)
    assert set(keys) == {(a, i) for a, i, _pt in pads}


@pytest.mark.parametrize('code,category', [
    ('empty', 'WARNING_NOTCL'),
    ('nothing', 'WARNING_NOTCL'),
    ('size', 'ERROR_NOTCL'),
    ('zero', 'WARNING_NOTCL'),
])
def test_error_codes_create_no_object_and_report_category(setup, monkeypatch, code, category):
    tool, app, source = setup

    def fail(*args, **kwargs):
        raise ValueError(code)

    monkeypatch.setattr(PUNCH_MODULE, 'punch_geometry', fail)
    tool.on_fixed_method(source, 'src_punched')
    assert app.created == []
    assert app.inform.emit.call_args[0][0].startswith('[%s]' % category)


def test_cleanup_ends_manual_mode_and_clears_marks(setup):
    tool, app, source = setup
    start_manual(tool)
    tool.old_name = 'src'
    source.mark_shapes = SimpleNamespace(enabled=True)
    tool.ui.exc_combo.setRootModelIndex = lambda *a: None
    tool.ui.gerber_object_combo.setRootModelIndex = lambda *a: None
    tool.on_plugin_cleanup()
    assert notebook_disabled(app) is False
    assert source.mark_shapes.enabled is False
    source.clear_plot_apertures.assert_called()
