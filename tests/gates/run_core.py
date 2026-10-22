#!/usr/bin/env python
"""Core gate: the outcome gate over every test file except the slow ones.

The slow files are listed in ``tests/gates/slow_files.txt`` (one path per line, ``<path>  # <seconds>``). Every other
``tests/**/test_*.py`` file is in the core, so a new test file joins the core by default. The core runs through
``run_gate.py --targeted`` (8 xdist workers, ``--dist loadfile``) and its outcomes are compared with
``tests/gates/outcome_baseline.json``.

    python tests/gates/run_core.py                  # run the core, compare with the baseline (about 30-35 s)
    python tests/gates/run_core.py --workers 0      # 1 serial process
    python tests/gates/run_core.py --list           # print the core files and the skipped slow files

Run ``run_gate.py`` (the full gate) before a push: the core does not run the slow files.

Exit codes: 0 gate passed, 1 gate failed.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATES = Path(__file__).resolve().parent
SLOW_FILES = GATES / 'slow_files.txt'

sys.path.insert(0, str(GATES))
import run_gate  # noqa: E402


def read_slow_files():
    """Paths of slow_files.txt (relative to the repository root, forward slashes)."""
    paths = set()
    if not SLOW_FILES.exists():
        return paths
    for line in SLOW_FILES.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        paths.add(line.split('#', 1)[0].strip().replace('\\', '/'))
    return paths


def core_files(slow):
    every = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests').rglob('test_*.py'))
    return [f for f in every if f not in slow]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workers', type=int, default=run_gate.default_workers(),
                        help='pytest-xdist workers (default: 8 if pytest-xdist is installed); 0 = 1 serial process')
    parser.add_argument('--list', action='store_true', help='print the core files and the slow files, run nothing')
    args = parser.parse_args()

    slow = read_slow_files()
    missing = sorted(p for p in slow if not (ROOT / p).is_file())
    for path in missing:
        print('note: slow_files.txt names a file that does not exist (remove the line): %s' % path)
    files = core_files(slow)
    if args.list:
        print('core: %d files; slow (skipped): %d files' % (len(files), len(slow) - len(missing)))
        for path in files:
            print('  core  %s' % path)
        for path in sorted(slow):
            print('  slow  %s' % path)
        return 0
    if not files:
        print('GATE FAILED: the core has no test file')
        return 1
    print('run_core: %d files (%d slow files skipped)' % (len(files), len(slow) - len(missing)))
    sys.argv = [sys.argv[0], '--workers', str(args.workers), '--targeted'] + files
    code = run_gate.main()
    # the budget counts the whole suite: the ids of the core run plus the baseline ids of the slow files
    total = set(run_gate.LAST_OUTCOMES)
    if run_gate.BASELINE.exists():
        baseline = json.loads(run_gate.BASELINE.read_text(encoding='utf-8'))
        total.update(i for i in baseline if i.split('::', 1)[0] in slow)
    warning = run_gate.budget_warning(sorted(total))
    if warning:
        print(warning)
    return code


if __name__ == '__main__':
    sys.exit(main())
