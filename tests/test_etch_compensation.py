"""Etch compensation: offset maths and geometry/aperture compensation (Qt-free Gen module)."""

from copy import deepcopy

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from appPlugins.ToolEtchCompensation.EtchCompensationGen import (
    compensate_geometry, lateral_offset_um, quad_segs, um_to_units)


def test_factor_mode_divides_thickness_by_factor():
    assert lateral_offset_um(35.0, 'factor', factor=3.0) == pytest.approx(11.6667, abs=1e-3)


def test_each_etchant_has_its_own_factor():
    offsets = [lateral_offset_um(18.0, 'etch_list', etchant=e) for e in ('cucl2', 'fecl3', 'alkaline')]
    assert offsets == pytest.approx([18 / 3.0, 18 / 2.5, 18 / 4.0])


@pytest.mark.parametrize('kwargs', [
    dict(mode='factor', factor=0),
    dict(mode='etch_list', etchant='nope'), dict(mode='manual', offset_um=None), dict(mode='other'),
    dict(mode='factor', factor=3.0, thickness_um=-1.0)])
def test_invalid_inputs_raise(kwargs):
    thickness = kwargs.pop('thickness_um', 18.0)
    with pytest.raises(ValueError):
        lateral_offset_um(thickness, **kwargs)


def test_manual_offset_passes_through_negative():
    assert lateral_offset_um(18.0, 'manual', offset_um=-7.5) == -7.5


def test_um_to_units_and_quad_segs():
    assert um_to_units(1000.0, 'MM') == pytest.approx(1.0)
    assert um_to_units(25400.0, 'in') == pytest.approx(1.0)
    with pytest.raises(ValueError):
        um_to_units(1.0, 'cm')
    assert quad_segs(64) == 16
    assert quad_segs(2) == 1


def _aperture_set():
    return {
        '10': {'type': 'C', 'size': 1.0, 'geometry': [
            {'solid': Point(0, 0).buffer(0.5), 'follow': Point(0, 0), 'clear': box(-0.1, -0.1, 0.1, 0.1)}]},
        '11': {'type': 'R', 'width': 2.0, 'height': 1.0, 'size': 2.2, 'geometry': [{'solid': box(0, 0, 2, 1)}]},
    }


def test_inputs_are_not_mutated():
    geom = [box(0, 0, 1, 1), MultiPolygon([box(3, 0, 4, 1)])]
    aps = _aperture_set()
    geom_before, aps_before = deepcopy(geom), deepcopy(aps)
    compensate_geometry(geom, aps, 0.1, 16)
    assert [g.wkt for g in geom] == [g.wkt for g in geom_before]
    assert aps['10']['size'] == aps_before['10']['size']
    assert aps['11']['width'] == aps_before['11']['width']
    assert aps['10']['geometry'][0]['solid'].equals(aps_before['10']['geometry'][0]['solid'])


def test_aperture_dimensions_grow_by_twice_the_offset():
    _, aps = compensate_geometry([], _aperture_set(), 0.1, 16)
    assert aps['10']['size'] == pytest.approx(1.2)
    assert aps['11']['width'] == pytest.approx(2.2)
    assert aps['11']['height'] == pytest.approx(1.2)
    assert aps['11']['size'] == pytest.approx((2.2 ** 2 + 1.2 ** 2) ** 0.5)


def test_clear_shrinks_and_solid_grows():
    _, aps = compensate_geometry([], _aperture_set(), 0.05, 16)
    rec = aps['10']['geometry'][0]
    assert rec['solid'].area > Point(0, 0).buffer(0.5).area
    assert rec['clear'].area < box(-0.1, -0.1, 0.1, 0.1).area
    assert rec['follow'].equals(Point(0, 0))


def test_large_negative_offset_drops_emptied_records_and_clamps_dimensions():
    _, aps = compensate_geometry([], _aperture_set(), -0.6, 16)
    assert aps['10']['geometry'] == []
    assert aps['11']['geometry'] == []
    assert aps['10']['size'] == 0.0
    assert aps['11']['width'] == pytest.approx(0.8)
    assert aps['11']['height'] == 0.0
    assert aps['11']['size'] == pytest.approx(0.8)


def test_positive_offset_empties_small_clear_key():
    aps = {'1': {'type': 'C', 'size': 1.0, 'geometry': [{'solid': box(0, 0, 1, 1), 'clear': box(0, 0, 0.1, 0.1)}]}}
    _, new = compensate_geometry([], aps, 0.2, 16)
    assert 'clear' not in new['1']['geometry'][0]
    assert 'solid' in new['1']['geometry'][0]


def test_result_is_flat_polygon_list_matching_single_union_buffer():
    geom = [box(0, 0, 1, 1), box(0.5, 0, 1.5, 1), MultiPolygon([box(5, 0, 6, 1)])]
    out, _ = compensate_geometry(geom, {}, 0.1, 16)
    assert isinstance(out, list) and out and all(isinstance(p, Polygon) for p in out)
    expected = unary_union([box(0, 0, 1, 1), box(0.5, 0, 1.5, 1), box(5, 0, 6, 1)]).buffer(0.1, 4)
    assert sum(p.area for p in out) == pytest.approx(expected.area)
    assert len(out) == 2


# ---------------------------------------------------------------------------------------------------------------
# the controller, called unbound on a namespace so that no window is built; the worker job runs synchronously
# ---------------------------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import MagicMock

from appPlugins.ToolEtchCompensation import ToolEtchCompensation

_METHODS = ('collect', 'read_values', 'offset_of', '_opt', '_set_busy', '_start', 'on_compensate', 'worker_job',
            'on_job_done', 'finish', 'store_values', 'draw_preview', 'clear_preview')


def _source(name, side=2.0):
    return SimpleNamespace(kind='gerber', obj_options={'name': name}, solid_geometry=[box(0, 0, side, side)],
                           tools={}, fill_color='#fff', outline_color='#000')


def _make_tool(sources, units='MM', multi=False, **ui_values):
    app = MagicMock()
    app.app_units = units
    app.defaults = None
    app.options = {'gerber_circle_steps': 64}
    app.collection.get_names.return_value = []
    app.collection.get_selected.return_value = sources
    app.collection.get_by_name.side_effect = lambda n: next((s for s in sources if s.obj_options['name'] == n), None)
    values = dict(thick_entry=30.0, ratio_radio='factor', factor_entry=3.0, etchants_combo=None, offset_entry=0.0,
                  multi_cb=multi)
    values.update(ui_values)
    ui = MagicMock()
    for key, value in values.items():
        getattr(ui, key).get_value.return_value = value
    ui.etchants_combo.currentData.return_value = 'cucl2'
    ui.gerber_combo.currentText.return_value = sources[0].obj_options['name']
    tool = SimpleNamespace(app=app, ui=ui, decimals=4, pluginName='Etch', _busy=False, _preview_drawn=False,
                           job_done=MagicMock(), created=[])
    for name in _METHODS:
        setattr(tool, name, getattr(ToolEtchCompensation, name).__get__(tool))
    tool.job_done.emit.side_effect = tool.on_job_done
    app.worker_task.emit.side_effect = lambda task: task['fcn'](*task['params'])

    def new_object(kind, name, init, **kwargs):
        obj = SimpleNamespace(obj_options={}, regenerate_source=lambda **kw: None)
        init(obj, app)
        tool.created.append((name, obj))
        return obj

    tool.new_object = new_object
    return tool


def _messages(tool):
    return [c.args[0] for c in tool.app.inform.emit.call_args_list if c.args]


@pytest.mark.parametrize('units, thickness, side_effect', [('MM', 30.0, 0.01), ('IN', 254.0, 0.01)])
def test_controller_grows_copper_by_thickness_over_factor(units, thickness, side_effect):
    # F = 1 for IN: 254 um = 0.01 in; F = 3 for MM: 30 um / 3 = 10 um = 0.01 mm
    src = _source('a')
    tool = _make_tool([src], units=units, thick_entry=thickness, factor_entry=3.0 if units == 'MM' else 1.0)
    tool.on_compensate()
    (name, obj), = tool.created
    assert name == 'a_comp' and obj.obj_options['name'] == 'a_comp'
    minx, miny, maxx, maxy = unary_union(obj.solid_geometry).bounds
    assert (minx, maxx) == pytest.approx((-side_effect, 2 + side_effect))
    assert all(isinstance(g, Polygon) for g in obj.solid_geometry)
    assert any(m.startswith('[success]') and 'a_comp' in m for m in _messages(tool))


def test_controller_leaves_the_source_unchanged():
    src = _source('a')
    before = [g.wkt for g in src.solid_geometry]
    tool = _make_tool([src])
    tool.on_compensate()
    assert len(tool.created) == 1, _messages(tool)
    assert [g.wkt for g in src.solid_geometry] == before


@pytest.mark.parametrize('ui_values, level', [
    (dict(factor_entry=0), '[ERROR_NOTCL]'),
    (dict(factor_entry=None), '[ERROR_NOTCL]'),
    (dict(ratio_radio='manual', offset_entry=0.0), '[WARNING_NOTCL]')])
def test_controller_creates_nothing_for_unusable_offset(ui_values, level):
    tool = _make_tool([_source('a')], **ui_values)
    tool.on_compensate()
    assert tool.created == []
    assert any(m.startswith(level) for m in _messages(tool))
    assert not any(m.startswith('[success]') for m in _messages(tool))


def test_controller_multi_select_makes_one_output_per_gerber():
    a, b = _source('a'), _source('b', 4.0)
    other = SimpleNamespace(kind='geometry', obj_options={'name': 'g'})
    tool = _make_tool([a, b, other], multi=True)
    tool.on_compensate()
    assert sorted(name for name, _obj in tool.created) == ['a_comp', 'b_comp']
    # nothing selected: an error and no object
    tool = _make_tool([a], multi=True)
    tool.app.collection.get_selected.return_value = [other]
    tool.on_compensate()
    assert tool.created == [] and any(m.startswith('[ERROR_NOTCL]') for m in _messages(tool))
