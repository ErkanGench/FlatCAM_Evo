"""
TEXT, ATTRIB and MTEXT conversion through ezdxf.addons.text2path (no matplotlib needed).
"""
import logging
import re

import ezdxf
from shapely.geometry import LineString

from .curves import FLATTEN_TOLERANCE, path_to_rings, rings_to_polygons

log = logging.getLogger('base')

MIN_EZDXF_VERSION = (1, 4, 5)
# Name of the temporary block MTEXT is exploded into.
SCRATCH_BLOCK = '*FC_MTEXT_SCRATCH'


def _parse_version(version):
    """
    :param version:     version string, e.g. '1.4.5' or '1.4.5b1'
    :return:            tuple of 3 ints, or None when it cannot be parsed
    """
    match = re.match(r'^\s*(\d+)\.(\d+)\.(\d+)', str(version))
    return tuple(int(g) for g in match.groups()) if match else None


try:
    from ezdxf.addons import text2path
    TEXT2PATH_IMPORTED = True
except ImportError:
    text2path = None
    TEXT2PATH_IMPORTED = False

try:
    from ezdxf.addons import MTextExplode
except ImportError:
    MTextExplode = None

_version = _parse_version(getattr(ezdxf, '__version__', ''))
TEXT2PATH_VERSION_OK = _version is not None and _version >= MIN_EZDXF_VERSION
TEXT_RENDERING_AVAILABLE = TEXT2PATH_IMPORTED and TEXT2PATH_VERSION_OK

if not TEXT_RENDERING_AVAILABLE:
    log.warning("DXF text import disabled: needs ezdxf>=1.4.5 with ezdxf.addons.text2path "
                "(found ezdxf %s)." % getattr(ezdxf, '__version__', '?'))


def _text_rings(entity, tolerance):
    """
    :param entity:      TEXT or ATTRIB
    :param tolerance:   flattening tolerance in drawing units
    :return:            list of coordinate lists, one per glyph contour
    """
    rings = []
    for path in text2path.make_paths_from_entity(entity):
        rings.extend(path_to_rings(path, tolerance=tolerance))
    return rings


def _mtext_rings(mtext, tolerance):
    """
    Explode an MTEXT into TEXT entities (one per line, alignment and spacing resolved) in a
    scratch block, take their contours and remove the block again. The MTEXT is left untouched.

    :param mtext:       ezdxf MTEXT (may be a virtual one from a block reference)
    :param tolerance:   flattening tolerance in drawing units
    :return:            list of coordinate lists, one per glyph contour
    """
    doc = mtext.doc
    if doc is None or MTextExplode is None:
        return []
    block = doc.blocks.new(SCRATCH_BLOCK)
    try:
        with MTextExplode(block) as exploder:
            exploder.explode(mtext, destroy=False)
        rings = []
        for entity in list(block):
            rings.extend(_text_rings(entity, tolerance))
        return rings
    finally:
        doc.blocks.delete_block(SCRATCH_BLOCK, safe=False)


def text_entity_to_shapes(entity, text_mode='stroke', tolerance=FLATTEN_TOLERANCE):
    """
    Convert a TEXT, ATTRIB or MTEXT entity to glyph geometry.

    :param entity:      ezdxf TEXT, ATTRIB or MTEXT entity
    :param text_mode:   'stroke' (glyph contours as LineStrings), 'outline' (filled Polygons)
                        or 'none' (nothing)
    :param tolerance:   flattening tolerance in drawing units
    :return:            list of Shapely geometries (empty when unsupported or on error)
    """
    if text_mode not in ('stroke', 'outline') or not TEXT_RENDERING_AVAILABLE:
        return []
    kind = entity.dxftype()
    if kind not in ('TEXT', 'ATTRIB', 'MTEXT'):
        return []
    try:
        rings = _mtext_rings(entity, tolerance) if kind == 'MTEXT' else _text_rings(entity, tolerance)
    except Exception as err:
        log.debug("DXF text skipped: %s" % str(err))
        return []
    if text_mode == 'outline':
        return rings_to_polygons(rings)
    lines = [LineString(r) for r in rings if len(r) >= 2]
    return [ln for ln in lines if ln.length > 0]
