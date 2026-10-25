"""cx_Freeze configuration for the Linux and macOS release packages.

Run from the repository root: python scripts/freeze_release.py bdist_appimage
or, on macOS: python scripts/freeze_release.py bdist_dmg
"""

import ast
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def bundle_metadata(source=ROOT / 'appMain.py'):
    """Read the tagged application's identity without importing its GUI or parsing build arguments."""
    tree = ast.parse(Path(source).read_text(encoding='utf-8'))
    app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'App')
    fields = {
        target.id: ast.literal_eval(node.value)
        for node in app.body if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in ('version', 'version_date')
    }
    version = str(fields['version']).split('.')
    if not 1 <= len(version) <= 3 or not all(part.isdecimal() for part in version):
        raise ValueError('App.version must have one to three numeric components for macOS packaging')
    date = datetime.strptime(fields['version_date'], '%Y/%m/%d')
    return {
        'CFBundleName': 'FlatCAM Evo',
        'CFBundleDisplayName': 'FlatCAM Evo',
        'CFBundleIdentifier': 'org.flatcam.evo',
        'CFBundleShortVersionString': '.'.join(version + ['0'] * (3 - len(version))),
        'CFBundleVersion': f'{date.year}.{date.month}.{date.day}',
    }


if __name__ == '__main__':
    from cx_Freeze import Executable, setup

    metadata = bundle_metadata()
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
            'plist_items': list(metadata.items()),
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
        version=metadata['CFBundleShortVersionString'],
        description='FlatCAM EVO PCB CAM application',
        packages=[],
        options=options,
        executables=[Executable(str(ROOT / 'flatcam.py'), base='gui', target_name='FlatCAM',
                                icon=str(icon) if sys.platform == 'linux' else None)],
    )
