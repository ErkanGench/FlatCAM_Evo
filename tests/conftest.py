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
