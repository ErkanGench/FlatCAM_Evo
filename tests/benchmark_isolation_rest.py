"""Run: .venv/Scripts/python tests/benchmark_isolation_rest.py

Compare the original, PR #31 and current rest isolation on synthetic sparse and dense layouts.
Timings exclude input creation, output comparison and query-memory instrumentation; each is the median of 3 rounds.
The historical implementations are read from local Git objects, without changing the checkout.
"""
import ast
import importlib
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import shapely
from shapely import box

isolation = importlib.import_module('appPlugins.ToolIsolation')


def historical_rest(ref):
    source = subprocess.check_output(
        ['git', 'show', f'{ref}:appPlugins/ToolIsolation.py'], cwd=ROOT, text=True, encoding='utf-8')
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ToolIsolation')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'generate_rest_geometry')
    namespace = vars(isolation).copy()
    exec(compile(ast.Module(body=[method], type_ignores=[]), ref, 'exec'), namespace)
    return namespace['generate_rest_geometry']


def layout(count, pitch):
    return [box((i % 100) * pitch, (i // 100) * pitch,
                (i % 100) * pitch + 0.2, (i // 100) * pitch + 0.2) for i in range(count)]


def signature(result):
    return tuple(tuple(geo.wkb for geo in part) for part in result)


def main():
    versions = {
        'original': historical_rest('9dbe4772877acdb2d60b18fd832550d449dbc10f'),
        'pr31': historical_rest('7ac91341d1fdc925ea063d88a8d35250993eafb9'),
        'adaptive': isolation.ToolIsolation.generate_rest_geometry,
    }
    cases = [
        ('sparse', 1000, 3.0, 0.2, 1),
        ('sparse', 1000, 3.0, 0.2, 3),
        ('dense', 3000, 0.3, 1.0, 1),
        ('dense', 3000, 0.3, 3.0, 1),
        ('dense', 3000, 0.3, 10.0, 1),
        ('dense', 3000, 0.3, 1.0, 3),
    ]
    tool = SimpleNamespace(app=SimpleNamespace(log=Mock()))
    original_tree = shapely.STRtree
    peak_bytes = []

    class RecordedTree:
        def __init__(self, geos):
            self.tree = original_tree(geos)

        def query(self, *args, **kwargs):
            result = self.tree.query(*args, **kwargs)
            peak_bytes.append(result.nbytes)
            return result

    print(f'Python {sys.version.split()[0]}, Shapely {shapely.__version__}, GEOS {shapely.geos_version_string}')
    print('layout,count,pitch_mm,tool_mm,passes,original_s,pr31_s,adaptive_s,pr31_peak_query_KiB,adaptive_peak_query_KiB')
    for name, count, pitch, diameter, passes in cases:
        times = {version: [] for version in versions}
        expected = None
        # Warm up all three implementations on a small input; rotate their order in the timed rounds.
        for function in versions.values():
            function(tool, layout(16, pitch), diameter, passes, 0.1, invert=False)
        names = list(versions)
        for round_nr in range(3):
            for version in names[round_nr:] + names[:round_nr]:
                geometry = layout(count, pitch)
                start = perf_counter()
                result = versions[version](tool, geometry, diameter, passes, 0.1, invert=False)
                times[version].append(perf_counter() - start)
                actual = signature(result)
                if expected is None:
                    expected = actual
                assert actual == expected, (name, diameter, passes, version)
        peaks = []
        for version in ('pr31', 'adaptive'):
            peak_bytes.clear()
            with patch.object(shapely, 'STRtree', RecordedTree):
                result = versions[version](tool, layout(count, pitch), diameter, passes, 0.1, invert=False)
            assert signature(result) == expected
            peaks.append(max(peak_bytes, default=0) / 1024)
        timings = ','.join(f'{median(times[version]):.4f}' for version in versions)
        print(f'{name},{count},{pitch},{diameter},{passes},{timings},{peaks[0]:.1f},{peaks[1]:.1f}', flush=True)
    print('All timed and instrumented results match, including path order and remaining polygons (WKB).')


if __name__ == '__main__':
    main()
