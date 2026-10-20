import json
import lzma
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import Point

from appCommon import ProjectFile
from appCommon.ProjectFile import ZSTD_MAGIC, load_project_file, save_project_file
from camlib import to_dict, dict2obj

try:
    import zstandard
except ImportError:
    zstandard = None


def project():
    return {"objs": [{"options": {"name": "a"}, "tools": {1: {"solid_geometry": [Point(1, 2).buffer(1)]}}}],
            "options": {"units": "MM"}, "version": 9.0}


class TestProjectFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.filename = os.path.join(self.tmp.name, 'p.FlatPrj')

    def check_round_trip(self, compression_level):
        save_project_file(self.filename, project(), default=to_dict, compression_level=compression_level)
        self.assertFalse(os.path.exists(self.filename + '.tmp'))
        loaded = load_project_file(self.filename, object_hook=dict2obj)
        geo = loaded['objs'][0]['tools']['1']['solid_geometry'][0]
        self.assertTrue(geo.equals_exact(Point(1, 2).buffer(1), 1e-9))
        self.assertEqual(loaded['options'], {"units": "MM"})
        return loaded

    def test_plain_round_trip(self):
        self.check_round_trip(None)
        with open(self.filename, 'rb') as f:
            self.assertEqual(f.read(1), b'{')

    def test_zstd_round_trip(self):
        self.check_round_trip(3)
        with open(self.filename, 'rb') as f:
            self.assertEqual(f.read(4), ZSTD_MAGIC)

    @unittest.skipIf(zstandard is None or ProjectFile.std_zstd is None, "needs both Zstandard backends")
    def test_zstandard_package_backend_reads_and_writes_the_same_format(self):
        with patch.object(ProjectFile, 'std_zstd', None), patch.object(ProjectFile, 'zstandard', zstandard):
            self.check_round_trip(3)
        # a file written by the zstandard package loads with the standard library backend
        self.check_round_trip_load_only()

    def check_round_trip_load_only(self):
        loaded = load_project_file(self.filename, object_hook=dict2obj)
        self.assertEqual(loaded['version'], 9.0)

    def test_compressed_json_is_compact_and_plain_json_is_indented(self):
        data = {"version": 9.0, "options": {"units": "MM"}, "objs": []}
        save_project_file(self.filename, data, default=to_dict, compression_level=3)
        with ProjectFile.open_project_stream(self.filename) as stream:
            # no indentation, and the keys stay in their order
            self.assertEqual(stream.read(), b'{"version":9.0,"options":{"units":"MM"},"objs":[]}')
        save_project_file(self.filename, data, default=to_dict, compression_level=None)
        with open(self.filename, 'rb') as f:
            self.assertEqual(f.read(), json.dumps(data, indent=2, sort_keys=True).encode('utf-8'))

    def test_out_of_range_level_is_clamped(self):
        self.check_round_trip(0)
        self.check_round_trip(99)

    def test_legacy_lzma_project_loads(self):
        data = json.dumps(project(), default=to_dict, indent=2, sort_keys=True).encode('utf-8')
        with open(self.filename, 'wb') as f:
            f.write(lzma.compress(data, preset=3))
        loaded = load_project_file(self.filename, object_hook=dict2obj)
        self.assertEqual(loaded['options'], {"units": "MM"})

    def test_compressed_save_replaces_inf_and_nan_with_null(self):
        d = project()
        d['options']['bad'] = [float('inf'), float('nan'), 1.5]
        save_project_file(self.filename, d, default=to_dict, compression_level=3)
        self.assertEqual(load_project_file(self.filename)['options']['bad'], [None, None, 1.5])

    def test_failed_save_keeps_the_old_file(self):
        save_project_file(self.filename, project(), default=to_dict, compression_level=3)
        with open(self.filename, 'rb') as f:
            old = f.read()
        for level in (None, 3):
            with self.subTest(level=level):
                # to_dict() returns the unknown object, so json reports a circular reference
                with self.assertRaises(ValueError):
                    save_project_file(self.filename, {"objs": [object()]}, default=to_dict, compression_level=level)
                with open(self.filename, 'rb') as f:
                    self.assertEqual(f.read(), old)
                self.assertFalse(os.path.exists(self.filename + '.tmp'))

    def test_bad_content_raises(self):
        with open(self.filename, 'wb') as f:
            f.write(b'not JSON')
        with self.assertRaises(ValueError):
            load_project_file(self.filename)
        with open(self.filename, 'wb') as f:
            f.write(ZSTD_MAGIC + b'broken')
        with self.assertRaises(Exception):
            load_project_file(self.filename)


if __name__ == '__main__':
    unittest.main()
