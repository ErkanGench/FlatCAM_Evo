"""Recolor single-color icon files without changing semantic indicators."""

from pathlib import Path
import re

import numpy as np
from PyQt6 import QtCore, QtGui


PROTECTED_ICONS = {
    'axis18.png', 'settings18.png', 'hud18.png',
    'black32.png', 'white32.png', 'red32.png', 'green32.png', 'blue32.png',
    'yellow32.png', 'brown32.png', 'indigo32.png', 'violet32.png',
}


def recolor_icons(directory, color):
    """Apply an RGB hex color to monochrome PNG/ICO files in one theme directory.

    Alpha and relative shading are retained. Project icons, status indicators,
    color swatches, animations and mixed-color images are never rewritten.
    """
    if not isinstance(color, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', color) is None:
        raise ValueError('Expected an RGB color in #RRGGBB format.')
    directory = Path(directory)
    if not directory.is_dir():
        raise OSError('Icon directory does not exist: %s' % directory)

    target = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    pending = []
    for path in sorted(directory.iterdir()):
        if (not path.is_file() or path.is_symlink() or path.suffix.lower() not in ('.png', '.ico') or
                path.stem.endswith(('_project', '_status')) or path.name in PROTECTED_ICONS or
                path.name.endswith('light12.png') or path.stem.startswith('active')):
            continue
        reader = QtGui.QImageReader(str(path))
        if reader.imageCount() > 1:
            del reader
            continue
        image = reader.read()
        error = reader.errorString()
        del reader
        if image.isNull():
            raise OSError('Cannot read icon %s: %s' % (path.name, error))
        image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.bits().asarray(image.sizeInBytes()), dtype=np.uint8).reshape(
            image.height(), image.width(), 4)
        rgb = pixels[:, :, :3]
        visible = pixels[:, :, 3] > 32
        if not visible.any():
            continue
        samples = rgb[visible].astype(float)
        # Near-neutral whites/grays include small RGB differences from antialiasing.
        if np.any(np.ptp(samples, axis=1) > 20):
            samples = samples[samples.max(axis=1) >= min(32, samples.max() / 8)]
            colors, counts = np.unique(samples, axis=0, return_counts=True)
            reference = colors[counts.argmax()]
            normalized = samples * 255 / samples.max(axis=1, keepdims=True)
            reference = reference * 255 / reference.max()
            # ponytail: conservative single-hue test; uncertain artwork stays untouched.
            if np.any(np.abs(normalized - reference) > 20):
                continue

        foreground = rgb[pixels[:, :, 3] > 0]
        if np.array_equal(foreground[foreground.max(axis=1).argmax()], target):
            continue

        original = image.copy()
        brightness = rgb.max(axis=2).astype(float)
        peak = brightness[pixels[:, :, 3] > 0].max()
        if peak:
            brightness /= peak
        else:
            brightness[:] = 1
        tinted = np.rint(brightness[:, :, None] * target).astype(np.uint8)
        rgb[pixels[:, :, 3] > 0] = tinted[pixels[:, :, 3] > 0]
        if image == original:
            continue

        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, path.suffix[1:].upper()):
            raise OSError('Cannot encode icon: %s' % path.name)
        pending.append((path, path.read_bytes(), bytes(buffer.data())))

    written = []
    try:
        for path, original, data in pending:
            _write_icon(path, data)
            written.append((path, original))
    except OSError:
        for path, original in reversed(written):
            _write_icon(path, original)
        raise
    return len(written)


def _write_icon(path, data):
    output = QtCore.QSaveFile(str(path))
    if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OSError('Cannot write icon %s: %s' % (path.name, output.errorString()))
    if output.write(data) != len(data):
        output.cancelWriting()
        raise OSError('Cannot write icon %s: %s' % (path.name, output.errorString()))
    if not output.commit():
        raise OSError('Cannot replace icon %s: %s' % (path.name, output.errorString()))
