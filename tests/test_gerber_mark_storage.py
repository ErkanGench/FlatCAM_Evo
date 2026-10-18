"""Marking an aperture that has no key in mark_shapes_storage must not fail (aperture added after build_ui)."""
import sys
from pathlib import Path
from unittest.mock import Mock
import pytest
from shapely import LineString, MultiLineString, MultiPolygon, Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_unify_characterization import make_app, make_gerber, _headless_qt  # noqa: E402,F401


def _gerber():
    app = make_app()
    obj = make_gerber(app)
    obj.mark_shapes = Mock()
    counter = iter(range(1000))
    obj.add_mark_shape = Mock(side_effect=lambda **kw: next(counter))
    obj.mark_shapes.add_batch.side_effect = lambda batch, **kw: [next(counter) for _ in batch]
    return app, obj


def _aperture_with_solid(obj):
    for ap, tool in obj.tools.items():
        if any('solid' in el for el in tool['geometry']):
            return ap
    raise AssertionError('no aperture with solid geometry')


def test_plot_aperture_without_storage_key_stores_shape_keys():
    app, obj = _gerber()
    ap = _aperture_with_solid(obj)
    obj.mark_shapes_storage.clear()

    obj.plot_aperture(run_thread=False, marked_aperture=ap, color='#ff0000')

    assert obj.mark_shapes_storage[ap]
    assert len(obj.mark_shapes_storage[ap]) == len(obj.mark_shapes.add_batch.call_args.args[0])
    app.log.error.assert_not_called()
    obj.mark_shapes.redraw.assert_called_once()


def test_plot_aperture_keeps_existing_storage_key():
    app, obj = _gerber()
    ap = _aperture_with_solid(obj)
    obj.mark_shapes_storage[ap] = ['old']

    obj.plot_aperture(run_thread=False, marked_aperture=ap, color='#ff0000')

    assert obj.mark_shapes_storage[ap][0] == 'old'
    assert len(obj.mark_shapes_storage[ap]) > 1
    app.log.error.assert_not_called()


def test_clear_plot_apertures_with_unknown_aperture_does_not_raise():
    app, obj = _gerber()
    obj.mark_shapes_storage['other'] = [1]

    obj.clear_plot_apertures('missing')

    assert obj.mark_shapes_storage['missing'] == []
    assert obj.mark_shapes_storage['other'] == [1]
    obj.mark_shapes.redraw.assert_called_once()


@pytest.mark.parametrize('only_flashes', [False, True])
@pytest.mark.parametrize('run_thread', [False, True])
def test_marking_batches_shapes_and_keeps_aperture_keys(only_flashes, run_thread):
    app, obj = _gerber()
    first = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    second = Polygon([(3, 0), (4, 0), (4, 1), (3, 1)])
    line = LineString([(0, 0), (2, 2)])
    obj.tools = {10: {'geometry': [
        {'solid': MultiPolygon([first, second]), 'follow': Point(0, 0)},
        {'solid': MultiLineString([line]), 'follow': line},
        {'solid': first, 'follow': Point(0, 0)}, {'follow': Point(0, 0)}]}}
    expected = [first, second, first] if only_flashes else [first, second, line, first]
    keys = list(range(100, 100 + len(expected)))
    obj.mark_shapes_storage = {10: ['existing'], 20: ['other']}
    obj.mark_shapes.add_batch.side_effect = None
    obj.mark_shapes.add_batch.return_value = keys

    obj.plot_aperture(only_flashes=only_flashes, run_thread=run_thread,
                      marked_aperture=10, color='#12345678', visible=False)
    if run_thread:
        obj.mark_shapes.add_batch.assert_not_called()
        task = app.worker_task.emit.call_args.args[0]
        task['fcn'](*task['params'])

    obj.mark_shapes.add_batch.assert_called_once()
    batch = obj.mark_shapes.add_batch.call_args.args[0]
    assert [item['shape'].wkb for item in batch] == [shape.wkb for shape in expected]
    assert all(item['color'] == item['face_color'] == '#12345678' for item in batch)
    assert obj.mark_shapes.add_batch.call_args.kwargs == {
        'tolerance': obj.drawing_tolerance, 'layer': 0, 'visible': False}
    assert obj.mark_shapes_storage == {10: ['existing'] + keys, 20: ['other']}
    obj.add_mark_shape.assert_not_called()
    obj.mark_shapes.redraw.assert_called_once()
    app.log.error.assert_not_called()

    obj.clear_plot_apertures(10)
    assert [call.args[0] for call in obj.mark_shapes.remove.call_args_list] == ['existing'] + keys
    assert obj.mark_shapes_storage == {10: [], 20: ['other']}


def test_mark_all_redraws_only_once():
    app, obj = _gerber()
    obj.ui = Mock()
    obj.ui.mark_all_cb.isChecked.return_value = True
    obj.ui.apertures_table.rowCount.return_value = len(obj.tools)
    obj.ui_connect = Mock()
    obj.ui_disconnect = Mock()
    obj.mark_shapes.add_batch.side_effect = lambda batch, **kw: list(range(len(batch)))

    obj.on_mark_all_click()

    obj.mark_shapes.redraw.assert_called_once()
    assert obj.marked_rows == [True] * len(obj.tools)
    app.log.error.assert_not_called()


def test_deleted_object_does_not_submit_mark_batches():
    app, obj = _gerber()
    obj.deleted = True
    obj.clear_plot_apertures = Mock()
    obj.plot_aperture(marked_aperture=_aperture_with_solid(obj))
    obj.mark_shapes.add_batch.assert_not_called()
    obj.clear_plot_apertures.assert_called_once()
    app.log.error.assert_not_called()
