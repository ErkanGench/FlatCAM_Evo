"""cx_Freeze configuration for the Linux and macOS release packages.

Run from the repository root: python scripts/freeze_release.py bdist_appimage
or, on macOS: python scripts/freeze_release.py bdist_dmg
"""

import sys
from pathlib import Path

from cx_Freeze import Executable, setup


ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    # Match make_freeze.py: appMain and the resource lookups live in lib/.
    include_files = [
        (str(ROOT / name), f'lib/{name}')
        for name in ('assets', 'resources', 'locale', 'locales', 'preprocessors', 'config')
        if (ROOT / name).is_dir()
    ]
    options = {
        'build_exe': {
            'build_exe': 'build/release',
            'path': [str(ROOT), *sys.path],
            'include_files': include_files,
            # These packages load modules by name at runtime.
            'packages': ['OpenGL', 'ortools', 'services.updater'],
            'excludes': ['pandas'],
        },
        'bdist_appimage': {'target_name': 'FlatCAM_EVO'},
        'bdist_mac': {
            'bundle_name': 'FlatCAM_EVO',
            'codesign_identity': '-',
            'plist_items': [('CFBundleIdentifier', 'org.flatcam.evo')],
        },
        'bdist_dmg': {'volume_label': 'FlatCAM EVO', 'applications_shortcut': True},
    }
    icon = ROOT / 'assets' / 'resources' / 'app256.png'
    if sys.platform == 'darwin':
        from PIL import Image

        mac_icon = ROOT / 'build' / 'FlatCAM_EVO.icns'
        mac_icon.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(icon) as image:
            image = image.convert('RGBA')
            side = max(image.size)
            square = Image.new('RGBA', (side, side), (0, 0, 0, 0))
            square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
            square.resize((1024, 1024)).save(mac_icon, format='ICNS')
        options['bdist_mac']['iconfile'] = str(mac_icon)

    setup(
        name='FlatCAM_EVO',
        description='FlatCAM EVO PCB CAM application',
        packages=[],
        options=options,
        executables=[Executable(str(ROOT / 'flatcam.py'), base='gui', target_name='FlatCAM',
                                icon=str(icon) if sys.platform == 'linux' else None)],
    )
