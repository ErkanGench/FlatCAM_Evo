import os
import subprocess
import sys
import unittest
from io import StringIO
from unittest.mock import patch

from flatcam import _shutdown_message_handler


class TestShutdownMessageHandler(unittest.TestCase):
    def test_suppresses_qthreadstorage_shutdown_warning(self):
        output = StringIO()

        with patch('sys.stderr', output):
            _shutdown_message_handler(
                None,
                None,
                'QThreadStorage: entry 3 destroyed before end of thread 0x1234'
            )

        self.assertEqual(output.getvalue(), '')

    def test_preserves_unrelated_qt_warning(self):
        output = StringIO()

        with patch('sys.stderr', output):
            _shutdown_message_handler(None, None, 'QObject cleanup failed')

        self.assertEqual(output.getvalue(), 'WARNING: QObject cleanup failed\n')


class TestPoolChildBootstrap(unittest.TestCase):
    def test_pool_child_does_not_load_the_application_and_uses_one_blas_thread(self):
        # spawn runs flatcam.py again as __mp_main__ in every pool child
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import runpy, sys, os\n"
            "for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):\n"
            "    os.environ.pop(k, None)\n"
            "sys.path.insert(0, %r)\n"
            "runpy.run_path(os.path.join(%r, 'flatcam.py'), run_name='__mp_main__')\n"
            "from appPlugins.ToolIsolation.Isolation import ToolIsolation\n"
            "from appObjects.GerberObject import GerberObject\n"
            "print('appMain' in sys.modules, os.environ['OPENBLAS_NUM_THREADS'], os.environ['MKL_NUM_THREADS'])\n"
        ) % (root, root)
        result = subprocess.run([sys.executable, '-c', code], cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split()[-3:], ['False', '1', '1'])


if __name__ == '__main__':
    unittest.main()
