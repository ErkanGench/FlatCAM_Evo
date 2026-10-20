"""pytest configuration for the FlatCAM tests.

appMain.App parses sys.argv with getopt when the class is defined, and it calls sys.exit(2) on an unknown
option. pytest options such as -q or -x would stop every test that imports appMain (for example Gerber() imports
it). Import appMain 1 time here with a clean sys.argv; the later imports get the module from sys.modules.
"""

import os
import sys

# Select native OpenGL support before collection can default Qt to offscreen.
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_PLATFORM', 'windows')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_saved_argv = sys.argv
sys.argv = sys.argv[:1]
try:
    import appMain  # noqa: F401
except ImportError:
    # without the GUI packages the tests that need appMain fail on their own
    pass
finally:
    sys.argv = _saved_argv


# The GUI tests show real windows. A window with WA_DontShowOnScreen is shown for Qt (visible, laid out, grab()
# works, the window states change) but it does not appear on the desktop, so the tests do not flash windows.
# Set FLATCAM_TEST_SHOW_WINDOWS=1 to see the windows.
_window_filter = None


def _install_window_filter():
    global _window_filter
    if _window_filter is not None or os.environ.get('FLATCAM_TEST_SHOW_WINDOWS'):
        return
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return

    class HideWindows(QtCore.QObject):
        def eventFilter(self, obj, event):
            # Polish comes before the first show of a widget, so the attribute is set in time
            if event.type() == QtCore.QEvent.Type.Polish and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
                obj.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            return False

    _window_filter = HideWindows()
    app.installEventFilter(_window_filter)


def pytest_runtest_setup(item):
    _install_window_filter()


def pytest_runtest_call(item):
    # unittest runs setUp in the call phase: a QApplication made in setUpClass is here
    _install_window_filter()


# Hardware tests (a connected E-Cut USB board or a GRBL serial board) do not run by default.
# Mark such a test with @pytest.mark.hardware and set FLATCAM_TEST_HARDWARE=1 to run it.
# All other tests cannot open a real HID device or serial port: a board that is connected stays untouched.
import pytest  # noqa: E402

HARDWARE_TESTS = os.environ.get('FLATCAM_TEST_HARDWARE') == '1'
_HARDWARE_BLOCKED = 'real hardware access is blocked in tests; mark the test hardware and set FLATCAM_TEST_HARDWARE=1'


def pytest_configure(config):
    config.addinivalue_line('markers', 'hardware: needs a connected E-Cut or GRBL board (FLATCAM_TEST_HARDWARE=1)')


def pytest_collection_modifyitems(config, items):
    if HARDWARE_TESTS:
        return
    skip = pytest.mark.skip(reason='hardware test: set FLATCAM_TEST_HARDWARE=1 to run it')
    for item in items:
        if item.get_closest_marker('hardware'):
            item.add_marker(skip)


class _BlockedHid:
    """Stands in for the hidapi module: any use fails, so no test reaches a real USB board."""

    def __getattr__(self, name):
        raise RuntimeError(_HARDWARE_BLOCKED)


@pytest.fixture(autouse=True)
def _no_real_hardware(request, monkeypatch):
    if HARDWARE_TESTS and request.node.get_closest_marker('hardware'):
        return
    monkeypatch.setitem(sys.modules, 'hid', _BlockedHid())
    try:
        import serial
    except ImportError:
        return

    def blocked_open(self, *args, **kwargs):
        raise serial.SerialException(_HARDWARE_BLOCKED)

    # the platform class of serial.Serial; loop:// and the test fakes use other classes
    monkeypatch.setattr(serial.Serial, 'open', blocked_open)
