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


if __name__ == '__main__':
    unittest.main()
