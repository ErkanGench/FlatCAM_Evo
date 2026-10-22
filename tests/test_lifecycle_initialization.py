# ###########################################################
# FlatCAM EVO - App Lifecycle Integration Tests
# Tests for app initialization order and shutdown sequence
# ###########################################################

import sys
import os
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch
from PyQt6 import QtWidgets
from PyQt6.QtCore import QTimer

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNewProjectTabClosure(unittest.TestCase):
    @staticmethod
    def make_handler(close_result):
        from appHandlers.appIO import appIO

        close_tab = Mock(return_value=close_result)
        tab_area = SimpleNamespace(
            tabBar=SimpleNamespace(count=Mock(return_value=1)),
            closeTab=close_tab,
            tabText=Mock(return_value='Tools Database'),
            insertTab=Mock(),
            protectTab=Mock()
        )
        project_tab = object()
        app = SimpleNamespace(
            call_source='app',
            collection=SimpleNamespace(get_list=lambda: []),
            exc_areas=SimpleNamespace(clear_shapes=Mock()),
            delete_selection_shape=Mock(),
            setup_default_properties_tab=Mock(),
            defaults_path=Mock(return_value='defaults'),
            on_defaults2options=Mock(),
            new_project_signal=SimpleNamespace(emit=Mock()),
            ui=SimpleNamespace(
                plot_tab_area=tab_area,
                notebook=SimpleNamespace(setCurrentWidget=Mock()),
                project_tab=project_tab,
                plot_tab=object(),
                set_ui_title=Mock()
            ),
            log=Mock()
        )
        handler = appIO.__new__(appIO)
        handler.app = app
        handler.log = app.log
        handler.inform = Mock()
        handler.options = SimpleNamespace(load=Mock())
        return handler, close_tab

    def test_new_project_reports_explicit_tab_close_veto_and_continues(self):
        handler, close_tab = self.make_handler(False)

        handler.on_file_new_project(use_thread=True)

        close_tab.assert_called_once_with(0)
        warning_messages = [call.args[0] for call in handler.inform.emit.call_args_list
                            if call.args and '[WARNING_NOTCL]' in call.args[0]]
        self.assertEqual(1, len(warning_messages))
        self.assertIn('Tools Database', warning_messages[0])
        self.assertIn('remains open', warning_messages[0])
        handler.app.new_project_signal.emit.assert_called_once_with()
        handler.app.ui.notebook.setCurrentWidget.assert_called_once_with(handler.app.ui.project_tab)

    def test_new_project_does_not_warn_for_accepted_or_legacy_none_close(self):
        for close_result in (True, None):
            with self.subTest(close_result=close_result):
                handler, close_tab = self.make_handler(close_result)

                handler.on_file_new_project(use_thread=True)

                close_tab.assert_called_once_with(0)
                warning_messages = [call.args[0] for call in handler.inform.emit.call_args_list
                                    if call.args and '[WARNING_NOTCL]' in call.args[0]]
                self.assertEqual([], warning_messages)
                handler.app.new_project_signal.emit.assert_called_once_with()


class TestAppShutdownSequence(unittest.TestCase):
    """
    Test that app shutdown sequence works correctly.
    
    Verifies that quit_application() can successfully call
    preferencesUiManager.save_defaults() without AttributeError.
    """
    
    @unittest.skip("Skipped - requires full Qt application context")
    def test_quit_application_can_save_preferences(self):
        """
        GREEN: quit_application() should successfully call save_defaults().
        
        This test is skipped because it requires a running Qt application.
        The fix is verified by other tests that check property access.
        """
        pass
    
    def test_quit_application_with_proper_preferencesUiManager(self):
        """
        GREEN: quit_application() works when preferencesUiManager is properly set.
        
        This test verifies the expected behavior when preferencesUiManager
        is properly initialized.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        # Set up with proper mock
        mock_prefs = Mock()
        mock_prefs.save_defaults = Mock()
        
        mock_app = Mock()
        # a Mock attribute is truthy: this is the GUI mode, not the headless mode
        mock_app.headless = False
        mock_app.preferencesUiManager = mock_prefs
        mock_app.defaults = Mock()
        mock_app.options = {}
        mock_app.ui = Mock()
        mock_app.new_launch = Mock()
        mock_app.listen_th = Mock()
        mock_app.geo_editor = None
        mock_app.exc_editor = None
        mock_app.grb_editor = None
        mock_app.gcode_editor = None
        mock_app.plotcanvas = Mock()
        mock_app.workers = Mock()
        mock_app.pool = Mock()
        mock_app.log = Mock()
        
        lifecycle = AppLifecycle(app=mock_app)
        
        # This should work
        try:
            with patch('appHandlers.appLifecycle.sys.platform', 'linux'), \
                    patch('PyQt6.QtCore.QSettings'):
                lifecycle.quit_application(silent=True)
            mock_prefs.save_defaults.assert_called_once_with(silent=True)
        except AttributeError as e:
            self.fail(f"quit_application failed even with proper preferencesUiManager: {e}")

    def test_quit_application_before_the_event_loop_still_ends_the_app(self):
        """
        A --shellfile runs in App.__init__(), before app.exec(). QApplication.quit() does nothing while the event
        loop does not run, so `quit_app` hid the window and the process kept running: the quit must also be queued
        for the event loop.
        """
        from appHandlers.appLifecycle import AppLifecycle

        mock_app = Mock()
        # a Mock attribute is truthy: this is the GUI mode, not the headless mode
        mock_app.headless = False
        mock_app.options = {}
        lifecycle = AppLifecycle(app=mock_app)
        lifecycle._confirm_tools_database = Mock(return_value=True)

        with patch('appHandlers.appLifecycle.sys.platform', 'linux'), \
                patch('PyQt6.QtCore.QSettings'), \
                patch('PyQt6.QtWidgets.QApplication.quit') as quit_now, \
                patch('PyQt6.QtCore.QTimer.singleShot') as single_shot:
            self.assertTrue(lifecycle.quit_application(silent=True))

        quit_now.assert_called_once_with()
        single_shot.assert_called_once_with(0, quit_now)


class TestFinalSaveSequence(unittest.TestCase):
    """
    Test the final_save() -> quit_application() sequence that triggers the bug.
    """
    
    def test_final_save_calls_quit_application(self):
        """
        Verify that final_save() calls quit_application().
        """
        from appHandlers.appLifecycle import AppLifecycle
        import inspect
        
        source = inspect.getsource(AppLifecycle.final_save)
        
        # Check that quit_application is called
        self.assertIn('quit_application', source,
                     "final_save should call quit_application")
    
def run_all_tests():
    """Run all tests and report results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestInitializationOrder))
    suite.addTests(loader.loadTestsFromTestCase(TestAppLifecycleCaching))
    suite.addTests(loader.loadTestsFromTestCase(TestAppShutdownSequence))
    suite.addTests(loader.loadTestsFromTestCase(TestDynamicAppStartup))
    suite.addTests(loader.loadTestsFromTestCase(TestFinalSaveSequence))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Report
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split(chr(10))[-2] if chr(10) in traceback else traceback[:100]}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split(chr(10))[-2] if chr(10) in traceback else traceback[:100]}")
    
    return result


if __name__ == '__main__':
    sys.exit(0 if run_all_tests().wasSuccessful() else 1)
