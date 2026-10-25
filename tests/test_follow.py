"""Follow plugin core (appPlugins/ToolFollow/FollowGen.py): Gerber follow paths to milling paths with Shapely only."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from shapely import LineString, MultiPolygon, Point
from shapely.geometry import box

from test_tcl_audit_generation import factory_app
from test_tcl_audit_regressions import FCShell

# FollowGen is Qt free; load it by path so the plugin package (which imports Qt) is not needed
_path = Path(__file__).resolve().parent.parent / 'appPlugins' / 'ToolFollow' / 'FollowGen.py'
_spec = importlib.util.spec_from_file_location('FollowGen_under_test', _path)
fg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fg)


def total_length(lines):
    return sum(g.length for g in lines)


def source(tools, follow=None):
    if follow is None:
        follow = [el['follow'] for t in tools.values() for el in t['geometry']]
    return NS(follow_geometry=follow, tools=tools)


def params(**kw):
    base = dict(union=False, simplify=False, tolerance=0.0, merge=True, selection=None, apertures=None,
                dia_mode='default', tooldia=0.1)
    base.update(kw)
    return base


TOOLS = {
    10: {'size': 0.2, 'geometry': [{'follow': LineString([(0, 0), (5, 0)])}, {'follow': Point(9, 9)}]},
    11: {'size': 0.4, 'geometry': [{'follow': LineString([(0, 5), (5, 5)])}]},
    12: {'size': 0.2, 'geometry': [{'follow': LineString([(0, 8), (5, 8)])}]},
    0: {'size': 0.0, 'geometry': [{'follow': LineString([(0, 10), (5, 10)])}]},
}


def test_paths_of_drops_points_and_follows_polygon_boundaries():
    donut = box(0, 0, 10, 10).difference(box(3, 3, 6, 6))
    lines = fg.paths_of([Point(1, 1), LineString(), None, [LineString([(0, 0), (1, 0)])], MultiPolygon([donut])])
    assert all(g.geom_type == 'LineString' for g in lines)
    assert len(lines) == 3
    assert total_length(lines) == pytest.approx(1 + 40 + 12)
    assert fg.paths_of(None) == []


def test_merge_joins_touching_lines():
    lines = [LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 0)]), LineString([(5, 5), (6, 5)])]
    assert len(fg.clean_paths(lines, False, False, 0.0, merge=True)) == 2
    assert len(fg.clean_paths(lines, False, False, 0.0, merge=False)) == 3


def test_union_then_merge_does_not_leave_lines_split():
    overlap = [LineString([(0, 0), (4, 0)]), LineString([(2, 0), (6, 0)])]
    result = fg.clean_paths(overlap, True, False, 0.0, merge=True)
    assert len(result) == 1
    assert result[0].length == pytest.approx(6.0)


def test_simplify_applies_only_with_a_tolerance():
    wiggle = LineString([(0, 0), (1, 0.001), (2, 0), (3, 0.001), (4, 0)])
    assert len(fg.clean_paths([wiggle], False, True, 0.01)[0].coords) == 2
    assert len(fg.clean_paths([wiggle], False, True, 0.0)[0].coords) == 5
    assert len(fg.clean_paths([wiggle], False, False, 0.01)[0].coords) == 5


def test_selection_keeps_inside_clips_crossing_drops_outside():
    inside = LineString([(1, 1), (2, 1)])
    crossing = LineString([(1, 5), (9, 5)])
    outside = LineString([(20, 20), (30, 20)])
    result = fg.select_paths([inside, crossing, outside], [box(0, 0, 4, 10)])
    assert total_length(result) == pytest.approx(1 + 3)
    assert fg.select_paths([outside], [box(0, 0, 4, 10)]) == []
    assert len(fg.select_paths([inside, outside], None)) == 2


def test_aperture_filter_uses_only_the_chosen_apertures():
    groups = fg.follow_groups(source(TOOLS), params(apertures=[11]))
    assert len(groups) == 1
    assert groups[0][0] == 0.1
    assert total_length(groups[0][1]) == pytest.approx(5.0)


def test_aperture_dia_mode_groups_by_size_and_regions_use_default_dia():
    groups = fg.follow_groups(source(TOOLS), params(dia_mode='aperture'))
    by_dia = {dia: total_length(lines) for dia, lines in groups}
    assert by_dia == {0.1: pytest.approx(5.0), 0.2: pytest.approx(10.0), 0.4: pytest.approx(5.0)}


@pytest.mark.parametrize('dia_mode', ['default', 'aperture'])
def test_a_polygon_follow_geometry_without_aperture_data_is_followed(dia_mode):
    """A Gerber from the DXF import keeps a Polygon in follow_geometry and has no aperture follow data."""
    groups = fg.follow_groups(source({}, follow=box(0, 0, 2, 2)),
                              params(union=True, simplify=True, tolerance=0.01, dia_mode=dia_mode))
    assert len(groups) == 1 and groups[0][0] == 0.1
    assert total_length(groups[0][1]) == pytest.approx(8.0)


def test_follow_groups_selection_and_empty_groups_dropped():
    groups = fg.follow_groups(source(TOOLS), params(dia_mode='aperture', selection=[box(-1, -1, 6, 6)]))
    assert sorted(dia for dia, _ in groups) == [0.2, 0.4]


@pytest.mark.parametrize('value, expected', [
    (2, [2.0]), ('0.1, 0.2', [0.1, 0.2]), ((0.5, 0.0), [0.5]),
])
def test_tool_dias_accepts(value, expected):
    assert fg.tool_dias(value) == expected


@pytest.mark.parametrize('value', ['', 'abc'])
def test_tool_dias_rejects(value):
    with pytest.raises(ValueError):
        fg.tool_dias(value)


def test_geometry_data_copies_only_geometry_and_mill_keys():
    options = {'geometry_cutz': -0.1, 'tools_mill_tooldia': 0.2, 'tools_mill_feedrate': 100,
               'tools_drilling_depth': 1, 'gerber_plot': True}
    assert fg.geometry_data(options, 'a') == {'cutz': -0.1, 'tools_mill_tooldia': 0.2, 'tools_mill_feedrate': 100,
                                              'name': 'a'}


def test_follow_tools_shape():
    groups = [(0.1, [LineString([(0, 0), (1, 0)])]), (0.25, [LineString([(0, 1), (1, 1)])])]
    data = {'name': 'a', 'tools_mill_tooldia': 9.0, 'cutz': -0.1}
    tools = fg.follow_tools(groups, data, 4)
    assert sorted(tools) == [1, 2]
    assert tools[2]['tooldia'] == 0.25
    assert tools[2]['offset'] == 'Path' and tools[2]['tool_type'] == 'C1' and tools[2]['type'] == 'Rough'
    assert tools[2]['data']['tools_mill_tooldia'] == 0.25
    assert tools[1]['data'] is not tools[2]['data'] and data['tools_mill_tooldia'] == 9.0
    assert tools[1]['solid_geometry'] == groups[0][1]


def test_inputs_are_not_mutated():
    tools = {k: {'size': v['size'], 'geometry': [dict(r) for r in v['geometry']]} for k, v in TOOLS.items()}
    src = source(tools)
    follow_before = list(src.follow_geometry)
    wkt_before = [r['follow'].wkt for t in tools.values() for r in t['geometry']]
    fg.follow_groups(src, params(union=True, simplify=True, tolerance=0.1, selection=[box(0, 0, 3, 11)],
                                 dia_mode='aperture'))
    assert src.follow_geometry == follow_before
    assert [r['follow'].wkt for t in tools.values() for r in t['geometry']] == wkt_before


# ---------------------------------------------------------------------------------------------------------------
# the controller (appPlugins/ToolFollow/Follow.py)
# ---------------------------------------------------------------------------------------------------------------

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from appPlugins.ToolFollow import ToolFollow

_METHODS = ('collect', '_opt', '_combo_object', '_set_busy', '_start', 'on_generate_geometry_click', 'worker_job',
            'check_abort', 'on_job_done', 'finish', 'store_values', 'draw_preview', 'clear_preview',
            'start_area_selection', 'end_area_selection', 'finish_area_selection', 'on_key_press',
            'on_mouse_release', 'on_mouse_move')


def gerber(name):
    follow = [LineString([(0, 0), (5, 0)]), LineString([(5, 0), (5, 5)])]
    return NS(kind='gerber', obj_options={'name': name}, follow_geometry=follow,
              tools={10: {'type': 'C', 'size': 0.2, 'geometry': [{'follow': f} for f in follow]}})


def make_tool(sources, selected=None, select='all', **ui_values):
    app = MagicMock()
    app.defaults = None
    app.options = {'tools_mill_tooldia': 0.1, 'geometry_cutz': -0.1, 'tools_mill_feedrate': 50.0,
                   'tools_follow_suffix': '_follow', 'global_cursor_width': 2, 'global_cursor_size': 20}
    app.collection.get_names.return_value = ['a_follow']
    app.collection.get_selected.return_value = sources if selected is None else selected
    app.collection.get_by_name.side_effect = lambda n: next((s for s in sources if s.obj_options['name'] == n), None)
    app.worker_task.emit.side_effect = lambda task: task['fcn'](*task['params'])
    app.proc_container.new.side_effect = lambda *a: contextmanager(lambda: (yield))()
    app.abort_flag = False
    app.plotcanvas.translate_coords.return_value = (0, 0)
    app.grid_status.return_value = False
    values = dict(simplify_cb=False, tol_entry=0.0, union_cb=False, merge_cb=True, dia_mode_radio='default',
                  select_method_radio=select, area_shape_radio='square')
    values.update(ui_values)
    ui = MagicMock()
    for key, value in values.items():
        getattr(ui, key).get_value.return_value = value
    ui.object_combo.currentText.return_value = sources[0].obj_options['name']
    ui.selected_apertures.return_value = None
    tool = NS(app=app, ui=ui, decimals=4, pluginName='Follow', _busy=False, _preview_drawn=False, selecting=False,
              pending_params=None, first_click=False, cursor_pos=None, points=[], poly_drawn=False, sel_rect=[],
              mouse_is_dragging=False, cursor_width=1, cursor_size=20, job_done=MagicMock(), created=[],
              in_group=False)
    for name in _METHODS:
        setattr(tool, name, getattr(ToolFollow, name).__get__(tool))
    tool.delete_moving_selection_shape = MagicMock()
    tool.delete_tool_selection_shape = MagicMock()
    tool.job_done.emit.side_effect = tool.on_job_done

    def new_object(kind, name, init, **kwargs):
        obj = NS(obj_options={}, in_group=tool.in_group)
        init(obj, app)
        tool.created.append((kind, name, obj))
        return obj

    tool.new_object = new_object
    return tool


def messages(tool):
    return [c.args[0] for c in tool.app.inform.emit.call_args_list if c.args]


def test_generate_makes_one_geometry_per_source_in_one_undo_step_with_unique_names():
    a, b = gerber('a.gbr'), gerber('b')
    tool = make_tool([a, b])
    steps = []

    @contextmanager
    def group(name):
        steps.append(name)
        tool.in_group = True
        yield
        tool.in_group = False

    with patch('appPlugins.ToolFollow.Follow.history_of') as history:
        history.return_value.group = group
        tool.on_generate_geometry_click()
    assert steps == ['Follow']
    assert [(k, n) for k, n, _o in tool.created] == [('geometry', 'a_follow_1'), ('geometry', 'b_follow')]
    assert all(o.in_group for _k, _n, o in tool.created)
    obj = tool.created[1][2]
    assert obj.multigeo is True and obj.obj_options['tools_mill_tooldia'] == 0.1
    tool_1 = obj.tools[1]
    assert tool_1['tooldia'] == 0.1 and tool_1['offset'] == 'Path'
    assert tool_1['data']['name'] == 'b_follow' and tool_1['data']['cutz'] == -0.1
    assert total_length(obj.solid_geometry) == pytest.approx(10.0)
    assert any(m.startswith('[success]') and 'b_follow' in m for m in messages(tool))


def test_generate_leaves_the_source_follow_geometry_unchanged():
    src = gerber('a')
    before = [g.wkt for g in src.follow_geometry]
    tool = make_tool([src])
    tool.on_generate_geometry_click()
    assert len(tool.created) == 1, messages(tool)
    assert [g.wkt for g in src.follow_geometry] == before


def test_the_job_follows_the_source_as_it_was_at_the_click():
    src = gerber('a')
    tool = make_tool([src])
    tasks = []
    tool.app.worker_task.emit.side_effect = tasks.append
    tool.on_generate_geometry_click()
    src.follow_geometry.clear()
    src.tools[10]['geometry'].clear()
    for task in tasks:
        task['fcn'](*task['params'])
    (_kind, _name, obj), = tool.created
    assert total_length(obj.solid_geometry) == pytest.approx(10.0)


def test_a_failed_creation_is_reported_and_the_other_sources_are_created():
    a, b = gerber('a'), gerber('b')
    tool = make_tool([a, b])
    create = tool.new_object
    tool.new_object = lambda kind, name, init, **kw: 'fail' if name.startswith('a') else create(kind, name, init, **kw)
    tool.on_generate_geometry_click()
    assert [n for _k, n, _o in tool.created] == ['b_follow']
    text = ' '.join(messages(tool))
    assert 'a_follow_1' in text and '1 of 2' in text


def test_generate_uses_the_combo_object_when_nothing_is_selected_and_reports_when_there_is_none():
    tool = make_tool([gerber('a')], selected=[])
    tool.on_generate_geometry_click()
    assert [n for _k, n, _o in tool.created] == ['a_follow_1']
    other = NS(kind='geometry', obj_options={'name': 'g'})
    tool = make_tool([other], selected=[other])
    tool.on_generate_geometry_click()
    assert tool.created == [] and 'No Gerber object is selected.' in ' '.join(messages(tool))


def test_empty_result_creates_nothing_and_names_the_source():
    empty = NS(kind='gerber', obj_options={'name': 'e'}, follow_geometry=[], tools={})
    tool = make_tool([empty])
    tool.on_generate_geometry_click()
    assert tool.created == []
    assert any('e' in m and m.startswith('[WARNING_NOTCL]') for m in messages(tool))
    assert not any(m.startswith('[success]') for m in messages(tool))


def test_unusable_tool_diameter_gives_an_error_and_no_job():
    tool = make_tool([gerber('a')])
    tool.app.options['tools_mill_tooldia'] = 0
    tool.on_generate_geometry_click()
    assert tool.created == [] and not tool.app.worker_task.emit.called
    assert any(m.startswith('[ERROR_NOTCL]') for m in messages(tool))


def test_area_job_uses_the_zones_copied_in_the_gui_thread():
    tool = make_tool([gerber('a')], select='area')
    tool.on_generate_geometry_click()
    assert tool.selecting and not tool.app.worker_task.emit.called
    tool.sel_rect.append(box(-1, -1, 6, 1))
    tool.on_mouse_release(NS(pos=(0, 0), button=2))
    assert not tool.selecting and tool.sel_rect == []
    (_kind, _name, obj), = tool.created
    # the horizontal path is inside the zone, the vertical one is clipped to its first unit
    assert total_length(obj.solid_geometry) == pytest.approx(6.0)


def test_right_click_without_a_zone_gives_a_message_and_no_job():
    tool = make_tool([gerber('a')], select='area')
    tool.on_generate_geometry_click()
    tool.on_mouse_release(NS(pos=(0, 0), button=2))
    assert not tool.selecting and not tool.app.worker_task.emit.called and tool.created == []
    assert any(m.startswith('[WARNING_NOTCL]') for m in messages(tool))


def test_escape_ends_the_area_selection_and_restores_the_app_handlers():
    tool = make_tool([gerber('a')], select='area')
    tool.on_generate_geometry_click()
    tool.first_click, tool.cursor_pos, tool.points, tool.sel_rect = True, (1, 1), [(0, 0)], [box(0, 0, 1, 1)]
    tool.on_key_press(NS(key='Escape'))
    assert not tool.selecting and not tool.first_click and tool.cursor_pos is None
    assert tool.points == [] and tool.sel_rect == [] and not tool.app.worker_task.emit.called
    connect = tool.app.plotcanvas.graph_event_connect
    connect.assert_any_call('mouse_press', tool.app.on_mouse_click_over_plot)
    connect.assert_any_call('mouse_move', tool.app.on_mouse_move_over_plot)
    connect.assert_any_call('mouse_release', tool.app.on_mouse_click_release_over_plot)
    tool.app.ui.notebook.setDisabled.assert_called_with(False)
    tool.app.delete_selection_shape.assert_called()


# Tcl follow


def follow_source():
    # two touching segments (one path after the merge), a flash (a Point) and a second aperture size
    tools = {
        10: {'size': 0.2, 'geometry': [{'follow': LineString([(0, 0), (5, 0)])},
                                       {'follow': LineString([(5, 0), (10, 0)])},
                                       {'follow': Point(20, 20)}]},
        11: {'size': 0.4, 'geometry': [{'follow': LineString([(0, 5), (10, 5)])}]},
    }
    follow = [el['follow'] for t in tools.values() for el in t['geometry']]
    return NS(kind='gerber', obj_options={'name': 'cu.gtl'}, follow_geometry=follow, tools=tools)


def run_follow(args, source=None):
    from tclCommands.TclCommandFollow import TclCommandFollow
    app = factory_app(source or follow_source())
    app.decimals = 4
    TclCommandFollow(app).execute({'name': 'cu.gtl', **args}, [])
    return app


def created(app):
    kind, name, init = app.app_obj.new_object.call_args[0]
    new = Mock()
    new.obj_options = {}
    init(new, app)
    return kind, name, new


def test_default_call_makes_a_geometry_with_merged_lines_and_no_points():
    app = run_follow({})
    kind, name, new = created(app)
    assert (kind, name) == ('geometry', 'cu_follow')
    assert app.app_obj.new_object.call_args[1]['plot'] is False
    assert new.multigeo is True
    assert all(isinstance(g, LineString) for g in new.solid_geometry)
    assert sorted(g.length for g in new.solid_geometry) == pytest.approx([10.0, 10.0])
    assert new.tools[1]['tooldia'] == pytest.approx(2.4)
    assert new.tools[1]['solid_geometry'] == new.solid_geometry


def test_box_clips_the_paths():
    _kind, _name, new = created(run_follow({'box': '0,-1,4,1', 'outname': 'part'}))
    assert [g.bounds for g in new.solid_geometry] == [pytest.approx((0, 0, 4, 0))]


def test_aperture_mode_makes_one_tool_per_aperture_size():
    _kind, _name, new = created(run_follow({'dia_mode': 'aperture'}))
    assert sorted(t['tooldia'] for t in new.tools.values()) == pytest.approx([0.2, 0.4])
    for tool in new.tools.values():
        assert tool['data']['tools_mill_tooldia'] == tool['tooldia']


@pytest.mark.parametrize('args', [{'box': '100,100,110,110'}, {'apertures': '99'}, {'dia_mode': 'nope'},
                                  {'box': '1,2,3'}, {'tooldia': 0}, {'union': 'maybe'}])
def test_bad_input_or_empty_result_is_a_tcl_error_and_creates_nothing(args):
    from tclCommands.TclCommandFollow import TclCommandFollow
    app = factory_app(follow_source())
    with pytest.raises(FCShell.TclErrorException):
        TclCommandFollow(app).execute({'name': 'cu.gtl', **args}, [])
    app.app_obj.new_object.assert_not_called()


def test_unknown_or_non_gerber_object_is_a_tcl_error():
    from tclCommands.TclCommandFollow import TclCommandFollow
    app = factory_app(None)
    with pytest.raises(FCShell.TclErrorException):
        TclCommandFollow(app).execute({'name': 'cu.gtl'}, [])
    app = factory_app(NS(kind='geometry'))
    with pytest.raises(FCShell.TclErrorException):
        TclCommandFollow(app).execute({'name': 'cu.gtl'}, [])
