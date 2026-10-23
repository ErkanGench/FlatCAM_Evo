"""Gerber aperture marking benchmark, including the real Mark All handler.

Run with --workers 4 to include actual process-pool buffer preparation.
--baseline-ref benchmarks historical marking methods with the current shared renderer.
GPU execution, input construction and process-pool startup aren't timed.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
import logging
import multiprocessing
from pathlib import Path
import statistics
import sys
from time import perf_counter
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shapely import Point
from vispy.gloo.context import FakeCanvas

import appObjects.GerberObject as gerber_module
from appObjects.AppObjectTemplate import FlatCAMObj
from appGUI.VisPyVisuals import ShapeCollectionVisual
from benchmark_object_plot import historical


def benchmark(args, pool):
    plot_aperture = gerber_module.GerberObject.plot_aperture
    mark_all = gerber_module.GerberObject.on_mark_all_click
    if args.baseline_ref:
        namespace = historical('appObjects/GerberObject.py', {'plot_aperture', 'on_mark_all_click'},
                               dict(vars(gerber_module)), args.baseline_ref)
        plot_aperture, mark_all = namespace['plot_aperture'], namespace['on_mark_all_click']
    geometries = [{'solid': Point(i % 100, i // 100).buffer(0.4, quad_segs=16),
                   'follow': Point(i % 100, i // 100)} for i in range(args.count)]
    rows = []
    for name, aperture_count in (('single-aperture', 1), ('mark-all', args.apertures)):
        timings = []
        for repeat in range(args.repeat + 1):
            canvas = FakeCanvas()
            collection = ShapeCollectionVisual(layers=1, pool=pool, fcoptions={
                'global_graphic_engine_3d_no_mp': pool is None})
            table = SimpleNamespace(rowCount=lambda: aperture_count, cellWidget=lambda *args: Mock())
            ui = SimpleNamespace(apertures_table=table, mark_all_cb=Mock(isChecked=lambda: True))
            app = SimpleNamespace(log=logging.getLogger('benchmark'),
                                  proc_container=SimpleNamespace(new=lambda *args: nullcontext()),
                                  ui=SimpleNamespace(grid_snap_btn=Mock()))
            obj = SimpleNamespace(
                app=app, ui=ui, tools={ap: {'geometry': geometries[ap::aperture_count]}
                                     for ap in range(aperture_count)},
                mark_shapes=collection, mark_shapes_storage={}, marked_rows=[],
                drawing_tolerance=0.001, deleted=False, ui_connect=lambda: None, ui_disconnect=lambda: None)
            obj._app_option = lambda key: '#4080FFAF'
            obj.add_mark_shape = MethodType(FlatCAMObj.add_mark_shape, obj)
            obj.plot_aperture = MethodType(plot_aperture, obj)
            obj.clear_plot_apertures = MethodType(gerber_module.GerberObject.clear_plot_apertures, obj)
            start = perf_counter()
            if name == 'single-aperture':
                obj.plot_aperture(marked_aperture=0, color='#4080FFAF', visible=True)
            else:
                mark_all(obj)
            plotted = perf_counter()
            assert len(collection.data) == args.count
            digest = hashlib.sha256()
            for ap, keys in sorted(obj.mark_shapes_storage.items()):
                assert len(keys) == len(obj.tools[ap]['geometry'])
                for key in keys:
                    data = collection.data[key]
                    for field in ('line_pts', 'line_rgba', 'mesh_vertices', 'mesh_tris', 'mesh_rgba'):
                        digest.update(data[field].tobytes())
                    digest.update(repr((data['visible'], data['layer'], data['tolerance'])).encode())
            obj.clear_plot_apertures()
            assert not collection.data
            if repeat:
                timings.append(plotted - start)
        row = dict(case=name, shapes=args.count, apertures=aperture_count, workers=args.workers,
                   fingerprint=digest.hexdigest(), plot_s=statistics.median(timings))
        rows.append(row)
        print(json.dumps(row), flush=True)
    if args.output:
        Path(args.output).write_text(json.dumps(rows, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=2000)
    parser.add_argument('--apertures', type=int, default=40)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--workers', type=int, default=0)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.workers:
        with multiprocessing.Pool(args.workers) as pool:
            benchmark(args, pool)
    else:
        benchmark(args, None)
