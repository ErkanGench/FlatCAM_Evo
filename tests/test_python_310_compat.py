"""The README promises Python 3.10 or newer, so no source file may use syntax that only 3.12 accepts.

A backslash inside the expression part of an f-string (PEP 701) is a SyntaxError on 3.10 and 3.11, and it stops the
whole application at import time. Python 3.12+ parses it without complaint, so the check inspects the f-string
expressions directly and also works when the tests run on 3.12 or newer.
"""

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {'.git', '.venv', 'venv', 'build', 'dist', '__pycache__', 'node_modules'}


def source_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith('.py'):
                yield Path(dirpath) / name


def python_310_offenders():
    offenders = []
    for path in source_files():
        source = path.read_text(encoding='utf-8')
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(source, filename=rel, feature_version=(3, 10))
        except SyntaxError as exc:
            offenders.append('%s:%s: %s' % (rel, exc.lineno, exc.msg))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FormattedValue):
                segment = ast.get_source_segment(source, node.value) or ''
                if '\\' in segment:
                    offenders.append('%s:%s: backslash in an f-string expression: %s'
                                     % (rel, node.value.lineno, segment[:60]))
    return offenders


def test_no_syntax_newer_than_python_310():
    offenders = python_310_offenders()
    assert not offenders, 'syntax that needs Python 3.12:\n' + '\n'.join(offenders)


if __name__ == '__main__':
    found = python_310_offenders()
    print('\n'.join(found) if found else 'ok')
    raise SystemExit(1 if found else 0)
