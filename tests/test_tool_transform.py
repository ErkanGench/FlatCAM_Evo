"""ToolTransform actions: the matrix given to plot_transformed, bounds computed once, failures isolated."""
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from shapely.geometry import Polygon  # noqa: E402
from shapely.affinity import affine_transform  # noqa: E402

import camlib  # noqa: E402
from camlib import Geometry  # noqa: E402
from appPlugins.ToolTransform import ToolTransform  # noqa: E402
from appObjects.AppObject import AppObject  # noqa: E402
from appHandlers.appHistory import HistoryManager  # noqa: E402


def make_app(selected):
    app = MagicMock()
    app.inform.emit = MagicMock()
    app.app_units = "MM"
    app.collection = SimpleNamespace(get_selected=MagicMock(return_value=selected), get_by_name=lambda n: None)

    @contextmanager
    def new(_msg):
        yield

    app.proc_container = SimpleNamespace(new=new, new_text='', update_view_text=lambda *a: None)
    app.app_obj = SimpleNamespace(object_changed=MagicMock())
    return app


class FakeObj:
    """A selected object: real camlib.Geometry transforms, counted bounds / plot calls."""

    def __init__(self, app, name='g', kind='geometry', fail=False, fail_value=None):
        self.kind = kind
        self.geo = Geometry(MagicMock())
        self.geo.app = app
        self.geo.multigeo = False
        self.geo.solid_geometry = [Polygon([(0, 0), (4, 0), (4, 2), (1, 3)])]
        self.obj_options = {'name': name}
        self.history_uid = name
        self.ser_attrs = ['solid_geometry', 'obj_options']
        self.bounds_calls = 0
        self.offset_bounds = []
        self.plot_calls = 0
        self.matrices = []
        self.fail = fail
        self.fail_value = fail_value

    @property
    def solid_geometry(self):
        return self.geo.solid_geometry

    @solid_geometry.setter
    def solid_geometry(self, value):
        self.geo.solid_geometry = value

    def from_dict(self, state):
        self.solid_geometry = state['solid_geometry']
        self.obj_options.update(state['obj_options'])

    def _go(self, fcn, *a, **kw):
        if self.fail:
            raise RuntimeError("boom")
        if self.fail_value is not None:
            return self.fail_value
        return fcn(*a, **kw)

    def rotate(self, angle, point):
        return self._go(self.geo.rotate, angle, point)

    def mirror(self, axis, point):
        return self._go(self.geo.mirror, axis, point)

    def skew(self, ax, ay, point):
        return self._go(self.geo.skew, ax, ay, point)

    def scale(self, xf, yf=None, point=None):
        return self._go(self._scale, xf, yf, point)

    def _scale(self, xf, yf, point):
        px, py = (0, 0) if point is None else point
        m = camlib.affine_scale_matrix(xf, yf, (px, py))
        self.geo.solid_geometry = [affine_transform(g, m) for g in self.geo.solid_geometry]

    def offset(self, vect):
        return self._go(self._offset, vect)

    def _offset(self, vect):
        m = camlib.affine_translate_matrix(*vect)
        self.geo.solid_geometry = [affine_transform(g, m) for g in self.geo.solid_geometry]

    def buffer(self, value, join, factor=None):
        self.geo.solid_geometry = [g.buffer(value) for g in self.geo.solid_geometry]

    def bounds(self):
        self.bounds_calls += 1
        return self.geo.solid_geometry[0].bounds

    def set_offset_values(self, bounds=None):
        if bounds is None:
            self.bounds()
        self.offset_bounds.append(bounds)

    def plot_transformed(self, matrix, kind=None):
        self.matrices.append(tuple(matrix))
        return True

    def plot(self, kind=None):
        self.plot_calls += 1


def reference(poly, matrix):
    return affine_transform(poly, matrix)


class TransformTest(unittest.TestCase):

    def setUp(self):
        self.objs = []

    def tool(self, objs):
        app = make_app(objs)
        for o in objs:
            o.geo.app = app
        return SimpleNamespace(app=app), app

    def run_action(self, name, objs, *args):
        t, app = self.tool(objs)
        getattr(ToolTransform, name)(t, *args)
        return app

    def check_matrix(self, obj, original):
        self.assertEqual(len(obj.matrices), 1)
        got = obj.geo.solid_geometry[0]
        exp = reference(original, obj.matrices[0])
        self.assertTrue(got.equals_exact(exp, 1e-9), (got.wkt, exp.wkt))
        self.assertEqual(obj.plot_calls, 0)

    def test_matrix_matches_each_action(self):
        original = Polygon([(0, 0), (4, 0), (4, 2), (1, 3)])
        cases = [
            ('on_rotate_action', (30.0, (1.0, 2.0))),
            ('on_flip', ('X', (1.0, 2.0))),
            ('on_flip', ('Y', (1.0, 2.0))),
            ('on_skew', ('X', 10.0, 5.0, (1.0, 2.0))),
            ('on_scale', ('X', 2.0, 3.0, (1.0, 2.0))),
            ('on_scale', ('X', 2.0, 3.0, None)),
            ('on_offset', ('X', 5.0)),
            ('on_offset', ('Y', -3.0)),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                o = FakeObj(None)
                self.run_action(name, [o], *args)
                self.check_matrix(o, original)

    def test_local_bounds_and_notification_compute_fresh_bounds(self):
        objs = [FakeObj(None, 'a'), FakeObj(None, 'b')]
        tool, app = self.tool(objs)
        app.app_obj.object_changed.emit.side_effect = lambda obj: AppObject.on_object_changed(tool, obj)
        ToolTransform.on_rotate_action(tool, 30.0, (0.0, 0.0))
        for o in objs:
            self.assertEqual(o.bounds_calls, 2)
            self.assertEqual(o.offset_bounds, [o.geo.solid_geometry[0].bounds])
            self.assertFalse(hasattr(o, '_pending_bounds'))
        self.assertEqual(app.app_obj.object_changed.emit.call_count, 2)
        # one final message
        # the plugin emits one final message (the camlib methods emit their own per object)
        msgs = [c.args[0] for c in app.inform.emit.call_args_list]
        self.assertEqual(sum("Rotate done" in m for m in msgs), 1)
        self.assertIn("Rotate done", msgs[-1])

    def test_mutation_then_failure_rolls_back_and_continues(self):
        for failure in ('fail', 'exception', 'metadata', 'plot'):
            with self.subTest(failure=failure):
                bad, good = FakeObj(None, 'bad'), FakeObj(None, 'good')
                original = bad.solid_geometry[0]
                tool, app = self.tool([bad, good])

                def apply(obj):
                    obj.offset((2, 0))
                    if obj is bad:
                        if failure == 'fail':
                            return 'fail'
                        if failure == 'exception':
                            raise RuntimeError('after mutation')

                def meta(obj):
                    obj.obj_options['offset_x'] = 2
                    if obj is bad and failure == 'metadata':
                        raise RuntimeError('metadata')

                if failure == 'plot':
                    bad.plot_transformed = MagicMock(side_effect=RuntimeError('plot'))
                ToolTransform._transform_selected(tool, 'Move', '', apply, (1, 0, 0, 1, 2, 0), meta, 'done')
                self.assertTrue(bad.solid_geometry[0].equals_exact(original, 0))
                self.assertNotIn('offset_x', bad.obj_options)
                self.assertFalse(good.solid_geometry[0].equals_exact(original, 0))

    def test_no_selection(self):
        app = self.run_action('on_offset', [], 'X', 2.0)
        self.assertIn('WARNING_NOTCL', app.inform.emit.call_args.args[0])

if __name__ == '__main__':
    unittest.main()
