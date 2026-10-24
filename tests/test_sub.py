"""Subtract plugin core (appPlugins/ToolSub/SubGen.py): Gerber, Geometry and Excellon with Shapely only."""
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from shapely import LineString, MultiPolygon, Point, Polygon
from shapely.geometry import box
from shapely.ops import unary_union

# SubGen is Qt free; load it by path so the plugin package (which imports Qt) is not needed
_path = Path(__file__).resolve().parent.parent / 'appPlugins' / 'ToolSub' / 'SubGen.py'
_spec = importlib.util.spec_from_file_location('SubGen_under_test', _path)
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)


def flash(x, y, w=2.0, h=2.0):
    poly = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    return {'solid': poly, 'follow': Point(x, y)}


def gerber(tools, units='MM', name='grb'):
    solid = unary_union([el['solid'] for t in tools.values() for el in t['geometry'] if 'solid' in el])
    clears = [el['clear'] for t in tools.values() for el in t['geometry'] if 'clear' in el]
    if clears:
        solid = solid.difference(unary_union(clears))          # the app keeps solid_geometry polarity resolved
    return NS(kind='gerber', tools=tools, solid_geometry=solid, multigeo=False,
              obj_options={'units': units, 'name': name})


def geometry(shapes, units='MM', name='geo'):
    return NS(kind='geometry', tools={}, solid_geometry=shapes, multigeo=False,
              obj_options={'units': units, 'name': name})


def multigeo(shapes_by_uid, units='MM'):
    tools = {uid: {'solid_geometry': s} for uid, s in shapes_by_uid.items()}
    return NS(kind='geometry', tools=tools, solid_geometry=[], multigeo=True, obj_options={'units': units})


def excellon(tools, units='MM', name='exc'):
    return NS(kind='excellon', tools=tools, solid_geometry=[], multigeo=False,
              obj_options={'units': units, 'name': name})


def exc_tool(dia, drills=(), slots=()):
    drills = [Point(*d) for d in drills]
    slots = [(Point(*a), Point(*b)) for a, b in slots]
    shapes = [d.buffer(dia / 2) for d in drills]
    shapes += [LineString([(a.x, a.y), (b.x, b.y)]).buffer(dia / 2) for a, b in slots]
    return {'tooldia': dia, 'drills': drills, 'slots': slots, 'solid_geometry': shapes}


def area_of(res):
    return sum(g.area for g in sg._flat(res))


# ---------------------------------------------------------------------------------------------------- Gerber target
def test_pad_split_in_two_gives_two_regions():
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 10, 2)]}}
    cutter = gerber({'11': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 2, 10)]}})
    res = sg.compute(gerber(tools), [cutter])
    assert '10' not in res.tools
    regions = res.tools[0]['geometry']
    assert len(regions) == 2 and res.tools[0]['type'] == 'REG'
    assert all(r['follow'].geom_type == 'LinearRing' for r in regions)
    assert res.solid_geometry.area == pytest.approx(20 - 4)


def test_untouched_elements_keep_aperture_and_follow_removed_dropped():
    far, near, covered = flash(50, 0), flash(0, 0, 4, 2), flash(0, 10, 1, 1)
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [far, near]},
             '11': {'type': 'C', 'size': 1.0, 'geometry': [covered]}}
    cutter = geometry([box(-1, -1, 1, 11)])
    res = sg.compute(gerber(tools), [cutter], margin=0.5)
    assert res.tools['10']['geometry'][0] is far
    assert res.tools['10']['geometry'][0]['follow'] == Point(50, 0)
    assert '11' not in res.tools                      # fully removed: the aperture ended empty and is gone
    assert res.stats['removed'] == 1 and res.stats['changed'] == 1 and res.stats['kept'] == 1
    assert len(res.tools[0]['geometry']) == 2        # the near pad leaves two halves


def test_input_tools_not_mutated():
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 10, 2)]}}
    sg.compute(gerber(tools), [geometry([box(-1, -5, 1, 5)])])
    assert len(tools['10']['geometry']) == 1 and 0 not in tools


def test_existing_aperture_zero_region_can_be_cut():
    region = {'solid': box(0, 0, 10, 10), 'follow': box(0, 0, 10, 10).exterior}
    tools = {0: {'type': 'REG', 'size': 0.0, 'geometry': [region]}}
    res = sg.compute(gerber(tools), [geometry([box(4, -1, 6, 11)])])
    assert len(res.tools[0]['geometry']) == 2


def test_subtractor_clear_holes_keep_copper_under_them():
    target = gerber({'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 10, 10)]}})
    pour = {'solid': box(-20, -20, 20, 20)}
    hole = {'clear': box(-2, -2, 2, 2)}
    sub = gerber({0: {'type': 'REG', 'size': 0.0, 'geometry': [pour, hole]}})
    res = sg.compute(target, [sub])
    assert res.solid_geometry.area == pytest.approx(16)       # only the copper under the hole survives
    assert res.tools[0]['geometry'][0]['solid'].area == pytest.approx(16)


def test_margin_grows_the_cut():
    target = gerber({'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 20, 2)]}})
    cutter = geometry([box(-1, -5, 1, 5)])
    plain = sg.compute(target, [cutter])
    grown = sg.compute(target, [cutter], margin=1.0)
    assert grown.solid_geometry.area < plain.solid_geometry.area
    assert plain.solid_geometry.area == pytest.approx(36)


def test_aperture_selection_leaves_other_apertures_alone():
    a, b = flash(0, 0, 4, 4), flash(0, 10, 4, 4)
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [a]}, '11': {'type': 'R', 'size': 0.0, 'geometry': [b]}}
    cutter = geometry([box(-5, -5, 5, 15)])
    res = sg.compute(gerber(tools), [cutter], target_tools=['11'])
    assert res.tools['10']['geometry'][0] is a
    assert '11' not in res.tools
    assert res.solid_geometry.area == pytest.approx(16)


def test_target_in_subtractors_raises():
    target = gerber({'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0)]}})
    with pytest.raises(ValueError):
        sg.compute(target, [target])
    with pytest.raises(ValueError):
        sg.compute(target, [])


def test_intersect_keeps_inside_and_clips_partial():
    inside, partial, outside = flash(0, 0, 2, 2), flash(10, 0, 4, 2), flash(50, 0)
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [inside, partial, outside]}}
    res = sg.compute(gerber(tools), [geometry([box(-5, -5, 11, 5)])], op='intersect')
    assert res.tools['10']['geometry'] == [inside]
    assert res.tools[0]['geometry'][0]['solid'].area == pytest.approx(3 * 2)
    assert res.stats == {'kept': 1, 'changed': 1, 'removed': 1, 'added': 0}


def test_xor_adds_area_outside_target():
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 4, 4)]}}
    res = sg.compute(gerber(tools), [geometry([box(0, -2, 6, 2)])], op='xor')
    assert res.solid_geometry.area == pytest.approx(16 + 24 - 2 * 8)
    assert res.stats['added'] == 1


def test_lines_without_margin_report_empty_area():
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0)]}}
    res = sg.compute(gerber(tools), [geometry([LineString([(-5, 0), (5, 0)])])])
    assert res.empty_area and res.solid_geometry.area == pytest.approx(4)
    cut = sg.compute(gerber(tools), [geometry([LineString([(-5, 0), (5, 0)])])], margin=0.2)
    assert not cut.empty_area and cut.solid_geometry.area < 4


def test_units_mix_inch_subtractor_on_mm_target():
    target = gerber({'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(25.4, 0, 2, 2)]}}, units='MM')
    cutter = geometry([box(0.9, -0.5, 1.1, 0.5)], units='IN')     # centered at x = 25.4 mm
    res = sg.compute(target, [cutter])
    assert res.solid_geometry.area == pytest.approx(0.0, abs=1e-9)  # the 5.08 mm wide cut removes the pad
    assert not res.tools


@pytest.mark.parametrize('target_units, sub_units, expected', [
    ('MM', 'IN', 25.4), ('IN', 'MM', 1 / 25.4), ('MM', 'MM', 1.0), (None, 'IN', 1.0), ('MM', None, 1.0)])
def test_units_factor(target_units, sub_units, expected):
    assert sg.units_factor(target_units, sub_units) == pytest.approx(expected)


# --------------------------------------------------------------------------------------------------- Geometry target
@pytest.mark.parametrize('multi', [False, True])
def test_geometry_bare_multipolygon_gives_result(multi):
    mp = MultiPolygon([box(0, 0, 4, 4), box(10, 0, 14, 4)])
    target = multigeo({1: mp}) if multi else geometry(mp)
    res = sg.compute(target, [geometry([box(-1, -1, 2, 5)])], close_paths=True)
    assert res.multigeo is multi
    shapes = sg._flat(res.tools[1]['solid_geometry'] if multi else res.solid_geometry)
    assert sum(s.area for s in shapes) == pytest.approx(8 + 16)


def test_geometry_rings_when_not_closing_paths():
    res = sg.compute(geometry([box(0, 0, 10, 10)]), [geometry([box(4, -1, 6, 11)])])
    assert all(g.geom_type in ('LineString', 'LinearRing') for g in res.solid_geometry)
    assert len(res.solid_geometry) == 3        # the ring is cut in three open paths


def test_geometry_lines_with_margin_cut_gerber_and_excellon_subtractors():
    target = geometry([box(0, 0, 10, 10)])
    by_line = sg.compute(target, [geometry([LineString([(5, -5), (5, 15)])])], margin=1.0, close_paths=True)
    assert area_of(by_line.solid_geometry) == pytest.approx(80, rel=0.01)
    exc = excellon({1: exc_tool(2.0, drills=[(5, 5)])})
    by_exc = sg.compute(target, [exc], close_paths=True)
    assert area_of(by_exc.solid_geometry) < 100 - 3
    grb = gerber({'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(5, 5, 4, 4)]}})
    by_grb = sg.compute(target, [grb], close_paths=True)
    assert area_of(by_grb.solid_geometry) == pytest.approx(84)


def test_geometry_intersect():
    res = sg.compute(geometry([box(0, 0, 10, 10)]), [geometry([box(5, 5, 20, 20)])], op='intersect', close_paths=True)
    assert area_of(res.solid_geometry) == pytest.approx(25)


# -------------------------------------------------------------------------------------------------- Excellon target
def test_excellon_drops_covered_drills_and_slots_and_empty_tools():
    tools = {1: exc_tool(1.0, drills=[(0, 0), (20, 0)]),
             2: exc_tool(0.8, drills=[(0, 5)], slots=[((0, 8), (4, 8))]),
             3: exc_tool(0.6, drills=[(1, 1)])}
    res = sg.compute(excellon(tools), [geometry([box(-2, -2, 2, 6)])], close_paths=True)
    assert [(p.x, p.y) for p in res.tools[1]['drills']] == [(20, 0)]
    assert len(res.tools[1]['solid_geometry']) == 1
    assert 3 not in res.tools
    assert res.tools[2]['drills'] == [] and len(res.tools[2]['slots']) == 1   # the slot only touches the area
    assert len(res.tools[2]['solid_geometry']) == 1


def test_excellon_intersect_keeps_only_covered_and_xor_rejected():
    tools = {1: exc_tool(1.0, drills=[(0, 0), (20, 0)])}
    res = sg.compute(excellon(tools), [geometry([box(-2, -2, 2, 2)])], op='intersect')
    assert [(p.x, p.y) for p in res.tools[1]['drills']] == [(0, 0)]
    with pytest.raises(ValueError):
        sg.compute(excellon(tools), [geometry([box(-2, -2, 2, 2)])], op='xor')


def test_excellon_subtractor_uses_hole_diameters_and_tool_selection():
    exc = excellon({1: exc_tool(2.0, drills=[(0, 0)]), 2: exc_tool(1.0, drills=[(10, 0)])}, name='drl')
    both = sg.subtractor_area([exc], steps=64)
    only = sg.subtractor_area([exc], steps=64, tools_by_name={'drl': [2]})
    assert both.area > only.area
    assert only.area == pytest.approx(3.14159 * 0.25, rel=0.01)
    assert sg.object_area(exc, margin=1.0, tools=[2]).area > only.area


# ------------------------------------------------------------------------------------------------------- apply/perf
def test_apply_result_sets_everything_but_name():
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': [flash(0, 0, 10, 2)]}}
    target = gerber(tools, name='orig')
    res = sg.compute(target, [geometry([box(-1, -5, 1, 5)])])
    new = NS(obj_options={'name': 'new'})
    sg.apply_result(new, res, target)
    assert new.obj_options['name'] == 'new' and new.obj_options['units'] == 'MM'
    assert new.tools is res.tools and new.follow_geometry == res.follow_geometry


def test_many_pads_against_many_shapes_is_fast():
    pads = [flash(x * 3.0, y * 3.0, 1.0, 1.0) for x in range(50) for y in range(40)]
    tools = {'10': {'type': 'R', 'size': 0.0, 'geometry': pads}}
    cutters = [box(i * 12.0 + 0.2, j * 12.0 + 0.2, i * 12.0 + 1.0, j * 12.0 + 1.0) for i in range(12)
               for j in range(40)]
    started = time.perf_counter()
    res = sg.compute(gerber(tools), [geometry(cutters)], close_paths=True)
    assert time.perf_counter() - started < 2.0
    assert res.stats['kept'] + res.stats['changed'] + res.stats['removed'] == 2000


# ------------------------------------------------------------------------------------------------- plugin controller
@pytest.fixture(scope='module')
def fc():
    import os
    import sys
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6 import QtWidgets
    import appHandlers.appHistory as appHistory
    from appMain import App
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app = App(qapp=qapp, headless=True)
    appHistory.RECORD_IN_HEADLESS = True
    yield app
    appHistory.RECORD_IN_HEADLESS = False


@pytest.fixture
def plugin(fc, monkeypatch):
    from appObjects.AppObjectTemplate import FlatCAMObj
    monkeypatch.setattr(FlatCAMObj, 'plot', lambda *a, **k: None)
    for name in list(fc.collection.get_names()):
        fc.collection.delete_by_name(name)
    fc.history.clear()
    for shapes, name in ((box(0, 0, 10, 10), 'tgt'), (box(4, 4, 6, 6), 'cut')):
        fc.app_obj.new_object('geometry', name, lambda o, a, s=shapes: setattr(o, 'solid_geometry', [s]), plot=False)
    return fc.sub_tool


def _pump(fc, plugin, timeout=10.0):
    from PyQt6 import QtWidgets
    end = time.time() + timeout
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        if not plugin._busy and not fc.projects.is_busy():
            break
        time.sleep(0.02)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def _click(fc, plugin, keep=True, delete_subs=False, sub='cut'):
    """Open the plugin the way the user does, pick the objects and press Apply."""
    from PyQt6 import QtCore
    plugin.run(toggle=False)
    ui = plugin.ui
    ui.type_combo.setCurrentIndex(ui.type_combo.findData('geometry'))
    ui.target_combo.setCurrentText('tgt')
    for i in range(ui.subs_list.count()):
        item = ui.subs_list.item(i)
        item.setCheckState(QtCore.Qt.CheckState.Checked if item.text() == sub else QtCore.Qt.CheckState.Unchecked)
    ui.keep_target_cb.setChecked(keep)
    ui.delete_subs_cb.setChecked(delete_subs)
    ui.apply_button.click()
    _pump(fc, plugin)


@pytest.mark.slow
def test_one_click_after_reopening_gives_one_object(fc, plugin):
    plugin.run(toggle=False)
    plugin.set_tool_ui()
    _click(fc, plugin)
    assert sorted(fc.collection.get_names()) == ['cut', 'tgt', 'tgt_sub']
    assert fc.collection.get_by_name('tgt_sub').solid_geometry
    assert fc.collection.get_by_name('tgt_sub').solid_geometry != fc.collection.get_by_name('tgt').solid_geometry


@pytest.mark.slow
def test_undo_brings_back_target_and_subtractors_in_one_step(fc, plugin):
    steps = len(fc.history.undo_stack)
    _click(fc, plugin, keep=False, delete_subs=True)
    assert fc.collection.get_names() == ['tgt']
    assert len(fc.history.undo_stack) == steps + 1
    fc.history.undo()
    _pump(fc, plugin)
    assert sorted(fc.collection.get_names()) == ['cut', 'tgt']
    assert fc.collection.get_by_name('tgt').solid_geometry[0].area == 100.0
    fc.history.redo()
    _pump(fc, plugin)
    assert fc.collection.get_names() == ['tgt']
    assert sum(g.area for g in fc.collection.get_by_name('tgt').solid_geometry) < 100.0


@pytest.mark.slow
def test_worker_error_leaves_the_plugin_usable(fc, plugin, monkeypatch):
    import sys
    module = sys.modules['appPlugins.ToolSub.SubGen']

    real = module.compute
    failing = [True]

    def boom(*a, **k):
        if failing[0]:
            raise RuntimeError('boom')
        return real(*a, **k)
    monkeypatch.setattr(module, 'compute', boom)
    _click(fc, plugin)
    assert fc.collection.get_names().count('tgt_sub') == 0 and plugin._busy is False
    failing[0] = False
    plugin.ui.apply_button.click()
    _pump(fc, plugin)
    assert 'tgt_sub' in fc.collection.get_names()


@pytest.mark.slow
def test_subtractor_without_area_warns_and_creates_nothing(fc, plugin):
    messages = []
    fc.inform.connect(messages.append)
    try:
        plugin.run(toggle=False)
        fc.collection.get_by_name('cut').solid_geometry = [LineString([(0, 0), (9, 9)])]
        _click(fc, plugin)
    finally:
        fc.inform.disconnect(messages.append)
    assert sorted(fc.collection.get_names()) == ['cut', 'tgt']
    assert any('no area' in m for m in messages)
