import gc
import os
import sys
import types

import pytest
from unittest.mock import MagicMock, Mock

from PyQt6 import sip
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from shapely.geometry import Point, LineString, box

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appPlugins.ToolRulesCheck import RulesCheckGen as gen  # noqa: E402
from appPlugins.ToolRulesCheck.RulesCheck import RulesCheck, RULE_WIDGETS, OBJECT_WIDGETS  # noqa: E402
from appPlugins.ToolRulesCheck.RulesCheckGen import render_report  # noqa: E402
from tests.helpers_objects import _headless_qt, make_app  # noqa: E402,F401

# Outline drawn as a thin ring: inner edge at x=0, y=0, x=10, y=10
RING = box(-1, -1, 11, 11).difference(box(0, 0, 10, 10))


def _aperture(kind, size=None, width=None, height=None, diam=None, tracks=()):
    return {'type': kind, 'size': size, 'width': width, 'height': height, 'diam': diam, 'tracks': list(tracks)}


def _gerber(name, geo=(), apertures=None):
    return {'name': name, 'geo': list(geo), 'apertures': apertures or {}}


def _excellon(name, holes=(), slots=()):
    return {'name': name, 'holes': list(holes), 'slots': list(slots)}


def _hole(x, y, dia):
    return {'x': x, 'y': y, 'dia': dia, 'geo': Point(x, y).buffer(dia / 2)}


def _slot(x1, y1, x2, y2, dia):
    return {'x': (x1 + x2) / 2, 'y': (y1 + y2) / 2, 'dia': dia,
            'geo': LineString([(x1, y1), (x2, y2)]).buffer(dia / 2)}


RULE_KEYS = ('trace_size', 'c2c', 'c2o', 's2s', 's2sm', 's2o', 'sm2sm', 'ri', 'h2h', 'dh', 'slot', 'h2o', 'h2c', 'iso')
LAYER_KEYS = ('copper_top', 'copper_bottom', 'sm_top', 'sm_bottom', 'silk_top', 'silk_bottom', 'outline',
              'exc_1', 'exc_2')


def _config(enabled, value=0.1, **values):
    """Every rule key present; rules named in `enabled` are on, the rest off."""
    config = {key: {'enabled': key in enabled, 'value': values.get(key, value)} for key in RULE_KEYS}
    return config


def _layers(**layers):
    out = {key: None for key in LAYER_KEYS}
    out.update(layers)
    return out


def test_within_gap_below_size_is_one_violation_located_between_squares():
    layer = _gerber('TOP', [box(0, 0, 1, 1), box(1.1, 0, 2.1, 1)])

    result = gen.check_clearance_within(layer, 0.25, 'R')

    assert len(result['violations']) == 1
    violation = result['violations'][0]
    assert violation['value'] == pytest.approx(0.1, abs=1e-6)
    assert violation['layer'] == 'TOP'
    assert 1.0 <= violation['x'] <= 1.1
    assert 0.0 <= violation['y'] <= 1.0
    assert result['error'] is None


def test_within_touching_polygons_are_connected_not_violating():
    # Touching polygons share an edge, so they are one copper area and not a clearance gap
    layer = _gerber('TOP', [box(0, 0, 1, 1), box(1, 0, 2, 1)])

    result = gen.check_clearance_within(layer, 0.25, 'R')

    assert result['violations'] == []
    assert result['error'] is None


def test_between_copper_near_outline_ring_violates():
    copper = _gerber('TOP', [box(0.2, 4, 0.7, 5)])
    outline = _gerber('OUT', [RING])

    result = gen.check_clearance_between(copper, outline, 0.5, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.2, abs=1e-6)


@pytest.mark.parametrize('aperture', [
    _aperture('C', size=0.1, tracks=[LineString([(0, 0), (5, 0)])]),  # round by size
    _aperture('P', diam=0.1, tracks=[LineString([(0, 0), (5, 0)])]),  # circle by diameter
])
def test_trace_size_narrow_round_track_violates(aperture):
    layer = _gerber('TOP', apertures={10: aperture})

    result = gen.check_trace_size([layer], 0.15, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.1, abs=1e-6)
    assert result['error'] is None


def test_trace_size_rectangle_uses_min_side_not_diagonal():
    # Width 0.1, height 2.0: a horizontal track is 0.1 wide. The diagonal (2.01) must not be used.
    layer = _gerber('TOP', apertures={
        10: _aperture('R', width=0.1, height=2.0, tracks=[LineString([(0, 0), (5, 0)])]),
    })

    result = gen.check_trace_size([layer], 0.2, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.1, abs=1e-6)


@pytest.mark.parametrize('hole_dia, values', [(0.6, [0.2]), (0.2, [])])  # thin ring fails, wide ring passes
def test_annular_ring_thin_ring_violates_wide_ring_passes(hole_dia, values):
    pad = _gerber('TOP', [Point(0, 0).buffer(0.5)])
    exc = _excellon('EXC', holes=[_hole(0, 0, hole_dia)])

    result = gen.check_annular_ring(pad, [exc], 0.25, 'R')

    assert [round(v['value'], 1) for v in result['violations']] == values
    assert result['error'] is None


def test_annular_ring_hole_crossing_pad_edge_is_zero():
    pad = _gerber('TOP', [Point(0, 0).buffer(0.5)])
    exc = _excellon('EXC', holes=[_hole(0.4, 0, 0.6)])

    result = gen.check_annular_ring(pad, [exc], 0.25, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0, abs=1e-6)


def test_hole_clearance_edges_closer_than_size_reported_once():
    exc = _excellon('EXC', holes=[_hole(0, 0, 0.5), _hole(0.6, 0, 0.5)])

    result = gen.check_hole_clearance([exc], 0.3, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.1, abs=0.01)


def test_hole_size_reports_each_undersized_drill():
    exc = _excellon('EXC', holes=[_hole(0, 0, 0.2), _hole(3, 0, 0.2), _hole(6, 0, 0.5)])

    result = gen.check_hole_size([exc], 0.3, 'R')

    assert len(result['violations']) == 2
    assert all(v['value'] == pytest.approx(0.2, abs=1e-6) for v in result['violations'])


def test_hole_to_outline_closer_than_size_violates():
    exc = _excellon('EXC', holes=[_hole(0.35, 5, 0.5)])
    outline = _gerber('OUT', [RING])

    result = gen.check_hole_to_outline([exc], outline, 0.3, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.1, abs=0.01)


def test_hole_to_copper_neighbour_pad_violates():
    exc = _excellon('EXC', holes=[_hole(1.0, 0, 0.5)])
    copper = _gerber('TOP', [Point(0, 0).buffer(0.5)])

    result = gen.check_hole_to_copper([exc], copper, 0.3, 'R')

    assert len(result['violations']) == 1
    assert result['violations'][0]['value'] == pytest.approx(0.25, abs=0.02)


def test_build_jobs_c2c_runs_top_and_bottom():
    layers = _layers(
        copper_top=_gerber('TOP', [box(0, 0, 1, 1)]),
        copper_bottom=_gerber('BOT', [box(0, 0, 1, 1)]),
    )
    jobs = gen.build_jobs(_config({'c2c'}), layers)

    results = gen.run_jobs_sync(jobs)

    assert len(results) == 2
    assert sum('TOP' in r['rule'] and 'BOTTOM' not in r['rule'] for r in results) == 1
    assert sum('BOTTOM' in r['rule'] for r in results) == 1


def test_build_jobs_silk_outline_uses_s2o_value_not_c2o():
    layers = _layers(
        copper_top=_gerber('COPPER_T', [box(0.2, 4, 0.7, 5)]),
        silk_top=_gerber('SILK_T', [box(0.5, 6, 0.6, 7)]),
        outline=_gerber('OUT', [RING]),
    )
    config = _config({'c2o', 's2o'}, c2o=0.1, s2o=0.5)
    jobs = gen.build_jobs(config, layers)

    results = gen.run_jobs_sync(jobs)

    silk = [r for r in results if any('SILK_T' in n for n in r['names'])]
    assert len(silk) == 1
    assert silk[0]['limit'] == 0.5


def test_build_jobs_missing_layers_error_and_other_rules_still_run():
    layers = _layers(exc_1=_excellon('EXC', holes=[_hole(0, 0, 0.5), _hole(0.6, 0, 0.5)]))
    config = _config({'c2c', 'h2h'}, h2h=0.3)
    jobs = gen.build_jobs(config, layers)

    results = gen.run_jobs_sync(jobs)

    assert any(r['error'] for r in results)
    assert any(r['error'] is None and r['limit'] == 0.3 and len(r['violations']) == 1 for r in results)


def test_gerber_layer_unions_solid_geometry_and_keeps_only_drawn_tracks():
    track = LineString([(0, 0), (5, 0)])
    obj = types.SimpleNamespace(
        obj_options={'name': 'TOP'},
        solid_geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)],
        tools={
            10: {'type': 'C', 'size': 0.1, 'geometry': [{'solid': box(0, 0, 1, 1), 'follow': track}]},
            11: {'type': 'C', 'size': 1.0, 'geometry': [{'solid': box(5, 5, 6, 6), 'follow': Point(5.5, 5.5)}]},
        })

    layer = gen.gerber_layer(obj)

    assert layer['name'] == 'TOP'
    assert len(layer['geo']) == 2
    assert list(layer['apertures']) == [10]
    assert layer['apertures'][10]['tracks'] == [track]


# ---------------------------------------------------------------------------------------------------------------
# the plugin: controller + UI with a stub app (real widgets, fake collection and pool)
# ---------------------------------------------------------------------------------------------------------------
class FakeCollection(QStandardItemModel):
    def __init__(self, objects):
        super().__init__()
        self.objects = {o.obj_options['name']: o for o in objects}
        # like the project tree: a group row for Gerber objects and one for Excellon objects
        groups = [QStandardItem('Gerber'), QStandardItem('Excellon')]
        self.appendColumn(groups)
        for name, obj in list(self.objects.items()) + [('ghost', None)]:
            is_exc = obj is not None and bool(obj.tools)  # only the Excellon stubs have tools
            groups[1 if is_exc else 0].appendRow(QStandardItem(name))

    def get_by_name(self, name):
        return self.objects.get(name)


class SyncPool:
    """Runs the job at get() time; `broken` lists the functions whose result raises."""

    def __init__(self, broken=()):
        self.broken = broken

    def apply_async(self, func, args=()):
        def get():
            if func in self.broken:
                raise RuntimeError('worker died')
            return func(*args)
        return types.SimpleNamespace(get=get, ready=lambda: True, wait=lambda timeout=None: None)


def _gerber_obj(name, *polys):
    return types.SimpleNamespace(obj_options={'name': name}, solid_geometry=list(polys), tools={})


def _excellon_obj(name, *points):
    tools = {1: {'tooldia': 0.8, 'drills': [Point(p) for p in points], 'slots': []}}
    return types.SimpleNamespace(obj_options={'name': name}, tools=tools)


@pytest.fixture
def tool():
    app = make_app()
    app.resource_location = ''
    app.inform = MagicMock()
    app.pool = SyncPool()
    app.collection = FakeCollection([
        _gerber_obj('top', box(0, 0, 1, 1), box(1.1, 0, 2, 1)), _gerber_obj('bot', box(0, 0, 1, 1)),
        _gerber_obj('sm_t'), _gerber_obj('sm_b'), _gerber_obj('silk_t'), _gerber_obj('silk_b'),
        _gerber_obj('out', RING), _excellon_obj('pth', (0.5, 0.5)), _excellon_obj('npth', (5, 5))])
    plugin = RulesCheck(app)
    plugin.set_tool_ui()
    plugin.new_object = Mock()
    yield plugin
    # the comboboxes use the model of app.collection: delete the widgets (also the ones that set_tool_ui() took
    # out of the layout) while the model is alive; a random garbage collection order crashes Qt
    sip.delete(plugin)
    gc.collect()


def _enable_only(tool, *stems):
    for stem, (cb_name, _entry) in RULE_WIDGETS.items():
        getattr(tool.ui, cb_name).setChecked(stem in stems)


def _use(tool, key, name):
    cb_name, combo_name = OBJECT_WIDGETS[key]
    getattr(tool.ui, cb_name).setChecked(True)
    getattr(tool.ui, combo_name).setCurrentText(name)


def test_every_widget_reaches_its_config_key(tool):
    stems = list(RULE_WIDGETS)
    for i, stem in enumerate(stems):
        cb_name, entry_name = RULE_WIDGETS[stem]
        getattr(tool.ui, cb_name).setChecked(i % 2 == 0)
        getattr(tool.ui, entry_name).set_value(0.1 * (i + 1))
    names = {'copper_top': 'top', 'copper_bottom': 'bot', 'sm_top': 'sm_t', 'sm_bottom': 'sm_b',
             'silk_top': 'silk_t', 'silk_bottom': 'silk_b', 'outline': 'out', 'exc_1': 'pth', 'exc_2': 'npth'}
    for key, name in names.items():
        _use(tool, key, name)
    tool.ui.out_cb.setChecked(False)

    config, objects, problems = tool.collect_inputs()

    assert problems == []
    for i, stem in enumerate(stems):
        assert config[stem]['enabled'] == (i % 2 == 0), stem
        assert config[stem]['value'] == pytest.approx(0.1 * (i + 1)), stem
    assert {k: (v.obj_options['name'] if v else None) for k, v in objects.items()} == dict(names, outline=None)


def test_run_reports_violation_and_ends_idle(tool):
    _enable_only(tool, 'c2c', 'dh')
    tool.ui.clearance_copper2copper_entry.set_value(0.5)
    tool.ui.drill_size_entry.set_value(1.0)
    _use(tool, 'copper_top', 'top')
    _use(tool, 'exc_1', 'pth')
    tool.app.worker_task.emit.side_effect = lambda task: task['fcn'](*task['params'])

    tool.execute()

    assert len(tool.last_results) == 2
    assert [len(r['violations']) for r in tool.last_results] == [1, 1]
    tool.app.proc_container.view.set_idle.assert_called_once()
    assert tool.new_object.call_count == 1


def test_failing_job_still_reports_other_rules(tool):
    config = {'dh': {'enabled': True, 'value': 1.0}, 'slot': {'enabled': True, 'value': 0.5}}
    tool.app.pool = SyncPool(broken=(gen.check_slot_size,))

    tool.worker_job(config, {'exc_1': _excellon_obj('e', (0, 0))})

    first, second = tool.last_results
    assert len(first['violations']) == 1 and first['error'] is None
    assert 'worker died' in second['error']
    tool.app.proc_container.view.set_idle.assert_called_once()


def test_report_statuses_units_and_odd_shapes():
    failed = gen.make_result('Copper gap', 0.25, ['top'])
    failed['checked'] = 3
    failed['violations'] = [{'layer': 'top', 'x': 1.5, 'y': 2.25, 'value': 0.1}]
    passed = dict(gen.make_result('Ring', 0.3, ['top']), checked=2)
    nothing = gen.make_result('Hole size', 0.3, ['pth'])
    errored = dict(gen.make_result('Slot', 0.3, []), error='needs <Excellon>')

    html = render_report([failed, passed, nothing, errored, 'odd', None, {'violations': 5}], 2, 'MM')

    assert 'FAILED (1 violations)' in html and '(1.50, 2.25)' in html and '0.10 MM' in html
    assert '0.25 MM' in html
    assert 'PASSED' in html and 'NOTHING TO CHECK' in html
    assert 'ERROR' in html and 'needs &lt;Excellon&gt;' in html
    assert render_report([], 2, 'MM') == ''


# ---------------------------------------------------------------------------------------------------------------
# results table, canvas markers, CSV, presets, cancel
# ---------------------------------------------------------------------------------------------------------------
def _sample_results():
    failed = dict(gen.make_result('Copper gap', 0.25, ['top']), checked=3, violations=[
        {'layer': 'top', 'x': 1.5, 'y': 2.25, 'value': 0.1}, {'layer': 'top', 'x': 7.0, 'y': 8.0, 'value': 0.2}])
    passed = dict(gen.make_result('Ring', 0.3, ['top']), checked=2)
    nothing = gen.make_result('Hole size', 0.3, ['pth'])
    errored = dict(gen.make_result('Slot', 0.3, []), error='needs an Excellon')
    return [failed, passed, nothing, errored]


def _rows(tool):
    table = tool.ui.results_table
    return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_results_table_has_a_row_per_violation_and_status_rows(tool):
    tool.tool_finished.emit(_sample_results())

    table = tool.ui.results_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(6)]
    assert headers[2:] == ['X (MM)', 'Y (MM)', 'Value (MM)', 'Limit (MM)']
    rows = _rows(tool)
    assert len(rows) == 4  # 2 violations + error + nothing to check; the passed rule has no row
    assert any(r[0] == 'Copper gap' and r[2] == '1.5000' and r[3] == '2.2500' and r[5] == '0.2500' for r in rows)
    assert any(r[0] == 'Slot' and r[1] == 'ERROR' for r in rows)
    assert any(r[0] == 'Hole size' and r[1] == 'NOTHING TO CHECK' for r in rows)
    assert tool.ui.summary_label.text() == '2 violations in 1 rules'
    assert tool.ui.export_button.isEnabled()


def test_clicking_a_row_zooms_to_the_violation(tool):
    tool.app.on_jump_to = Mock()
    tool.tool_finished.emit(_sample_results())
    row = next(r for r, cells in enumerate(_rows(tool)) if cells[2] == '7.0000')

    tool.ui.results_table.cellClicked.emit(row, 0)

    kwargs = tool.app.plotcanvas.fit_center.call_args.kwargs
    assert kwargs['loc'] == (7.0, 8.0)
    rect = kwargs['rect']
    assert rect.center == pytest.approx((7.0, 8.0)) and rect.width >= 2.0 - 1e-9
    tool.app.on_jump_to.assert_called_once_with(custom_location=(7.0, 8.0), fit_center=False)
    # a status row has no location
    tool.app.plotcanvas.fit_center.reset_mock()
    tool.ui.results_table.cellClicked.emit(next(r for r, c in enumerate(_rows(tool)) if c[1] == 'ERROR'), 0)
    tool.app.plotcanvas.fit_center.assert_not_called()


def test_results_to_csv_rows(tmp_path):
    import csv
    path = tmp_path / 'r.csv'
    gen.results_to_csv(_sample_results(), path)
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    assert rows[0] == ['rule', 'layer', 'x', 'y', 'value', 'limit', 'status']
    assert len(rows) == 5
    assert rows[1][:2] == ['Copper gap', 'top'] and float(rows[1][2]) == 1.5 and rows[1][-1] == 'FAILED'
    assert [r[-1] for r in rows[3:]] == ['NOTHING TO CHECK', 'ERROR']


def test_export_button_writes_the_csv(tool, tmp_path, monkeypatch):
    from appGUI import GUIElements as rc_module
    path = tmp_path / 'out.csv'
    tool.app.get_last_save_folder = Mock(return_value=str(tmp_path))
    monkeypatch.setattr(rc_module.FCFileSaveDialog, 'get_saved_filename', Mock(return_value=(str(path), 'csv')))
    assert not tool.ui.export_button.isEnabled()
    tool.tool_finished.emit(_sample_results())

    tool.ui.export_button.click()

    assert path.read_text(encoding='utf-8').startswith('rule,layer,x,y,value,limit,status')


def test_preset_fills_values_in_inches_and_editing_returns_to_custom(tool):
    tool.app.app_units = 'IN'
    tool.set_tool_ui()
    ui = tool.ui

    ui.preset_combo.setCurrentIndex(list(gen.PRESETS).index('JLCPCB standard') + 1)

    assert ui.clearance_copper2copper_entry.get_value() == pytest.approx(0.127 / 25.4, abs=1e-4)
    assert ui.drill_size_entry.get_value() == pytest.approx(0.3 / 25.4, abs=1e-4)
    assert ui.preset_combo.currentIndex() == list(gen.PRESETS).index('JLCPCB standard') + 1
    ui.drill_size_entry.set_value(0.05)
    assert ui.preset_combo.currentIndex() == 0


def test_cancel_discards_results_and_leaves_the_app_idle(tool):
    _enable_only(tool, 'dh')
    _use(tool, 'exc_1', 'pth')
    tool.execute()  # queued on the mocked worker_task
    task = tool.app.worker_task.emit.call_args.args[0]
    assert tool.ui.cancel_button.isEnabled() and not tool.ui.run_button.isEnabled()

    tool.ui.cancel_button.click()
    task['fcn'](*task['params'])

    assert tool.last_results == []
    assert tool.ui.results_table.rowCount() == 0
    tool.app.proc_container.view.set_idle.assert_called_once()
    assert any('cancelled' in str(c.args[0]) for c in tool.app.inform.emit.call_args_list)
    assert tool.ui.run_button.isEnabled() and not tool.ui.cancel_button.isEnabled()
