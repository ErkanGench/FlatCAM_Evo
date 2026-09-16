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


class TestInitializationOrder(unittest.TestCase):
    """
    Test that App attributes are initialized in correct order.
    
    This test suite verifies that critical attributes like preferencesUiManager
    are initialized BEFORE AppLifecycle caches them, preventing None references.
    """
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_app = Mock()
        self.mock_app.log = Mock()
        self.mock_app.inform = Mock()
        self.mock_app.defaults = Mock()
        self.mock_app.options = {}
        self.mock_app.ui = Mock()
        self.mock_app.qapp = Mock()
        self.mock_app.plotcanvas = Mock()
        self.mock_app.collection = Mock()
        self.mock_app.f_handlers = Mock()
        self.mock_app.trayIcon = Mock()
        self.mock_app.autosave_timer = Mock()
        self.mock_app.listen_th = Mock()
        self.mock_app.new_launch = Mock()
        self.mock_app.geo_editor = Mock()
        self.mock_app.exc_editor = Mock()
        self.mock_app.grb_editor = Mock()
        self.mock_app.gcode_editor = Mock()
        self.mock_app.use_3d_engine = True
        self.mock_app.mm = None
        self.mock_app.mp = None
        self.mock_app.mr = None
        self.mock_app.mdc = None
        self.mock_app.kp = None
        self.mock_app.workers = Mock()
        self.mock_app.pool = Mock()
        self.mock_app.cmd_line_headless = 0
        self.mock_app.save_in_progress = False
        self.mock_app.block_autosave = False
        self.mock_app.on_properties_tab_click = Mock()
        self.mock_app.app_quit = Mock()
        self.mock_app.message = Mock()
        self.mock_app.version = "test"
        self.mock_app.os = "windows"
        self.mock_app.version_url = "http://test.com"
        self.mock_app.connect_toolbar_signals = Mock()
        self.mock_app.connect_editors_toolbar_signals = Mock()
        self.mock_app.on_mouse_move_over_plot = Mock()
        self.mock_app.on_mouse_click_over_plot = Mock()
        self.mock_app.on_mouse_click_release_over_plot = Mock()
        self.mock_app.on_mouse_double_click_over_plot = Mock()
        self.mock_app.check_project_file_size = Mock()
        
        # Critical: Initially set to None to simulate the bug
        self.mock_app.preferencesUiManager = None
        
    def test_lifecycle_does_not_cache_none_preferencesUiManager(self):
        """
        GREEN: AppLifecycle should NOT cache None for preferencesUiManager.
        
        This test verifies the fix where AppLifecycle uses a property to access
        preferencesUiManager via self.app instead of caching it in __init__.
        
        Expected behavior: Access via self.app.preferencesUiManager works even if
        it was None when lifecycle was created.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        # Simulate the initialization order: lifecycle created before preferencesUiManager
        self.mock_app.preferencesUiManager = None
        
        # Create lifecycle - it should NOT cache None
        lifecycle = AppLifecycle(app=self.mock_app)
        
        # Now set the preferencesUiManager (simulating later initialization in _setup_gui)
        mock_prefs = Mock()
        self.mock_app.preferencesUiManager = mock_prefs
        
        self.assertNotIn('preferencesUiManager', lifecycle.__dict__)
        self.assertIs(lifecycle.app.preferencesUiManager, mock_prefs)
    
    def test_lifecycle_accesses_preferences_via_app_reference(self):
        """
        RED: AppLifecycle should access preferencesUiManager via self.app.
        
        This test verifies that lifecycle methods access preferencesUiManager
        through the app reference rather than cached value.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        # Set up with None initially (simulating early lifecycle creation)
        self.mock_app.preferencesUiManager = None
        lifecycle = AppLifecycle(app=self.mock_app)
        
        # Now set the preferencesUiManager (simulating later initialization)
        mock_prefs = Mock()
        self.mock_app.preferencesUiManager = mock_prefs
        
        # The lifecycle should be able to access it via self.app
        # Check that the app reference is maintained
        self.assertIs(lifecycle.app, self.mock_app)
        
        # Access via app should work
        self.assertIs(lifecycle.app.preferencesUiManager, mock_prefs)
    
    def test_initialization_order_preferences_before_lifecycle(self):
        """
        Verify the lifecycle retains the App reference for late-initialized state.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        lifecycle = AppLifecycle(app=self.mock_app)
        mock_prefs = Mock()
        self.mock_app.preferencesUiManager = mock_prefs

        self.assertIs(lifecycle.app, self.mock_app)
        self.assertIs(lifecycle.app.preferencesUiManager, mock_prefs)


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


class TestAppLifecycleCaching(unittest.TestCase):
    """
    Test that AppLifecycle correctly handles attribute caching.
    
    Verifies which attributes are safely cached vs which should be accessed
    via app reference.
    """
    
    def test_lifecycle_cached_attributes_list(self):
        """
        Verify the lifecycle only caches stable constructor dependencies.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        mock_app = Mock(log=Mock(), inform=Mock(), defaults=Mock(), options={})
        lifecycle = AppLifecycle(app=mock_app)

        self.assertEqual(
            set(lifecycle.__dict__) - {'app', 'log', 'inform', 'defaults', 'options'},
            set()
        )

    def test_lifecycle_constructs_with_early_app_state(self):
        from appHandlers.appLifecycle import AppLifecycle

        app = SimpleNamespace(log=Mock(), inform=Mock(), defaults=Mock(), options={})

        lifecycle = AppLifecycle(app=app)

        self.assertIs(lifecycle.app, app)
        self.assertFalse(hasattr(app, 'ui'))
        self.assertFalse(hasattr(app, 'collection'))
        self.assertFalse(hasattr(app, 'plotcanvas'))
    
    def test_lifecycle_should_not_cache_mutable_late_init_attributes(self):
        """
        Verify mutable late-initialized App attributes aren't copied by the handler.
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        late_attributes = {
            'autosave_timer', 'collection', 'exc_editor', 'f_handlers',
            'gcode_editor', 'geo_editor', 'grb_editor', 'plotcanvas',
            'preferencesUiManager', 'trayIcon', 'ui', 'workers'
        }
        mock_app = Mock(log=Mock(), inform=Mock(), defaults=Mock(), options={})
        lifecycle = AppLifecycle(app=mock_app)

        self.assertTrue(late_attributes.isdisjoint(lifecycle.__dict__))


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
        mock_app.preferencesUiManager = mock_prefs
        mock_app.defaults = Mock()
        mock_app.options = {}
        mock_app.ui = Mock()
        mock_app.autosave_timer = Mock()
        mock_app.new_launch = Mock()
        mock_app.listen_th = Mock()
        mock_app.geo_editor = None
        mock_app.exc_editor = None
        mock_app.grb_editor = None
        mock_app.gcode_editor = None
        mock_app.use_3d_engine = False
        mock_app.plotcanvas = Mock()
        mock_app.cmd_line_headless = 1
        mock_app.workers = Mock()
        mock_app.pool = Mock()
        mock_app.log = Mock()
        
        lifecycle = AppLifecycle(app=mock_app)
        
        # This should work
        try:
            with patch('appHandlers.appLifecycle.sys.platform', 'linux'):
                lifecycle.quit_application(silent=True)
            mock_prefs.save_defaults.assert_called_once_with(silent=True)
        except AttributeError as e:
            self.fail(f"quit_application failed even with proper preferencesUiManager: {e}")


class TestDynamicAppStartup(unittest.TestCase):
    """
    Dynamic tests that actually instantiate App components.
    
    These tests verify real initialization behavior, not just mocks.
    """
    
    @unittest.skip("Requires full PyQt6 application context")
    def test_full_app_instantiation_sequence(self):
        """
        Test the full App instantiation sequence.
        
        This test requires a running PyQt6 application and tests
        the complete initialization flow.
        """
        from PyQt6 import QtWidgets
        from appMain import App
        
        # Create QApplication
        qapp = QtWidgets.QApplication.instance()
        if qapp is None:
            qapp = QtWidgets.QApplication(sys.argv)
        
        # This would test the actual initialization order
        # Currently skipped because it requires full GUI context
        # app = App(qapp, user_defaults=False)
        
        self.assertTrue(True, "Test requires full GUI context")
    
    def test_appMain_setup_method_order(self):
        """
        Verify the order of setup method calls in App.__init__.
        
        This test parses the __init__ method to verify the call order.
        """
        import ast
        import inspect
        from appMain import App
        
        source = inspect.getsource(App.__init__)
        tree = ast.parse(textwrap.dedent(source))
        
        # Find all self.method() calls in __init__
        setup_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr.startswith('_setup_'):
                        setup_calls.append(node.func.attr)
        
        print("\n=== Setup Method Call Order ===")
        for i, call in enumerate(setup_calls):
            print(f"  {i+1}. {call}")
        
        # Verify expected order
        expected_order = [
            '_setup_logging',
            '_setup_state_variables',
            '_setup_paths_and_config',
            '_setup_defaults_and_preferences',
            '_setup_gui',
            '_setup_workers_crew',
            '_setup_canvas_and_plotting',
            '_setup_tools_and_editors',
            '_setup_system_integration',
            '_setup_signal_connections',
            '_setup_startup'
        ]
        
        # Check that setup methods are called
        self.assertEqual(setup_calls, expected_order,
                        f"Setup method order mismatch.\nExpected: {expected_order}\nActual: {setup_calls}")
    
    def test_preferencesUiManager_created_before_lifecycle_uses_it(self):
        """
        Verify lifecycle methods resolve preferences through the App reference.
        """
        import inspect
        from appHandlers.appLifecycle import AppLifecycle

        source = inspect.getsource(AppLifecycle.quit_application)
        self.assertIn('self.app.preferencesUiManager.save_defaults', source)


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
    
    def test_final_save_sequence_works_after_fix(self):
        """
        GREEN: final_save -> quit_application works after the fix.
        
        Original bug:
        File "appMain.py", line 2659, in final_save
          self.lifecycle.final_save()
        File "appHandlers/appLifecycle.py", line 334, in final_save
          self.quit_application()
        File "appHandlers/appLifecycle.py", line 353, in quit_application
          self.preferencesUiManager.save_defaults(silent=True)
        AttributeError: 'NoneType' object has no attribute 'save_defaults'
        
        Fix: preferencesUiManager is now a property that accesses via self.app
        """
        from appHandlers.appLifecycle import AppLifecycle
        
        # Set up with proper mock - simulating app after full initialization
        mock_prefs = Mock()
        mock_prefs.save_defaults = Mock()
        
        mock_app = Mock()
        mock_app.preferencesUiManager = mock_prefs
        mock_app.defaults = Mock()
        mock_app.options = {}
        mock_app.ui = Mock()
        mock_app.save_in_progress = False
        mock_app.should_we_save = False  # Skip save dialog
        mock_app.collection = Mock()
        mock_app.collection.get_list = Mock(return_value=[])  # No objects
        mock_app.trayIcon = Mock()
        mock_app.trayIcon.hide = Mock()
        mock_app.autosave_timer = Mock()
        mock_app.new_launch = Mock()
        mock_app.listen_th = Mock()
        mock_app.geo_editor = None
        mock_app.exc_editor = None
        mock_app.grb_editor = None
        mock_app.gcode_editor = None
        mock_app.use_3d_engine = False
        mock_app.plotcanvas = Mock()
        mock_app.plotcanvas.close = Mock()
        mock_app.cmd_line_headless = 1
        mock_app.workers = Mock()
        mock_app.workers.quit = Mock()
        mock_app.pool = Mock()
        mock_app.pool.terminate = Mock()
        mock_app.pool.join = Mock()
        mock_app.log = Mock()
        
        lifecycle = AppLifecycle(app=mock_app)
        
        # Call final_save which should call quit_application
        try:
            with patch('appHandlers.appLifecycle.sys.platform', 'linux'):
                lifecycle.final_save()
            # After fix: this should work without AttributeError
            mock_prefs.save_defaults.assert_called()
        except AttributeError as e:
            if 'preferencesUiManager' in str(e):
                self.fail(f"BUG NOT FIXED: final_save -> quit_application -> {e}")
            else:
                raise


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
