"""
appCommon.SafeEval.safe_eval(): the values that eval() was used for, without running code.

A Gerber aperture macro, a project or preferences option, the clipboard and the entry fields were read with eval():
opening a Gerber made by someone else or pasting a text could run any Python code.

    python tests/test_safe_eval.py
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtWidgets     # noqa: E402

from appCommon.SafeEval import safe_eval      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# a call of eval() or exec(), not of a method like dialog.exec()
CALL_RE = re.compile(r'(?<![\w.])(?:eval|exec)\s*\(')
# frozen builds and third-party code that can sit in a checkout (as in test_python_310_compat.py)
SKIP_DIRS = {'build', 'dist', 'venv', 'site-packages', 'node_modules'}

# when it runs, this code puts MARKER in sys.modules; it has no '*', ',' or 'x' (the Gerber macro parser splits the
# text on '*' and ',' and changes 'x' to '*')
MARKER = 'flatcam_safe_eval_marker'
CODE = "__import__('sys').modules.setdefault('%s')" % MARKER

# parse_gerber() in a new interpreter: a big integer calculation cannot be interrupted, so a parse that does not end
# fails the test at the timeout instead of stopping the run. appMain (imported by Gerber()) reads sys.argv when it is
# imported: no arguments, and it is imported before the clock starts.
PARSE_IN_NEW_PROCESS = textwrap.dedent("""
    import json, sys, time
    sys.path.insert(0, %r)
    import appMain
    from test_safe_eval import parse_gerber
    start = time.perf_counter()
    result = parse_gerber(%r)[1]
    print('PARSE_RESULT=' + json.dumps([result, time.perf_counter() - start]))
""")


def parse_gerber(macro):
    """Gerber.parse_file() of a file with the aperture macro M1 flashed 1 time at (1, 2): (the Gerber, the result)"""
    from appParsers.ParseGerber import Gerber

    options = {
        'gerber_def_units': 'MM', 'gerber_def_zeros': 'L', 'gerber_circle_steps': 64,
        'gerber_simp_tolerance': 0.001, 'gerber_simplification': True, 'gerber_buffering': True,
        'gerber_extra_buffering': 0.0, 'gerber_clean_apertures': True, 'gerber_use_buffer_for_union': True,
        'global_tolerance': 0.01,
    }
    app = SimpleNamespace(
        options=options, decimals=4, abort_flag=False, log=Mock(), inform=Mock(), app_units='MM',
        plotcanvas=SimpleNamespace(new_shape_collection=Mock()), proc_container=Mock(),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'macro.gbr')
        with open(path, 'w') as f:
            f.write('%FSLAX46Y46*%\n%MOMM*%\n' + macro + '\n%ADD10M1,0.5*%\nD10*\nX1000000Y2000000D03*\nM02*\n')
        gbr = Gerber(app)
        return gbr, gbr.parse_file(path)


class MarkerCase(unittest.TestCase):
    def setUp(self):
        sys.modules.pop(MARKER, None)
        self.addCleanup(sys.modules.pop, MARKER, None)

    def assertCodeDidNotRun(self):
        self.assertFalse(MARKER in sys.modules, 'the code in the text was run')


class TestValues(unittest.TestCase):
    def test_literals(self):
        self.assertEqual(0.1, safe_eval('0.1'))
        self.assertEqual(-3, safe_eval(' -3 '))
        self.assertEqual((0.1, 0.2), safe_eval('0.1, 0.2'))
        self.assertEqual((1.0, 2.5), safe_eval('(1.0, 2.5)'))
        self.assertEqual([1, 2], safe_eval('[1, 2]'))
        self.assertEqual({'a': 1}, safe_eval("{'a': 1}"))
        self.assertIs(True, safe_eval('True'))
        self.assertIsNone(safe_eval('None'))
        self.assertEqual('text', safe_eval("'text'"))
        self.assertEqual(1e-3, safe_eval('1e-3'))
        self.assertEqual(2.5, safe_eval(2.5))

    def test_arithmetic(self):
        self.assertAlmostEqual(10 / 3, safe_eval('10/3'))
        self.assertAlmostEqual(0.6, safe_eval('0.5*1+0.1'))
        self.assertEqual(-0.5, safe_eval('-(0.25+0.25)'))
        self.assertEqual(0.5, safe_eval('--0.5'))
        self.assertEqual(8, safe_eval('2**3'))
        self.assertEqual(1, safe_eval('7 % 3'))
        self.assertEqual(3, safe_eval('7 // 2'))
        self.assertTrue(bool(safe_eval('1')))
        self.assertFalse(bool(safe_eval('0')))

    def test_same_value_as_eval(self):
        # the tool diameters and the toolchange / end X,Y of the G-code keep their values
        for text in ('0.1', ' 0.2', '-1.27', '10/3', '0.8*0.5', '1.0+0.25', '-(0.1)', '25.4/1000', '1e-3',
                     '(1.5, -2.0)'):
            with self.subTest(text=text):
                self.assertEqual(eval(text), safe_eval(text))

    def test_code_is_refused(self):
        for text in ("__import__('os').system('echo hacked')", 'open("x")', 'x', 'a.b', '[1][0]',
                     '(lambda: 1)()', '[i for i in range(3)]', "'a' * 3", '"a" + "b"', '9**9**9', '1/0',
                     '{**{}}', 'True + 1', '1 if 1 else 2', '1 < 2', '2 ^ 3', '1j // 2', ''):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    safe_eval(text)

    def test_too_long_or_too_deep_is_refused(self):
        for text in ('1+' * 49999 + '1', '-' * 99990 + '1', '(' * 300 + '1' + ')' * 300, '1' * 100001):
            with self.subTest(text=text[:10]):
                with self.assertRaises(ValueError):
                    safe_eval(text)

    def test_not_a_string(self):
        with self.assertRaises(ValueError):
            safe_eval(None)
        with self.assertRaises(ValueError):
            safe_eval(['1'])


class TestIntegerSize(unittest.TestCase):
    """A product or a power of integers above MAX_INTEGER_BITS (4096) is refused before it is calculated."""

    def test_power_of_a_power_is_refused(self):
        # every exponent is within MAX_EXPONENT, the result would have 1000001 bits
        with self.assertRaises(ValueError):
            safe_eval('(2**1000)**1000')

    def test_long_multiplication_is_refused(self):
        # 2**1000 has 1001 bits: a product of 4 fits in 4096 bits, a product of 5 does not
        self.assertEqual(2 ** 4000, safe_eval('*'.join(['2**1000'] * 4)))
        for text in ('*'.join(['2**1000'] * 5), '*'.join(['4294967295'] * 200)):
            with self.subTest(text=text[:20]):
                with self.assertRaises(ValueError):
                    safe_eval(text)

    def test_ordinary_arithmetic_still_works(self):
        self.assertEqual(25.4 / 1000, safe_eval('25.4/1000'))
        self.assertEqual(-1.27, safe_eval('-1.27'))
        self.assertEqual(-8, safe_eval('-2**3'))
        self.assertEqual(-8, safe_eval('(-2)**3'))
        self.assertEqual(1024, safe_eval('2**10'))
        self.assertEqual(0.5, safe_eval('2**-1'))
        self.assertEqual(2 ** 1000, safe_eval('2**1000'))
        # floats as before
        self.assertEqual(2.0 ** 1000, safe_eval('2.0**1000'))
        self.assertEqual(2.0 ** 999, safe_eval('2**1000*0.5'))
        self.assertEqual(1e300 * 1e300, safe_eval('1e300*1e300'))
        with self.assertRaises(ValueError):
            safe_eval('10.0**400')

    def test_zero_one_and_minus_one_stay_small(self):
        big = '0x' + 'f' * 2000     # an integer of 8000 bits
        for text, value in ((big + '*0', 0), ('0*' + big, 0), (big + '**0', 1), ('0**1000', 0), ('1**1000', 1),
                            ('(-1)**999', -1), ('(-1)**1000', 1)):
            with self.subTest(text=text[-12:]):
                self.assertEqual(value, safe_eval(text))

    def test_exponent_limit_is_kept(self):
        for text in ('2**1001', '1**1001', '0.5**-1001'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    safe_eval(text)


class TestGerberMacro(MarkerCase):
    """Opening a Gerber file: the aperture macro expressions are values, not code."""

    parse = staticmethod(parse_gerber)

    def test_macro_arithmetic_still_works(self):
        # $2 = $1 x 2 + 0.25 = 1.25: a circle of 1.25 mm flashed at (1, 2)
        gbr, result = self.parse('%AMM1*$2=$1x2+0.25*1,1,$2,0,0*%')
        self.assertIsNone(result)
        circle = gbr.tools[10]['geometry'][0]['solid']
        self.assertAlmostEqual(1.25, circle.bounds[2] - circle.bounds[0], places=3)
        self.assertAlmostEqual(1.0, circle.centroid.x, places=6)
        self.assertAlmostEqual(2.0, circle.centroid.y, places=6)

    def test_code_in_a_macro_primitive_does_not_run(self):
        gbr, result = self.parse('%%AMM1*1,1,$1,0,%s or 0*%%' % CODE)
        self.assertCodeDidNotRun()
        self.assertEqual('fail', result)

    def test_code_in_a_macro_variable_does_not_run(self):
        gbr, result = self.parse('%%AMM1*$2=%s or 1*1,1,$2,0,0*%%' % CODE)
        self.assertCodeDidNotRun()
        self.assertEqual('fail', result)

    def test_huge_integer_in_a_macro_fails_quickly(self):
        # ((2**1000)**1000)**1000 has 10**9 bits: without the integer size limit this parse takes 8 s (0.5 GB) on a
        # desktop PC, with 3 instead of 2 more than 5 minutes. With the limit it takes about 0.02 s.
        code = PARSE_IN_NEW_PROCESS % (str(ROOT / 'tests'), '%AMM1*1,1,((2xx1000)xx1000)xx1000,0,0*%')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        try:
            # the import of appMain takes 5 to 10 s on Windows
            run = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True,
                                 timeout=120)
        except subprocess.TimeoutExpired:
            self.fail('the parse did not end in 120 s')
        self.assertEqual(0, run.returncode, run.stderr[-2000:])
        result, seconds = json.loads(run.stdout.split('PARSE_RESULT=', 1)[1])
        self.assertEqual('fail', result)
        self.assertLess(seconds, 2)

    def test_aperture_macro_refuses_code(self):
        from camlib import ApertureMacro

        macro = ApertureMacro('EVIL')
        macro.raw = '1,1,1,0,%s or 0*' % CODE
        with self.assertRaises(ValueError):
            macro.make_geometry([])
        self.assertCodeDidNotRun()


class TestUserText(MarkerCase):
    """The entry fields and the clipboard."""

    @classmethod
    def setUpClass(cls):
        cls.qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_entries_evaluate_arithmetic_and_refuse_code(self):
        from appGUI.GUIElements import FloatEntry, EvalEntry, NumericalEvalTupleEntry

        for cls, text, value in ((FloatEntry, '10/4', 2.5), (EvalEntry, '0.1, 0.2', (0.1, 0.2)),
                                 (NumericalEvalTupleEntry, '(1.5, -2.0)', (1.5, -2.0))):
            with self.subTest(entry=cls.__name__):
                entry = cls()
                self.addCleanup(entry.deleteLater)
                entry.setText(text)
                self.assertEqual(value, entry.get_value())
                entry.setText(CODE)
                self.assertIsNone(entry.get_value())
        self.assertCodeDidNotRun()

    def test_jump_to_does_not_run_the_clipboard_or_the_typed_text(self):
        from appHandlers.appObjectOps import AppObjectOps

        fcapp = SimpleNamespace(log=Mock(), inform=Mock(), defaults=Mock(), options={}, ui=None, resource_location='',
                                mouse_pos=[0.0, 0.0], clipboard=SimpleNamespace(text=lambda: CODE))
        handler = AppObjectOps(fcapp)
        dialogs = []

        def dialog(**kwargs):
            dialogs.append(kwargs)
            return SimpleNamespace(ok=True, location=CODE, reference='abs')

        with patch('appGUI.GUIElements.DialogBoxRadio', side_effect=dialog):
            self.assertIsNone(handler.on_jump_to())
        self.assertCodeDidNotRun()
        self.assertIsNone(dialogs[0]['initial_text'])

        # a point copied from the canvas is still offered in the dialog
        fcapp.clipboard = SimpleNamespace(text=lambda: '(1.5, -2.0)')
        with patch('appGUI.GUIElements.DialogBoxRadio', side_effect=dialog):
            handler.on_jump_to()
        self.assertEqual('(1.5, -2.0)', dialogs[1]['initial_text'])


class TestNoEval(unittest.TestCase):
    def test_application_code_has_no_eval_or_exec_call(self):
        """Text from files, projects, preferences, the clipboard or the command line is read with safe_eval()."""
        found = []
        for folder, dirs, files in os.walk(ROOT):
            # not the tests, the bundled libraries, hidden folders, a build or a virtual environment in the checkout
            dirs[:] = sorted(d for d in dirs if not d.startswith(('.', '__')) and d not in SKIP_DIRS and
                             not (folder == str(ROOT) and d in ('tests', 'libs')) and
                             not os.path.exists(os.path.join(folder, d, 'pyvenv.cfg')))
            for name in sorted(f for f in files if f.endswith('.py')):
                path = Path(folder) / name
                text = path.read_text(encoding='utf-8', errors='replace')
                if not CALL_RE.search(text):
                    continue
                for node in ast.walk(ast.parse(text)):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                            node.func.id in ('eval', 'exec'):
                        found.append('%s:%d' % (path.relative_to(ROOT).as_posix(), node.lineno))
        self.assertEqual([], found)


if __name__ == '__main__':
    unittest.main()
