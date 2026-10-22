"""The --headless and --command options are parsed in the class body of App, before anything starts."""

import os
import subprocess
import sys
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse(argv, tmp_path):
    code = textwrap.dedent(f'''
        import sys
        sys.path.insert(0, {REPO!r})
        sys.argv = ['flatcam.py'] + {argv!r}
        import appMain
        A = appMain.App
        print(repr((A.cmd_line_headless, A.cmd_line_command, A.cmd_line_shellvar)))
    ''')
    return subprocess.run([sys.executable, '-c', code], cwd=str(tmp_path), capture_output=True, text=True,
                          timeout=300)


def test_without_options(tmp_path):
    result = _parse([], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "(False, '', '')"


def test_headless_and_command(tmp_path):
    result = _parse(['--headless', '--command=new_geometry g; puts ok', '--shellvar=1,2'], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "(True, 'new_geometry g; puts ok', '1,2')"

