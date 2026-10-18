"""Affine transforms: SVG ``transform`` attribute, CSS ``transform`` property and ``transform-origin``."""
import math
import re

import numpy as np

_ITEM = re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)')
_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_CSS_FUNC = re.compile(r'([a-zA-Z0-9]+)\s*\(([^)]*)\)')
_CSS_ARG = re.compile(r'([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)')
_ANGLE = {'': 1.0, 'deg': 1.0, 'rad': 180.0 / math.pi, 'grad': 0.9, 'turn': 360.0}
_CACHE = {}


def translation(tx, ty):
    """
    :param tx: x offset
    :param ty: y offset
    :return: 3x3 translation matrix
    """
    m = np.eye(3)
    m[0, 2] = tx
    m[1, 2] = ty
    return m


def scaling(sx, sy):
    """
    :param sx: x factor
    :param sy: y factor
    :return: 3x3 scale matrix
    """
    m = np.eye(3)
    m[0, 0] = sx
    m[1, 1] = sy
    return m


def rotation(deg):
    """
    :param deg: angle in degrees
    :return: 3x3 rotation matrix
    """
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def rotation_about(deg, cx, cy):
    """
    :param deg: angle in degrees
    :param cx: centre x
    :param cy: centre y
    :return: 3x3 rotation matrix about (cx, cy), i.e. translate(c) rotate translate(-c) in one step
    """
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, cx - c * cx + s * cy], [s, c, cy - s * cx - c * cy], [0.0, 0.0, 1.0]])


def skew(deg_x, deg_y):
    """
    :param deg_x: x skew in degrees
    :param deg_y: y skew in degrees
    :return: 3x3 skew matrix
    """
    m = np.eye(3)
    m[0, 1] = math.tan(math.radians(deg_x))
    m[1, 0] = math.tan(math.radians(deg_y))
    return m


def _from_matrix(v):
    return np.array([[v[0], v[2], v[4]], [v[1], v[3], v[5]], [0.0, 0.0, 1.0]])


def _single(name, a):
    n = len(a)
    if name == 'matrix' and n == 6:
        return _from_matrix(a)
    if name == 'translate' and n in (1, 2):
        return translation(a[0], a[1] if n == 2 else 0.0)
    if name == 'scale' and n in (1, 2):
        return scaling(a[0], a[1] if n == 2 else a[0])
    if name == 'rotate' and n in (1, 3):
        if n == 1:
            return rotation(a[0])
        return rotation_about(a[0], a[1], a[2])
    if name == 'skewX' and n == 1:
        return skew(a[0], 0.0)
    if name == 'skewY' and n == 1:
        return skew(0.0, a[0])
    return None


def parse_transform(text):
    """
    :param text: SVG transform list
    :return: 3x3 matrix (treat as read-only) or None when empty
    """
    if not text:
        return None
    hit = _CACHE.get(text)
    if hit is not None:
        return hit
    m = np.eye(3)
    for item in _ITEM.finditer(text):
        t = _single(item.group(1), [float(v) for v in _NUM.findall(item.group(2))])
        if t is not None:
            m = m @ t
    if len(_CACHE) < 4096:
        _CACHE[text] = m
    return m


def parse_css_transform(text, length):
    """
    Parse a CSS ``transform`` value.

    :param text: CSS value, e.g. ``rotate(45deg) translate(10px, 2mm)``
    :param length: callable(str) -> user units for a length token such as ``2mm``
    :return: 3x3 matrix
    """
    m = np.eye(3)
    for func, body in _CSS_FUNC.findall(text or ''):
        raw = [(a.group(1), a.group(2), a.group(0)) for a in _CSS_ARG.finditer(body)]
        if not raw:
            continue
        lens = [length(r[2].replace(' ', '')) or 0.0 for r in raw]
        nums = [float(r[0]) for r in raw]
        angs = [float(r[0]) * _ANGLE.get(r[1].lower(), 1.0) for r in raw]
        t = _css_single(func.lower(), len(raw), lens, nums, angs)
        if t is not None:
            m = m @ t
    return m


def _css_single(name, n, lens, nums, angs):
    if name == 'matrix' and n == 6:
        return _from_matrix(nums)
    if name == 'translate':
        return translation(lens[0], lens[1] if n > 1 else 0.0)
    if name == 'translatex':
        return translation(lens[0], 0.0)
    if name == 'translatey':
        return translation(0.0, lens[0])
    if name == 'scale':
        return scaling(nums[0], nums[1] if n > 1 else nums[0])
    if name == 'scalex':
        return scaling(nums[0], 1.0)
    if name == 'scaley':
        return scaling(1.0, nums[0])
    if name in ('rotate', 'rotatez'):
        return rotation(angs[0])
    if name == 'skew':
        return skew(angs[0], angs[1] if n > 1 else 0.0)
    if name == 'skewx':
        return skew(angs[0], 0.0)
    if name == 'skewy':
        return skew(0.0, angs[0])
    return None


def around(m, ox, oy):
    """
    :param m: 3x3 matrix
    :param ox: origin x
    :param oy: origin y
    :return: matrix applying m around the origin
    """
    if ox == 0.0 and oy == 0.0:
        return m
    return translation(ox, oy) @ m @ translation(-ox, -oy)


def mean_scale(m):
    """
    :param m: 3x3 matrix
    :return: sqrt(|det|) of the linear part
    """
    return math.sqrt(abs(m[0, 0] * m[1, 1] - m[0, 1] * m[1, 0]))
