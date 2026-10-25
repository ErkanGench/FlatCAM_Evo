"""Launch a frozen FlatCAM from outside its source tree before publishing it."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def check_release(executable):
    executable = str(Path(executable).resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix='flatcam-release-') as folder:
        env = os.environ.copy()
        for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH',
                     'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'TCL_LIBRARY', 'TK_LIBRARY'):
            env.pop(name, None)
        env['QT_QPA_PLATFORM'] = 'offscreen'
        env['FLATCAM_DATA_PATH'] = str(Path(folder) / 'settings')
        result = subprocess.run(
            [executable, '--headless', '--command=puts FLATCAM_RELEASE_SMOKE_OK'],
            cwd=folder, env=env, capture_output=True, text=True, timeout=180,
        )
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        if result.returncode or 'FLATCAM_RELEASE_SMOKE_OK' not in result.stdout:
            raise RuntimeError(f'Frozen FlatCAM startup failed (exit code {result.returncode})')


if __name__ == '__main__':
    check_release(sys.argv[1])
