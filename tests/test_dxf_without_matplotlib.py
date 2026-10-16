"""Run directly to avoid conftest importing appMain before the import blocker."""

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def probe(blocked):
    import importlib.abc
    import math

    class BlockMatplotlib(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in ('matplotlib', 'descartes'):
                raise ModuleNotFoundError(f'Blocked optional dependency: {fullname}')

    if blocked:
        sys.meta_path.insert(0, BlockMatplotlib())
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(ROOT / 'flatcam.py')]
    import appMain
    import ezdxf
    import fontTools
    from ezdxf.fonts import fonts
    from appParsers import ParseDXF

    assert appMain.App
    assert ParseDXF.HAS_TEXT2PATH
    assert ParseDXF.HAS_TEXT2PATH_VERSION_OK, ezdxf.__version__
    doc = ezdxf.new()
    doc.styles.get('Standard').dxf.font = 'Arial.ttf'
    model = doc.modelspace()
    entities = [model.add_text('ABC', dxfattribs={'height': 2.5}),
                model.new_entity('ATTRIB', dxfattribs={
                    'tag': 'LABEL', 'text': 'ABC', 'insert': (0, 0), 'height': 2.5})]
    results = {}
    for entity in entities:
        for mode in ('stroke', 'outline'):
            geometry = ParseDXF.dxftext2shapely(entity, text_mode=mode)
            assert geometry, (entity.dxftype(), mode)
            assert all(g.is_valid and not g.is_empty and g.length > 0 for g in geometry)
            assert all(math.isfinite(v) for g in geometry for v in g.bounds)
            expected_type = 'LineString' if mode == 'stroke' else 'Polygon'
            assert all(g.geom_type == expected_type for g in geometry)
            results[f'{entity.dxftype()}:{mode}'] = {
                'count': len(geometry), 'bounds': [g.bounds for g in geometry],
                'wkb': [g.wkb_hex for g in geometry]}

    unsupported = {}
    for entity in (model.add_mtext('ABC'), model.add_attdef('LABEL', text='ABC')):
        for mode in ('stroke', 'outline'):
            unsupported[f'{entity.dxftype()}:{mode}'] = len(
                ParseDXF.dxftext2shapely(entity, text_mode=mode))

    # Exercise the defensive branches without changing installed packages.
    import builtins
    import importlib
    from unittest.mock import patch

    with patch.object(ezdxf, '__version__', '1.4.4'):
        importlib.reload(ParseDXF)
        assert not ParseDXF.HAS_TEXT2PATH_VERSION_OK
        assert ParseDXF.dxftext2shapely(entities[0]) == []
    with patch.object(ezdxf, '__version__', 'invalid'):
        importlib.reload(ParseDXF)
        assert not ParseDXF.HAS_TEXT2PATH_VERSION_OK
        assert ParseDXF.dxftext2shapely(entities[0]) == []
    original_import = builtins.__import__

    def without_addon(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'ezdxf.addons' and 'text2path' in fromlist:
            raise ImportError('text2path unavailable')
        return original_import(name, globals, locals, fromlist, level)

    with patch('builtins.__import__', side_effect=without_addon):
        importlib.reload(ParseDXF)
        assert not ParseDXF.HAS_TEXT2PATH
        assert ParseDXF.dxftext2shapely(entities[0]) == []
    importlib.reload(ParseDXF)
    if blocked:
        assert not any(name.split('.')[0] in ('matplotlib', 'descartes') for name in sys.modules)
    return {'ezdxf': ezdxf.__version__, 'fontTools': fontTools.__version__,
            'font': str(fonts.font_manager.get_font_face('Arial.ttf')),
            'geometry': results, 'unsupported_entity_counts': unsupported}


def test_dxf_without_matplotlib():
    results = []
    for mode in ('baseline', 'blocked'):
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--probe', mode],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(completed.stdout.split('DXF_RESULT=', 1)[1])
        results.append(result)
    assert results[0] == results[1]
    evidence = dict(results[1])
    evidence['geometry'] = {key: {'count': value['count'], 'bounds': value['bounds']}
                            for key, value in evidence['geometry'].items()}
    print(json.dumps(evidence))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--probe':
        print('DXF_RESULT=' + json.dumps(probe(sys.argv[2] == 'blocked')))
    else:
        test_dxf_without_matplotlib()
