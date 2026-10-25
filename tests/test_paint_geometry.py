"""Run: python tests/test_paint_geometry.py"""
import contextlib
import io
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_saved_argv = sys.argv
sys.argv = [sys.argv[0]]
try:
    import camlib
    from appPlugins.ToolNCC.NccGen import NccGen
    from appPlugins.ToolPaint import PaintModel
    from appPlugins.ToolPaint.PaintGen import PaintGen
    from shapely import LineString, LinearRing, MultiPolygon, Point, Polygon, box
finally:
    sys.argv = _saved_argv


def storage_of(paths):
    storage = camlib.AppRTreeStorage()
    storage.get_points = lambda go: [go.coords[0], go.coords[-1]]
    for path in paths:
        storage.insert(path)
    return storage


def paint_worker(geometry, diameters, method=2):
    worker = PaintGen.__new__(PaintGen)
    worker.app = geometry.app
    worker.app.inform = Mock()
    worker.units = 'MM'
    worker.decimals = 4
    worker.circle_steps = 64
    worker.parent_tool = geometry
    worker.ui = SimpleNamespace(rest_offset_entry=SimpleNamespace(get_value=lambda: 0))
    worker._cleanup_progressive_plotting = Mock()
    params = SimpleNamespace(
        paint_method=method, prog_plot=False, simplification_value=0, output_object_name='paint',
        rest_offset=0.0, tools_storage={
            i: {'tooldia': dia, 'solid_geometry': [], 'data': {
                'tools_paint_overlap': 15, 'tools_paint_connect': False,
                'tools_paint_contour': True, 'tools_paint_offset': 0}}
            for i, dia in enumerate(diameters, 1)})
    return worker, params


class TestPaintGeometry(unittest.TestCase):
    def setUp(self):
        self.geometry = camlib.Geometry.__new__(camlib.Geometry)
        self.geometry.app = SimpleNamespace(abort_flag=False, log=Mock(), inform_no_echo=Mock(),
                                            proc_container=Mock())
        self.polygon = Polygon(box(0, 0, 6, 6).exterior.coords,
                               [box(2, 2, 4, 4).exterior.coords])

    def test_shrink_uses_configured_circle_accuracy_for_cumulative_offsets(self):
        from test_shrink_offsets import inset_layers, layer_paths
        for steps in (1, 16, 17, 64):
            with self.subTest(steps=steps):
                paths = list(camlib.Geometry.clear_polygon_shrink(
                    self.geometry, self.polygon, 1, steps, connect=False).get_objects())
                expected = layer_paths(inset_layers(self.polygon, 1, 0.15, steps, True, bounded=True))
                self.assertEqual(len(paths), len(expected))
                self.assertTrue(all(a.equals_exact(b, 1e-12) for a, b in zip(paths, expected)))

    def test_trace_filling_uses_full_circle_steps(self):
        line = LineString([(1, 3), (5, 3)])
        paths = list(camlib.Geometry.fill_with_lines(
            self.geometry, line, 2, 0.5, 64, connect=False).get_objects())
        expected = line.buffer(1, quad_segs=16).buffer(-0.25, quad_segs=16)
        rings = [path for path in paths if isinstance(path, LinearRing)]
        self.assertEqual(len(rings), 1)
        self.assertTrue(rings[0].equals_exact(expected.exterior, 1e-12))

    def test_connect_reverses_nearest_end_and_lifts_for_long_walk(self):
        paths = [LineString([(1, 1), (2, 1)]), LineString([(4, 1), (3, 1)]),
                 LineString([(8, 1), (9, 1)])]
        result = camlib.Geometry.paint_connect(storage_of(paths), box(0, 0, 10, 3), 0.2, 64, max_walk=2)
        self.assertEqual([list(path.coords) for path in result.get_objects()],
                         [[(1, 1), (2, 1), (3, 1), (4, 1)], [(8, 1), (9, 1)]])

    def test_connect_lifts_at_a_hole(self):
        boundary = Polygon(box(0, 0, 8, 3).exterior.coords,
                           [box(2.5, 0.5, 3.5, 1.5).exterior.coords])
        paths = [LineString([(1, 1), (2, 1)]), LineString([(5, 1), (6, 1)])]
        result = camlib.Geometry.paint_connect(storage_of(paths), boundary, 0.2, 64)
        self.assertEqual([list(path.coords) for path in result.get_objects()],
                         [list(path.coords) for path in paths])

    def test_paint_and_ncc_dispatch_to_the_same_clearing_paths(self):
        worker = SimpleNamespace(app=self.geometry.app, parent_tool=self.geometry, circle_steps=64)
        for method in (0, 1, 2):
            for connect in (False, True):
                with self.subTest(method=method, connect=connect):
                    painted = PaintGen.paint_polygon_worker(
                        worker, self.polygon, 1, method, 0.15, connect, True, False, None)
                    cleared = NccGen.clear_polygon_worker(
                        worker, self.polygon, 1, method, 0.15, connect, True, False)
                    self.assertIsNotNone(painted)
                    self.assertIsNotNone(cleared)
                    self.assertEqual([list(path.coords) for path in painted.get_objects()],
                                     [list(path.coords) for path in cleared])
        self.geometry.app.log.error.assert_not_called()

    def test_unpaintable_polygon_is_skipped_and_the_job_goes_on(self):
        from appPlugins.ToolPaint import PaintModel
        bad, good = box(0, 0, 4, 4), box(10, 0, 14, 4)
        tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': []},
                 2: {'tooldia': 0.5, 'data': {}, 'solid_geometry': []}}
        line = LineString([(11, 2), (13, 2)])

        def process(polygon, diameter, settings):
            if polygon.bounds[0] < 5:
                return 'fail'
            return SimpleNamespace(get_objects=lambda: [line])

        kwargs = dict(find_uid=lambda dia, storage: 1 if dia == 1.0 else 2,
                      get_params=lambda uid, storage: {'offset': 0.0},
                      buffer=lambda geo, off: list(geo), simplify=lambda geo, tol: list(geo))
        for rest in (False, True):
            with self.subTest(rest=rest):
                generate = PaintModel.generate_rest_paint if rest else PaintModel.generate_paint
                ordering = () if rest else (0,)
                result = generate([bad, good], tools, [1.0, 0.5], *ordering, 0.0, 4, process, **kwargs)
                self.assertNotEqual(result, 'fail')
                self.assertTrue(any(tool['solid_geometry'] for tool in result['tools'].values()))
                self.assertTrue(any(kind == 'skipped' for kind, _detail in result['warnings']))

    def test_final_cleanup_adds_cleanup_paths_only_when_flagged(self):
        standard, cleanup_path = LineString([(1, 1), (2, 1)]), LineString([(3, 3), (3.5, 3)])
        residual = box(5, 5, 5.2, 5.2)
        data = {'tools_paint_overlap': 15, 'tools_paint_connect': False,
                'tools_paint_contour': True, 'tools_paint_offset': 0}

        def process(polygon, diameter, settings):
            return SimpleNamespace(get_objects=lambda: [standard])

        def cleanup(domain, diameter, previous, generate_paths, boundary_first):
            return [cleanup_path], residual

        for flag in (True, False):
            with self.subTest(flag=flag):
                storage = {1: {'tooldia': 1.0, 'data': {**data, 'tools_paint_final_cleanup': flag},
                               'solid_geometry': []}}
                output_tools = {1: {'tooldia': 1.0, 'data': dict(data), 'solid_geometry': [standard]}}
                result = PaintModel.final_cleanup([self.polygon], storage, output_tools, [1.0], 4,
                                                  process, cleanup)
                if flag:
                    self.assertEqual([list(path.coords) for path in result['output_tools'][1]['solid_geometry']],
                                     [list(standard.coords), list(cleanup_path.coords)])
                    self.assertEqual(result['output_tools'][1]['paint_cleanup_start'], 1)
                    self.assertIs(result['residual'], residual)
                    self.assertIn(('cleanup', None), result['warnings'])
                else:
                    self.assertIsNone(result['residual'])
                    self.assertEqual(result['warnings'], [])
                    self.assertEqual([list(path.coords) for path in result['output_tools'][1]['solid_geometry']],
                                     [list(standard.coords)])
                # The caller's tool dicts are never changed.
                self.assertEqual(len(output_tools[1]['solid_geometry']), 1)
                self.assertNotIn('paint_cleanup_start', output_tools[1])
                self.assertNotIn('paint_cleanup_start', storage[1])

    def test_tool_table_keeps_empty_tools_after_a_job(self):
        for rest in (False, True):
            with self.subTest(rest=rest):
                worker, params = paint_worker(self.geometry, [1.0, 50.0])
                output = SimpleNamespace(tools={}, obj_options={})
                generate = worker._generate_rest_paint_worker if rest else worker._generate_paint_worker
                with contextlib.redirect_stdout(io.StringIO()):
                    result = generate(output, worker.app, params, [1.0, 50.0], [self.polygon], None, False)
                self.assertNotEqual(result, 'fail')
                self.assertEqual(list(output.tools), [1])
                self.assertTrue(output.tools[1]['solid_geometry'])
                self.assertEqual(sorted(params.tools_storage), [1, 2])
                for tool in params.tools_storage.values():
                    self.assertEqual(tool['solid_geometry'], [])

    def test_selection_kernels_pick_contained_polygon_and_clip_to_area(self):
        left, right = box(0, 0, 4, 4), box(10, 0, 14, 4)
        with self.subTest('point inside'):
            self.assertTrue(PaintModel.select_polygon([left, right], (12, 2)).equals(right))
        with self.subTest('point outside'):
            self.assertIsNone(PaintModel.select_polygon([left, right], (7, 2)))
        with self.subTest('area clip'):
            painted = PaintModel.area_intersection(MultiPolygon([left, right]), [box(-1, -1, 5, 5)])
            self.assertAlmostEqual(sum(part.area for part in painted), 16)
            self.assertTrue(all(part.within(box(-1, -1, 5, 5)) for part in painted))
        for label, geometry in (('single list', [left]), ('multipolygon', MultiPolygon([left, right])),
                                ('list of two', [left, right])):
            with self.subTest('reference area', geometry=label):
                expected = geometry.bounds if hasattr(geometry, 'bounds') else camlib.unary_union(geometry).bounds
                reference = PaintModel.reference_area(geometry)
                self.assertTrue(all(abs(a - b) < 1e-6 for a, b in zip(reference.bounds, expected)))

    def test_split_overlapping_and_failing_polygons_still_give_paths(self):
        # A dumbbell splits on buffering, overlapping sources are painted once, and one polygon
        # that raises keeps the paths of the others.
        dumbbell = camlib.unary_union([box(0, 0, 4, 4), box(3.9, 1.8, 6.1, 2.2), box(6, 0, 10, 4)])
        self.assertEqual(len(PaintModel.buffer_geometry(dumbbell, 0.5)), 2)
        calls = []

        def process(polygon, diameter, settings):
            calls.append(polygon)
            if polygon.bounds[0] > 20:
                raise ValueError('boom')
            return SimpleNamespace(get_objects=lambda: [LineString([polygon.bounds[:2], polygon.bounds[2:]])])

        tool = {'tooldia': 1.0, 'data': {}, 'solid_geometry': []}
        result = PaintModel.generate_paint(
            [box(0, 0, 4, 4), box(2, 0, 6, 4), box(30, 0, 34, 4)], {0: tool}, [1.0], 0, 0.0, 4, process,
            find_uid=lambda dia, storage: 0, get_params=lambda uid, storage: {'offset': 0.0},
            simplify=lambda geo, tol: list(geo))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result['tools'][0]['solid_geometry']), 1)
        self.assertTrue(any(kind == 'normal' for kind, _detail in result['warnings']))

    def test_progress_restarts_for_every_tool_and_reaches_the_end(self):
        tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': []},
                 2: {'tooldia': 0.5, 'data': {}, 'solid_geometry': []}}
        seen = []

        def progress(number, total, old):
            seen.append((number, total, old))
            return number

        def process(polygon, diameter, settings):
            return SimpleNamespace(get_objects=lambda: [LineString([(1, 1), (2, 1)])])

        kwargs = dict(find_uid=lambda dia, storage: 1 if dia == 1.0 else 2, progress=progress,
                      get_params=lambda uid, storage: {'offset': 0.0}, simplify=lambda geo, tol: list(geo))
        PaintModel.generate_paint([box(0, 0, 4, 4), box(10, 0, 14, 4)], tools, [1.0, 0.5], 0, 0.0, 4,
                                  process, **kwargs)
        self.assertEqual([old for _n, _t, old in seen], [0, 1, 0, 1])
        seen.clear()
        PaintModel.generate_rest_paint([box(0, 0, 4, 4), box(10, 0, 10.3, 0.3)], tools, [1.0], 0.0, 4,
                                       process, **kwargs)
        self.assertEqual(seen[-1][:2], (2, 2))

    def test_tool_uid_zero_and_string_diameters_are_found(self):
        tools = {0: {'tooldia': 0.5}, 1: {'tooldia': 1.0}}
        self.assertEqual(PaintModel.find_tool_uid('0.5', tools, 4), 0)
        self.assertIsNone(PaintModel.find_tool_uid(0.25, tools, 4))
        tool = {'tooldia': 0.5, 'solid_geometry': [], 'data': {
            'tools_paint_overlap': 15, 'tools_paint_connect': False, 'tools_paint_contour': True,
            'tools_paint_offset': 0}}
        result = PaintModel.generate_paint(
            [box(0, 0, 4, 4)], {0: tool}, [0.5], 0, 0.0, 4,
            lambda polygon, diameter, settings: SimpleNamespace(get_objects=lambda: [LineString([(1, 1), (2, 1)])]))
        self.assertEqual(len(result['tools'][0]['solid_geometry']), 1)

    def test_combo_method_falls_through_a_failing_method(self):
        def broken(*args, **kwargs):
            raise ValueError('boom')

        good = SimpleNamespace(objects=[1], get_objects=lambda: [1])
        result = PaintModel.paint_polygon(self.polygon, 1, 4, 0.15, False, True, False, 64,
                                          lambda *a, **k: good, lambda *a, **k: good, broken)
        self.assertIs(result, good)

    def test_laser_lines_takes_only_traces_inside_the_polygon(self):
        inside, outside = LineString([(1, 1), (5, 1)]), LineString([(20, 1), (25, 1)])
        apertures = {'10': {'size': 0.0, 'type': 'C', 'geometry': [
            {'follow': inside}, {'follow': outside}, {'solid': inside.buffer(0.1)}]}}
        filled = []

        def fill(line, size, **kwargs):
            filled.append(line)
            return SimpleNamespace(get_objects=lambda: [line])

        for index in (None, PaintModel.aperture_index(apertures)):
            filled.clear()
            result = PaintModel.laser_lines(box(0, 0, 6, 6), 0.2, 0.15, False, True, False, 64, 64,
                                            apertures, None, None, fill, index=index)
            self.assertEqual([line.wkt for line in filled], [inside.wkt])
            self.assertEqual(len(list(result.get_objects())), 1)
        empty = PaintModel.laser_lines(box(40, 40, 46, 46), 0.2, 0.15, False, True, False, 64, 64,
                                       apertures, None, None, fill)
        self.assertEqual(list(empty.get_objects()), [])

    def test_area_intersection_keeps_every_area_and_drops_touching_artifacts(self):
        left, right = box(0, 0, 4, 4), box(10, 0, 14, 4)
        painted = PaintModel.area_intersection(
            camlib.unary_union([left, right, box(4, 0, 6, 4)]),
            [box(-1, -1, 4, 5), box(9, -1, 15, 5), box(6, 1, 7, 2)])
        self.assertAlmostEqual(sum(part.area for part in painted), 32)
        self.assertEqual(PaintModel.area_intersection(left, box(4, 0, 8, 4)), [])
        self.assertEqual(PaintModel.area_intersection(left, box(4, 4, 8, 8)), [])

    def test_reference_area_is_the_exact_union_not_a_hull(self):
        reference = PaintModel.reference_area([[box(0, 0, 4, 1), box(0, 0, 1, 4)], [box(10, 10, 11, 11)]])
        self.assertAlmostEqual(reference.area, 7 + 1, places=4)
        self.assertTrue(reference.contains(Point(0.5, 3.5)))
        self.assertFalse(reference.contains(Point(3.5, 3.5)))

    def test_select_polygon_picks_the_hit_in_a_nested_set(self):
        cells = [box(x, y, x + 0.9, y + 0.9) for x in range(200) for y in range(100)]
        nested = [cells[:5000], [LinearRing(box(500, 500, 502, 502).exterior.coords)], cells[5000:]]
        self.assertTrue(PaintModel.select_polygon(nested, (150.5, 40.5)).equals(box(150, 40, 150.9, 40.9)))
        self.assertTrue(PaintModel.select_polygon(nested, (501, 501)).equals(box(500, 500, 502, 502)))
        self.assertIsNone(PaintModel.select_polygon(nested, (150.95, 40.5)))

    def test_rest_stock_keeps_the_polygon_the_big_tool_could_not_paint(self):
        wide, narrow = box(0, 0, 6, 6), box(10, 0, 10.8, 5)
        tools = {1: {'tooldia': 1.0, 'data': {}, 'solid_geometry': []},
                 2: {'tooldia': 0.5, 'data': {}, 'solid_geometry': []}}
        seen = []

        def process(polygon, diameter, settings):
            seen.append((diameter, polygon.bounds))
            return SimpleNamespace(get_objects=lambda: [LineString([(polygon.bounds[0] + diameter, 3),
                                                                   (polygon.bounds[2] - diameter, 3)])])

        PaintModel.generate_rest_paint(
            [wide, narrow], tools, [1.0, 0.5], 0.0, 4, process,
            find_uid=lambda dia, storage: 1 if dia == 1.0 else 2,
            get_params=lambda uid, storage: {'offset': 0.0}, simplify=lambda geo, tol: list(geo))
        self.assertTrue(any(diameter == 0.5 and bounds[0] >= 10 for diameter, bounds in seen))

    def test_paint_area_fails_without_overlap_or_when_the_handler_fails(self):
        paint_gen = PaintGen.__new__(PaintGen)
        paint_gen.app = SimpleNamespace(abort_flag=False, log=Mock(), inform=Mock())
        painted = SimpleNamespace(kind='geometry', solid_geometry=box(0, 0, 4, 4))
        with self.subTest('no overlap'):
            self.assertEqual(paint_gen.paint_poly_area_worker(painted, box(10, 10, 12, 12), run_threaded=False), 'fail')
        with self.subTest('handler fails'), patch.object(PaintGen, 'paint_handler', return_value='fail'):
            self.assertEqual(paint_gen.paint_poly_area_worker(painted, box(1, 1, 3, 3)), 'fail')

    def _job_worker(self, abort=False, new_object_result='fail'):
        worker = PaintGen.__new__(PaintGen)
        worker.app = SimpleNamespace(abort_flag=abort, log=Mock(), inform=Mock(), proc_container=Mock(),
                                     collection=Mock(), units='MM', options={})
        worker.obj_name = 'src'
        worker.decimals = 4
        worker.parent_tool = SimpleNamespace(paint_tools={}, new_object=Mock(return_value=new_object_result))
        worker.ui = None
        return worker

    def _messages(self, worker):
        return ' '.join(str(call.args[0]) for call in worker.app.inform.emit.call_args_list)

    def test_controller_state_is_read_live_not_copied(self):
        worker = PaintGen.__new__(PaintGen)
        worker.parent_tool = SimpleNamespace(paint_tools={1: {}}, points=[], first_click=False)
        worker.parent_tool.paint_tools = {2: {}}
        worker.parent_tool.points.append((1, 1))
        worker.parent_tool.first_click = True
        self.assertEqual(worker.paint_tools, {2: {}})
        self.assertEqual(worker.points, [(1, 1)])
        self.assertTrue(worker.first_click)

    def test_each_tool_uses_its_own_method_and_a_forced_method_wins(self):
        worker, params = paint_worker(self.geometry, [1.0, 0.5], method=0)
        params.tools_storage[1]['data']['tools_paint_method'] = 2
        gerber, geo = SimpleNamespace(kind='gerber'), SimpleNamespace(kind='geometry')
        first = worker._get_tool_params(1, params.tools_storage)
        second = worker._get_tool_params(2, params.tools_storage)
        self.assertEqual(worker._tool_method(first, params, geo), 2)
        self.assertEqual(worker._tool_method(second, params, geo), 0)
        params.paint_method_explicit = True
        self.assertEqual(worker._tool_method(first, params, geo), 0)
        # Laser lines exist for Gerber only
        params.paint_method, params.paint_method_explicit = 3, False
        self.assertEqual(worker._tool_method(second, params, gerber), 3)
        self.assertEqual(worker._tool_method(second, params, geo), 0)

    def test_rest_offset_and_simplification_overrides_beat_the_form_and_options(self):
        worker = self._job_worker()
        worker.app.units = 'IN'
        worker.app.options = {'tools_paint_simplification': 0.254}
        params = worker._create_params(0, 2, True, 'out', None)
        self.assertAlmostEqual(params.simplification_value, 0.01)
        self.assertEqual(params.rest_offset, 0.0)    # headless: the option, not a form
        params = worker._create_params(0, 2, True, 'out', None, rest_offset=0.3, simplification=0.5)
        self.assertEqual((params.rest_offset, params.simplification_value), (0.3, 0.5))
        self.assertTrue(params.paint_method_explicit)
        self.assertEqual(worker._create_params(0, 2, False, 'out', None, rest_offset=0.3).rest_offset, 0.0)

    def test_user_abort_reports_a_cancel_and_failure_reports_failed(self):
        for abort, expected in ((True, 'Cancelled.'), (False, 'Failed.')):
            with self.subTest(abort=abort):
                worker = self._job_worker(abort=abort)
                result = worker.paint_handler(
                    SimpleNamespace(kind='geometry'), [box(0, 0, 4, 4)], tooldia=[0.5], run_threaded=False)
                self.assertEqual(result, 'fail')
                self.assertIn(expected, self._messages(worker))
                worker.app.collection.remove_promise.assert_called()

    def test_a_tool_too_big_for_the_geometry_says_so_instead_of_failing_silently(self):
        worker, params = paint_worker(self.geometry, [10.0])
        worker._process_polygon = Mock(return_value=None)
        output = SimpleNamespace(tools={}, obj_options={})
        result = worker._generate_paint_worker(output, worker.app, params, [10.0], [self.polygon], None, False)
        self.assertEqual(result, 'fail')
        self.assertIn('too big', self._messages(worker))

    def test_unknown_warning_kinds_do_not_break_reporting(self):
        worker = self._job_worker()
        worker._report_warnings([('brand-new', 'x'), ('skipped', 1.0), ('skipped', 1.0), ('normal', 'boom')])
        self.assertEqual(sum('could not be painted' in str(c.args[0]) for c in worker.app.inform.emit.call_args_list), 1)

    def test_paint_all_of_a_multigeo_geometry_takes_every_tool_and_leaves_gerber_alone(self):
        worker = self._job_worker()
        multigeo = SimpleNamespace(kind='geometry', multigeo=True, solid_geometry=None, tools={
            1: {'solid_geometry': [box(0, 0, 2, 2)]}, 2: {'solid_geometry': [box(5, 0, 7, 2)]}})
        with patch.object(PaintGen, 'paint_handler', return_value='ok') as handler:
            self.assertEqual(worker.paint_poly_all(multigeo, run_threaded=False), 'ok')
        self.assertEqual(len(handler.call_args.args[1]), 2)
        copper = box(0, 0, 3, 3)
        gerber = SimpleNamespace(kind='gerber', solid_geometry=[copper], tools={}, apertures={})
        worker.app.options = {'tools_paint_plotting': 'progressive', 'gerber_buffering': 'full'}
        with patch.object(PaintGen, 'paint_handler', return_value='ok'),                 patch('appPlugins.ToolPaint.PaintGen.gerber_copper_for_paint', return_value=copper):
            worker.paint_poly_all(gerber, run_threaded=False)
        self.assertEqual(gerber.solid_geometry, [copper])

    def test_empty_selection_warns_and_fails(self):
        worker = self._job_worker()
        painted = SimpleNamespace(kind='geometry', solid_geometry=box(0, 0, 4, 4))
        touching = box(4, 0, 6, 4)
        for call in (lambda: worker.paint_poly_area_worker(painted, touching, run_threaded=False),
                     lambda: worker.paint_poly_all(SimpleNamespace(kind='geometry', solid_geometry=[]),
                                                   run_threaded=False)):
            worker.app.inform.emit.reset_mock()
            self.assertEqual(call(), 'fail')
            self.assertIn('No polygon found', self._messages(worker))

    def _click_worker(self, selected, multi, select_method=0):
        worker = PaintGen.__new__(PaintGen)
        by_name = {obj.obj_options['name']: obj for obj in selected}
        worker.app = SimpleNamespace(
            options={'gerber_circle_steps': 12, 'geometry_circle_steps': 48}, inform=Mock(), log=Mock(),
            defaults=SimpleNamespace(report_usage=Mock(), get=lambda key, default=None: default),
            collection=SimpleNamespace(get_selected=lambda: selected, get_by_name=by_name.get))
        worker.parent_tool = SimpleNamespace(reset_selection_state=Mock(), clear_preview=Mock(), area_to_paint_list=[])
        value = lambda v: SimpleNamespace(get_value=lambda: v)
        worker.ui = SimpleNamespace(
            type_obj_radio=value('geometry'), obj_combo=SimpleNamespace(currentText=lambda: 'combo'),
            multi_objects_cb=value(multi), select_method_combo=value(select_method),
            tools_table=SimpleNamespace(
                selectedItems=lambda: [SimpleNamespace(row=lambda: 0)],
                item=lambda row, col: SimpleNamespace(text=lambda: '0.5')))
        by_name['combo'] = SimpleNamespace(kind='geometry', obj_options={'name': 'combo'})
        return worker

    def test_selected_objects_are_painted_one_job_each_with_their_own_circle_steps(self):
        gerber = SimpleNamespace(kind='gerber', obj_options={'name': 'copper'})
        geo = SimpleNamespace(kind='geometry', obj_options={'name': 'cut'})
        excellon = SimpleNamespace(kind='excellon', obj_options={'name': 'holes'})
        worker = self._click_worker([gerber, excellon, geo], multi=True)
        jobs = []
        with patch.object(PaintGen, 'paint_poly_all', side_effect=lambda obj, tooldia, outname: jobs.append(
                (obj.obj_options['name'], outname, worker.circle_steps))):
            worker.on_paint_button_click()
        self.assertEqual(jobs, [('copper', 'copper_paint', 12), ('cut', 'cut_paint', 48)])
        # nothing suitable selected: warn and do nothing
        worker = self._click_worker([excellon], multi=True)
        with patch.object(PaintGen, 'paint_poly_all') as paint_all:
            worker.on_paint_button_click()
        paint_all.assert_not_called()
        self.assertIn('select', self._messages(worker).lower())
        # unchecked: the combobox object, as before
        worker = self._click_worker([gerber, geo], multi=False)
        with patch.object(PaintGen, 'paint_poly_all') as paint_all:
            worker.on_paint_button_click()
        self.assertEqual(paint_all.call_args.args[0].obj_options['name'], 'combo')

    def test_check_validity_stops_when_no_tool_fits_inside_and_only_warns_when_some_do(self):
        # Paint cuts inside the polygons: a tool is valid if it fits inside them (the 0.3 strip is too narrow
        # for 0.5), for Geometry and Gerber sources alike.
        selected = [box(0, 0, 4, 4), box(5, 0, 5.3, 4)]
        for kind, checked, tools, runs, text in (('geometry', True, [5.0], False, 'no tool fits'),
                                                 ('gerber', True, [0.5], True, 'too narrow'),
                                                 ('geometry', True, [0.2, 5.0], True, 'fit inside no polygon'),
                                                 ('geometry', False, [5.0], True, '')):
            with self.subTest(kind=kind, checked=checked, tools=tools):
                worker = self._job_worker(new_object_result='ok')
                worker.ui = SimpleNamespace(valid_cb=SimpleNamespace(get_value=lambda c=checked: c))
                source = SimpleNamespace(kind=kind, tools={})
                result = worker.paint_handler(source, selected, tooldia=tools, run_threaded=False)
                self.assertEqual(worker.parent_tool.new_object.called, runs)
                self.assertEqual(result == 'fail', not runs)
                self.assertIn(text, self._messages(worker))


if __name__ == '__main__':
    unittest.main()
