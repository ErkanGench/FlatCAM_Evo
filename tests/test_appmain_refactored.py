#!/usr/bin/env python
"""
Automated tests for appMain.py refactored structure.
Tests the Phase 1 refactoring of the App class setup methods.

Run: python tests/test_appmain_refactored.py
"""

import sys
import os
import re
import ast
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APPMMAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
    'appMain.py'
)


def read_appmain():
    """Read appMain.py source."""
    with open(APPMMAIN_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def parse_appmain():
    """Parse appMain.py into AST."""
    source = read_appmain()
    return ast.parse(source), source


def get_app_class(tree):
    """Extract the App class node from AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'App':
            return node
    return None


def get_method_names(app_class):
    """Get all method names in the App class."""
    methods = []
    for item in app_class.body:
        if isinstance(item, ast.FunctionDef):
            methods.append(item.name)
    return methods


def get_setup_methods(app_class):
    """Get all _setup_* methods."""
    methods = []
    for item in app_class.body:
        if isinstance(item, ast.FunctionDef) and item.name.startswith('_setup_'):
            methods.append({
                'name': item.name,
                'line': item.lineno,
                'end_line': item.end_lineno,
                'docstring': ast.get_docstring(item) or '',
                'args': [arg.arg for arg in item.args.args]
            })
    return methods


def get_init_calls(tree):
    """Get all method calls in __init__."""
    init_method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '__init__':
            init_method = node
            break
    
    if not init_method:
        return []
    
    calls = []
    for node in ast.walk(init_method):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith('_setup_'):
                    calls.append(node.func.attr)
    return calls


def extract_method(source, method_name):
    """Extract a method's source code from the App class."""
    # Find the method definition with proper indentation
    pattern = rf'^    def {method_name}\('
    match = re.search(pattern, source, re.MULTILINE)
    if not match:
        return None

    start = match.start()
    # Find the end of the method (next method at same indentation or class end)
    lines = source[start:].split('\n')
    method_lines = [lines[0]]

    for i in range(1, len(lines)):
        line = lines[i]
        # Stop at next method at same indentation level (4 spaces for App methods)
        if line.strip().startswith('def ') and line.startswith('    def '):
            break
        method_lines.append(line)

    return '\n'.join(method_lines)


def get_instance_attributes(app_class):
    """Get all self.xxx attributes initialized in __init__."""
    init_method = None
    for item in app_class.body:
        if isinstance(item, ast.FunctionDef) and item.name == '__init__':
            init_method = item
            break
    
    if not init_method:
        return set()
    
    attrs = set()
    for node in ast.walk(init_method):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    if isinstance(target.value, ast.Name) and target.value.id == 'self':
                        attrs.add(target.attr)
    return attrs


# =============================================================================
# TEST GROUP 1: App Class Structure
# =============================================================================

class TestAppClassStructure(unittest.TestCase):
    """Test that the App class has proper structure after refactoring."""

    def setUp(self):
        """Parse appMain.py before each test."""
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)
        self.assertIsNotNone(self.app_class, "App class not found")

    def test_app_class_exists(self):
        """RED: App class should exist in appMain.py."""
        # This is verified in setUp, but explicit test for clarity
        self.assertIsNotNone(self.app_class)

    def test_app_inherits_from_qt_object(self):
        """RED: App class should inherit from QtCore.QObject."""
        # AST represents attribute access differently - check for QtCore and QObject
        has_qtcore = False
        has_qobject = False
        for base in self.app_class.bases:
            if isinstance(base, ast.Attribute):
                if isinstance(base.value, ast.Name) and base.value.id == 'QtCore':
                    has_qtcore = True
                if base.attr == 'QObject':
                    has_qobject = True
        
        self.assertTrue(has_qtcore and has_qobject,
            "App class should inherit from QtCore.QObject")

    def test_has_init_method(self):
        """RED: App class should have __init__ method."""
        methods = get_method_names(self.app_class)
        self.assertIn('__init__', methods,
            "App class should have __init__ method")

    def test_has_all_setup_methods(self):
        """
        RED: After Phase 1 refactoring, App should have 11 setup methods.
        Missing any setup method indicates incomplete refactoring.
        """
        expected_setup = [
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
        
        methods = get_method_names(self.app_class)
        missing = [m for m in expected_setup if m not in methods]
        
        self.assertEqual(len(missing), 0,
            f"Missing setup methods: {missing}. "
            f"All 11 setup methods must exist after Phase 1 refactoring.")


# =============================================================================
# TEST GROUP 2: Setup Method Invocation Order
# =============================================================================

class TestSetupMethodOrder(unittest.TestCase):
    """Test that setup methods are called in correct order in __init__."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)
        self.assertIsNotNone(self.app_class, "App class not found")

    def test_all_setup_methods_called(self):
        """
        RED: All 11 setup methods must be called in __init__.
        If a setup method is defined but not called, initialization is incomplete.
        """
        expected_setup = [
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
        
        calls = get_init_calls(self.tree)
        missing = [m for m in expected_setup if m not in calls]
        
        self.assertEqual(len(missing), 0,
            f"Setup methods defined but not called in __init__: {missing}")

    def test_setup_method_order(self):
        """
        RED: Setup methods must be called in specific order.
        Dependencies:
        - _setup_logging must be first (needed by other methods)
        - _setup_state_variables must be early (global state)
        - _setup_paths_and_config before _setup_defaults_and_preferences
        - _setup_gui before methods that use UI
        - _setup_signal_connections near end (connects to all components)
        - _setup_startup must be last (shows GUI)
        """
        calls = get_init_calls(self.tree)
        
        # Verify critical ordering
        order_checks = [
            ('_setup_logging', '_setup_state_variables', 
             "Logging should be setup before state variables"),
            ('_setup_paths_and_config', '_setup_defaults_and_preferences',
             "Paths should be setup before defaults"),
            ('_setup_gui', '_setup_workers_crew',
             "GUI should be setup before workers"),
            ('_setup_canvas_and_plotting', '_setup_tools_and_editors',
             "Canvas should be setup before tools"),
            ('_setup_system_integration', '_setup_signal_connections',
             "System integration before signal connections"),
            ('_setup_signal_connections', '_setup_startup',
             "Signal connections before startup"),
        ]
        
        for first, second, message in order_checks:
            if first in calls and second in calls:
                first_idx = calls.index(first)
                second_idx = calls.index(second)
                self.assertLess(first_idx, second_idx, message)

    def test_no_duplicate_setup_calls(self):
        """
        RED: Each setup method should be called exactly once.
        Duplicate calls would cause initialization issues.
        """
        calls = get_init_calls(self.tree)
        duplicates = set([c for c in calls if calls.count(c) > 1])
        
        self.assertEqual(len(duplicates), 0,
            f"Setup methods called multiple times: {duplicates}")


# =============================================================================
# TEST GROUP 3: Setup Method Documentation
# =============================================================================

class TestSetupMethodDocstrings(unittest.TestCase):
    """Test that setup methods have proper documentation."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)
        self.setup_methods = get_setup_methods(self.app_class)

    def test_all_setup_methods_have_docstrings(self):
        """
        RED: All setup methods should have docstrings.
        Missing docstrings make the code harder to understand.
        """
        missing = []
        for method in self.setup_methods:
            if not method['docstring']:
                missing.append(method['name'])
        
        # Note: This is now expected to pass after fixing _setup_workers_crew
        self.assertEqual(len(missing), 0,
            f"Setup methods without docstrings: {missing}")

    def test_all_docstrings_mention_phase(self):
        """
        GREEN: All setup method docstrings should indicate they are Phase 1.
        This helps track the refactoring progress.
        """
        methods_without_phase = []
        for method in self.setup_methods:
            if 'Phase 1' not in method['docstring']:
                methods_without_phase.append(method['name'])
        
        self.assertEqual(len(methods_without_phase), 0,
            f"Methods without 'Phase 1' in docstring: {methods_without_phase}")


# =============================================================================
# TEST GROUP 4: Instance Attributes
# =============================================================================

class TestInstanceAttributes(unittest.TestCase):
    """Test that all required instance attributes are declared."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)
        self.attrs = get_instance_attributes(self.app_class)

    def test_qapp_attribute(self):
        """RED: qapp reference should be stored."""
        self.assertIn('qapp', self.attrs,
            "qapp reference should be stored as instance attribute")

    def test_core_handlers_declared(self):
        """
        RED: Core handler attributes should be declared.
        These are essential for app functionality.
        Note: signal_connector is set in _setup_canvas_and_plotting, not __init__
        """
        # signal_connector is set in _setup_canvas_and_plotting method
        required = ['f_handlers', 'edit_class', 'plot_manager']
        missing = [r for r in required if r not in self.attrs]
        
        self.assertEqual(len(missing), 0,
            f"Missing core handler attributes in __init__: {missing}")

    def test_editors_declared(self):
        """RED: Editor attributes should be declared."""
        required = ['exc_editor', 'grb_editor', 'geo_editor', 'gcode_editor']
        missing = [r for r in required if r not in self.attrs]
        
        self.assertEqual(len(missing), 0,
            f"Missing editor attributes: {missing}")

    def test_tools_declared(self):
        """RED: Tool attributes should be declared."""
        # Sample of important tools
        required = [
            'paint_tool', 'isolation_tool', 'drilling_tool', 
            'milling_tool', 'distance_tool', 'panelize_tool'
        ]
        missing = [r for r in required if r not in self.attrs]
        
        self.assertEqual(len(missing), 0,
            f"Missing tool attributes: {missing}")

    def test_collection_declared(self):
        """RED: Object collection should be declared."""
        self.assertIn('collection', self.attrs,
            "Object collection should be declared")

    def test_preferences_declared(self):
        """RED: Preferences attributes should be declared."""
        # Note: 'options' is set in _setup_defaults_and_preferences
        required = ['defaults', 'preferencesUiManager']
        missing = [r for r in required if r not in self.attrs]
        
        self.assertEqual(len(missing), 0,
            f"Missing preferences attributes: {missing}")


# =============================================================================
# TEST GROUP 5: Setup Method Dependencies
# =============================================================================

class TestSetupMethodDependencies(unittest.TestCase):
    """Test that setup methods use correct dependencies."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)

    def test_setup_logging_uses_self_log(self):
        """RED: _setup_logging should initialize self.log."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_logging\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_logging not found")
        method_body = method_match.group(1)
        
        self.assertIn('self.log', method_body,
            "_setup_logging should initialize self.log")

    def test_setup_gui_uses_self_ui(self):
        """RED: _setup_gui should initialize self.ui."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_gui\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_gui not found")
        method_body = method_match.group(1)
        
        self.assertIn('self.ui', method_body,
            "_setup_gui should initialize self.ui (MainGUI)")

    def test_setup_workers_uses_self_workers(self):
        """RED: _setup_workers_crew should initialize self.workers."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_workers_crew\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_workers_crew not found")
        method_body = method_match.group(1)
        
        self.assertIn('self.workers', method_body,
            "_setup_workers_crew should initialize self.workers")

    def test_setup_gui_uses_self_plotcanvas(self):
        """RED: _setup_gui should initialize self.plotcanvas."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_gui\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_gui not found")
        method_body = method_match.group(1)
        
        self.assertIn('self.plotcanvas', method_body,
            "_setup_gui should initialize self.plotcanvas")

    def test_setup_canvas_and_plotting_content(self):
        """RED: _setup_canvas_and_plotting should have proper content."""
        source = read_appmain()
        method_body = extract_method(source, '_setup_canvas_and_plotting')
        self.assertIsNotNone(method_body, "_setup_canvas_and_plotting not found")
        
        # This method sets up canvas-related items
        # It should contain some canvas/exclusion/setup related content
        self.assertTrue(
            'exc_areas' in method_body or 
            'ExclusionAreas' in method_body or
            'setup_default' in method_body,
            "_setup_canvas_and_plotting should set up canvas-related components")


# =============================================================================
# TEST GROUP 6: Signal Connection Verification
# =============================================================================

class TestSignalConnections(unittest.TestCase):
    """Test that signal connections are properly set up."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)

    def test_signal_connections_method_exists(self):
        """RED: _setup_signal_connections method should exist."""
        methods = get_method_names(self.app_class)
        self.assertIn('_setup_signal_connections', methods)

    def test_inform_signal_connected(self):
        """RED: inform signal should be connected to info method."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_signal_connections\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_signal_connections not found")
        method_body = method_match.group(1)
        
        self.assertIn('self.inform', method_body,
            "inform signal should be connected")
        self.assertIn('self.info', method_body,
            "info method should be connected to inform signal")

    def test_file_opened_signal_connected(self):
        """RED: file_opened signal should be connected."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_signal_connections\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_signal_connections not found")
        method_body = method_match.group(1)
        
        self.assertIn('file_opened', method_body,
            "file_opened signal should be connected")

    def test_object_status_changed_connected(self):
        """RED: object_status_changed signal should be connected."""
        source = read_appmain()
        method_match = re.search(
            r'def _setup_signal_connections\(self\):(.*?)(?=\n    def |\Z)',
            source, re.DOTALL
        )
        self.assertIsNotNone(method_match, "_setup_signal_connections not found")
        method_body = method_match.group(1)
        
        self.assertIn('object_status_changed', method_body,
            "object_status_changed signal should be connected")


# =============================================================================
# TEST GROUP 7: App Class Size and Complexity
# =============================================================================

class TestAppClassMetrics(unittest.TestCase):
    """Test metrics about the App class size and complexity."""

    def setUp(self):
        self.tree, self.source = parse_appmain()
        self.app_class = get_app_class(self.tree)

    def test_method_count(self):
        """RED: Report the total method count for documentation."""
        methods = get_method_names(self.app_class)
        print(f"\nApp class has {len(methods)} methods")
        self.assertGreater(len(methods), 0)

    def test_setup_method_count(self):
        """RED: Verify exactly 11 setup methods exist."""
        setup_methods = get_setup_methods(self.app_class)
        self.assertEqual(len(setup_methods), 11,
            f"Expected 11 setup methods, found {len(setup_methods)}")

    def test_setup_methods_line_counts(self):
        """RED: Report line counts for each setup method."""
        setup_methods = get_setup_methods(self.app_class)
        print("\nSetup method line counts:")
        for method in setup_methods:
            lines = method['end_line'] - method['line'] + 1
            print(f"  {method['name']}: {lines} lines")
            self.assertGreater(lines, 0)


class TestDelegatedBehavior(unittest.TestCase):
    """Exercise App facade behavior without constructing the full GUI."""

    @classmethod
    def setUpClass(cls):
        original_argv = sys.argv
        try:
            sys.argv = [original_argv[0]]
            from appMain import App
            cls.app_class = App
        finally:
            sys.argv = original_argv

    def test_facades_preserve_handler_results(self):
        sentinel = object()
        ui_actions = SimpleNamespace(
            on_tools_database=lambda source='app': sentinel,
            on_3d_area=lambda: sentinel
        )
        object_ops = SimpleNamespace(
            on_set_zero_click=lambda event, location=None, noplot=False, use_thread=True: sentinel
        )
        app = SimpleNamespace(ui_actions=ui_actions, object_ops=object_ops)

        self.assertIs(self.app_class.on_tools_database(app, source='paint'), sentinel)
        self.assertIs(self.app_class.on_3d_area(app), sentinel)
        self.assertIs(
            self.app_class.on_set_zero_click(app, None, location=[0, 0], use_thread=False),
            sentinel
        )

    def test_geometry_database_facade_forwards_handler_results(self):
        tool = object()

        for expected in (True, 'fail'):
            with self.subTest(result=expected):
                calls = []

                def callback(received_tool, result=expected):
                    calls.append(received_tool)
                    return result

                app = SimpleNamespace(
                    ui_actions=SimpleNamespace(on_geometry_tool_add_from_db_executed=callback)
                )

                self.assertEqual(expected,
                                 self.app_class.on_geometry_tool_add_from_db_executed(app, tool))
                self.assertEqual([tool], calls)


class TestPythonCompatibility(unittest.TestCase):
    def test_custom_runner_avoids_backslashes_in_fstring_expressions(self):
        with open(__file__, 'r', encoding='utf-8') as test_file:
            source = test_file.read()

        tree = ast.parse(source)
        incompatible = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            segment = ast.get_source_segment(source, node) or ''
            if 'traceback.split' in segment and '\\' in segment:
                incompatible.append(segment)

        self.assertEqual(incompatible, [])


# =============================================================================
# Test runner
# =============================================================================

def run_all_tests():
    """Run all tests and report results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestAppClassStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestSetupMethodOrder))
    suite.addTests(loader.loadTestsFromTestCase(TestSetupMethodDocstrings))
    suite.addTests(loader.loadTestsFromTestCase(TestInstanceAttributes))
    suite.addTests(loader.loadTestsFromTestCase(TestSetupMethodDependencies))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalConnections))
    suite.addTests(loader.loadTestsFromTestCase(TestAppClassMetrics))
    suite.addTests(loader.loadTestsFromTestCase(TestDelegatedBehavior))
    suite.addTests(loader.loadTestsFromTestCase(TestPythonCompatibility))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.wasSuccessful():
        print("ALL TESTS PASSED")
    else:
        if result.failures:
            print("\nFAILURES:")
            for test, traceback in result.failures:
                traceback_lines = traceback.splitlines()
                details = traceback_lines[-2] if len(traceback_lines) >= 2 else traceback[:100]
                print(f"  - {test}: {details}")
        if result.errors:
            print("\nERRORS:")
            for test, traceback in result.errors:
                traceback_lines = traceback.splitlines()
                details = traceback_lines[-2] if len(traceback_lines) >= 2 else traceback[:100]
                print(f"  - {test}: {details}")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
