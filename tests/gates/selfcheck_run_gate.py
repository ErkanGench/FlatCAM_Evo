#!/usr/bin/env python
"""Self check of run_gate.py (no ``test_`` prefix, so pytest does not collect it).

Checks that run_gate.py exits non-zero for a pattern that matches no file and for a file with a syntax error.
Run it after each change of run_gate.py.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_GATE = Path(__file__).resolve().parent / 'run_gate.py'


def run(*extra):
    return subprocess.run([sys.executable, str(RUN_GATE)] + list(extra), cwd=str(ROOT),
                          capture_output=True, text=True)


def main():
    failed = False

    proc = run('--targeted', 'tests/no_such_file_*.py')
    ok = proc.returncode != 0
    print('%s  no matching file -> exit %d' % ('ok  ' if ok else 'FAIL', proc.returncode))
    failed |= not ok

    with tempfile.TemporaryDirectory(prefix='run_gate_selfcheck_') as tmp:
        bad = Path(tmp) / 'test_syntax_error_selfcheck.py'
        bad.write_text('def test_x(:\n    pass\n', encoding='utf-8')
        proc = run('--targeted', str(bad))
        ok = proc.returncode != 0
        print('%s  syntax error file -> exit %d' % ('ok  ' if ok else 'FAIL', proc.returncode))
        if not ok:
            sys.stdout.write(proc.stdout[-2000:] + proc.stderr[-2000:])
        failed |= not ok

    sys.path.insert(0, str(RUN_GATE.parent))
    import run_gate
    with tempfile.TemporaryDirectory(prefix='run_gate_selfcheck_') as tmp:
        run_gate.BUDGET = Path(tmp) / 'test_budget.json'
        run_gate.BUDGET.write_text('{"max_tests": 2, "max_files": 1}', encoding='utf-8')
        over_tests = run_gate.budget_warning(['a.py::t1', 'a.py::t2', 'a.py::t3'])
        over_files = run_gate.budget_warning(['a.py::t1', 'b.py::t1'])
        within = run_gate.budget_warning(['a.py::t1', 'a.py::t2'])
    ok = bool(over_tests) and 'test budget exceeded: 3 tests > 2' in over_tests
    print('%s  more tests than the budget -> %s' % ('ok  ' if ok else 'FAIL', 'warning' if over_tests else 'none'))
    failed |= not ok
    ok = bool(over_files) and 'test budget exceeded: 2 files > 1' in over_files
    print('%s  more files than the budget -> %s' % ('ok  ' if ok else 'FAIL', 'warning' if over_files else 'none'))
    failed |= not ok
    ok = within is None
    print('%s  counts within the budget -> %s' % ('ok  ' if ok else 'FAIL', 'no warning' if ok else 'warning'))
    failed |= not ok

    print('SELFCHECK FAILED' if failed else 'SELFCHECK PASSED')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
