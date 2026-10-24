"""QR encoding and Gerber geometry generation from explicit data (Qt-free, unit aware).

One QR module (box) measures box_size / 10 mm (qrcode SvgFragmentImage). `units` is 'MM' or 'IN'.
"""

import builtins
import math
import re
from collections import namedtuple
from html import escape
from io import BytesIO
from typing import Iterable

import qrcode
import qrcode.exceptions
import qrcode.image.pil
import qrcode.image.svg
from copy import deepcopy  # noqa: F401  re-exported by appPlugins/ToolQRCode/__init__.py
from shapely import MultiPolygon, Polygon, box  # noqa: F401  MultiPolygon re-exported by __init__.py
from shapely.affinity import rotate, scale, translate
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from appParsers.SVG import svg_to_shapes, SvgImportError


def _(message):
    translate_fcn = getattr(builtins, '_', None)
    return translate_fcn(message) if translate_fcn else message


ERROR_CODES = {
    'L': qrcode.constants.ERROR_CORRECT_L,
    'M': qrcode.constants.ERROR_CORRECT_M,
    'Q': qrcode.constants.ERROR_CORRECT_Q,
    'H': qrcode.constants.ERROR_CORRECT_H
}
ANCHORS = ('bl', 'tl', 'br', 'tr', 'c')
MM_PER_IN = 25.4

# mask: the clearance polygon; geometry: what is added to the solid geometry; outline: the QR shapes (translated);
# modules: the single modules (translated)
QRInsertion = namedtuple('QRInsertion', ['mask', 'geometry', 'outline', 'modules'])


class QRDataOverflow(ValueError):
    """The data does not fit in the requested QR version / error correction."""


def module_size(box_size, units):
    """Size of one QR module in the given units."""
    size_mm = float(box_size) / 10.0
    return size_mm / MM_PER_IN if units == 'IN' else size_mm


def valid_color(text, allow_transparent=False):
    """True for a color name / hex value that PIL understands ('transparent' only when allowed)."""
    if not isinstance(text, str) or not text.strip():
        return False
    text = text.strip()
    if text.lower() == 'transparent':
        return allow_transparent
    from PIL import ImageColor
    try:
        ImageColor.getrgb(text)
    except ValueError:
        return False
    return True


def _is_transparent(color):
    return color is None or (isinstance(color, str) and color.strip().lower() in ('', 'transparent'))


def build_qr(text_data, version, error, box_size, border, file_type, fill_color=None, back_color=None,
             mask_pattern=None):
    """
    Build the QR code and its image.

    :param version:       1..40 fixed (never silently grown), None or 0 = automatic
    :param mask_pattern:  None = automatic, 0..7
    :param file_type:     'fragment' (SVG rects, for the geometry), 'png' or 'svg'
    :return:              (qrcode.QRCode, image); the actual version is qr.version
    :raises QRDataOverflow: the data does not fit
    """
    factory = {
        'fragment': qrcode.image.svg.SvgFragmentImage,
        'png': qrcode.image.pil.PilImage,
        'svg': qrcode.image.svg.SvgPathImage
    }[file_type]
    fixed = int(version) if version else None
    qr = qrcode.QRCode(version=fixed, error_correction=ERROR_CODES[error], box_size=box_size,
                       border=border, image_factory=factory, mask_pattern=mask_pattern)
    qr.add_data(text_data)
    try:
        qr.make(fit=fixed is None)
    except (qrcode.exceptions.DataOverflowError, ValueError) as e:
        if fixed is None:
            raise QRDataOverflow(_("The data does not fit in a QR code.")) from e
        raise QRDataOverflow(_("The data does not fit in QR version %d with error correction %s. "
                               "Use a higher version, Auto, or a lower error correction.") % (fixed, error)) from e

    if file_type == 'fragment':
        return qr, qr.make_image()
    kwargs = {}
    if file_type == 'png':
        if _is_transparent(back_color):
            kwargs['back_color'] = (0, 0, 0, 0)
            kwargs['fill_color'] = fill_color or 'black'
            return qr, _transparent_png(qr, fill_color or 'black')
        kwargs['back_color'] = back_color
        if fill_color:
            kwargs['fill_color'] = fill_color
        return qr, qr.make_image(**kwargs)
    return qr, SvgDocument(qr.make_image(), fill_color, back_color)


def _transparent_png(qr, fill_color):
    """PNG with a transparent background: the QR modules drawn with fill_color on an RGBA canvas."""
    from PIL import Image, ImageColor, ImageDraw
    matrix = qr.get_matrix()
    px = qr.box_size
    size = len(matrix) * px
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    fill = ImageColor.getrgb(fill_color)
    if len(fill) == 3:
        fill = fill + (255,)
    draw = ImageDraw.Draw(img)
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                draw.rectangle([c * px, r * px, (c + 1) * px - 1, (r + 1) * px - 1], fill=fill)
    return img


class SvgDocument:
    """SVG export with explicit colors: path filled with fill_color, optional background rect."""

    def __init__(self, image, fill_color=None, back_color=None):
        buf = BytesIO()
        image.save(buf)
        self.text = self._style(buf.getvalue().decode('UTF-8'), fill_color, back_color)

    @staticmethod
    def _style(text, fill_color, back_color):
        text = re.sub(r'\s(?:fill_color|back_color)="[^"]*"', '', text)
        fill = fill_color if isinstance(fill_color, str) and fill_color.strip() else '#000000'
        text = text.replace('<path ', '<path fill="%s" ' % escape(fill.strip(), quote=True), 1)
        if not _is_transparent(back_color):
            vb = re.search(r'viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)\s*"', text)
            head = re.search(r'<svg\b[^>]*>', text)
            if vb and head:
                rect = '<rect width="%s" height="%s" fill="%s"/>' % (vb.group(1), vb.group(2),
                                                                   escape(back_color.strip(), quote=True))
                text = text[:head.end()] + rect + text[head.end():]
        return text

    def save(self, target, *args, **kwargs):
        data = self.text.encode('UTF-8')
        if hasattr(target, 'write'):
            target.write(data)
        else:
            with open(target, 'wb') as f:
                f.write(data)


def make_qr_image(text_data, version, error, box_size, border, file_type,
                  fill_color=None, back_color=None, mask_pattern=None):
    """The QR image: a PIL image for 'png', an object with .save() for 'svg' / 'fragment'."""
    return build_qr(text_data, version, error, box_size, border, file_type, fill_color, back_color,
                    mask_pattern)[1]


def qr_info(text_data, version, error, mask_pattern=None):
    """Actual version and module count (without border) the data needs: {'version': int, 'modules': int}."""
    qr = build_qr(text_data, version, error, 10, 0, 'fragment', mask_pattern=mask_pattern)[0]
    return {'version': qr.version, 'modules': qr.modules_count}


def flatten_list(geo_list):
    for item in geo_list:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            yield from flatten_list(item)
        else:
            yield item


def _as_list(geom):
    """Flat list of the non-empty simple geometries inside geom (geometry, Multi*, or nested iterables)."""
    if geom is None:
        return []
    if hasattr(geom, 'geoms'):
        out = []
        for g in geom.geoms:
            out.extend(_as_list(g))
        return out
    if isinstance(geom, BaseGeometry):
        return [] if geom.is_empty else [geom]
    out = []
    for g in geom:
        out.extend(_as_list(g))
    return out


def utility_geometry(svg_geometry, module=None):
    """
    Union of the QR modules. The modules are axis aligned squares: the ones that touch in a row are merged
    into one rectangle first, so the union stays fast for thousands of modules.

    :param module: module size in units (for the buffer epsilon); None: the smallest module side found
    """
    polys = [p for p in _as_list(svg_geometry)]
    if not polys:
        return Polygon()
    if module is None:
        module = min(min(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p in polys)
    eps = module * 1e-4
    tol = module * 1e-3
    x0 = min(p.bounds[0] for p in polys)
    y0 = min(p.bounds[1] for p in polys)

    # snap the rectangle corners to the module grid: neighbours then share exact edges and the union
    # needs no closing buffer (the buffer of a large QR took seconds)
    def snap(v, origin):
        return origin + round((v - origin) / module) * module

    rows = {}
    rest = []
    for p in polys:
        a, b, c, d = p.bounds
        if abs(p.area - (c - a) * (d - b)) > tol * tol:       # not a rectangle: no merge
            rest.append(p)
            continue
        a, c = snap(a, x0), snap(c, x0)
        b, d = snap(b, y0), snap(d, y0)
        rows.setdefault((round(b / tol), round(d / tol)), []).append((a, b, c, d))
    merged = []
    for items in rows.values():
        items.sort()
        a, b, c, d = items[0]
        for na, nb, nc, nd in items[1:]:
            if na <= c + tol:
                c = max(c, nc)
            else:
                merged.append(box(a, b, c, d))
                a, b, c, d = na, nb, nc, nd
        merged.append(box(a, b, c, d))
    union = unary_union(merged)
    if rest:
        union = unary_union([union] + rest).buffer(eps).buffer(-eps)
    return union


def qr_geometry(text_data, version, error, box_size, border, units, mask_pattern=None, circle_steps=64):
    """
    Geometry of the QR code in the given units, lower-left of the image (border included) at the origin.

    :return: (module polygons list, utility geometry (union), info dict)
             info: version, modules (count per side), border, module_size, width, height (image incl. border)
    :raises QRDataOverflow: data does not fit
    :raises ValueError: no text or no geometry produced
    """
    if not text_data:
        raise ValueError(_("There is no QRCode Data."))
    qr, img = build_qr(text_data, version, error, box_size, border, 'fragment', mask_pattern=mask_pattern)
    buf = BytesIO()
    img.save(buf)
    try:
        geos = svg_to_shapes(buf.getvalue().decode('UTF-8'), None, units=units, resolution=circle_steps,
                             flip=True, include_text=False, app=None)
    except SvgImportError as e:
        raise ValueError(_("The QRCode geometry could not be created: %s") % str(e)) from e
    modules = [g for g in _as_list(geos) if isinstance(g, Polygon)]
    if not modules:
        raise ValueError(_("The QRCode has no geometry."))
    msize = module_size(box_size, units)
    utility = utility_geometry(modules, msize)
    if utility.is_empty:
        raise ValueError(_("The QRCode has no geometry."))
    side = (qr.modules_count + 2 * int(border)) * msize
    info = {'version': qr.version, 'modules': qr.modules_count, 'border': int(border), 'module_size': msize,
            'width': side, 'height': side}
    return modules, utility, info


# --- transforms ----------------------------------------------------------------------------------------------------
def transform_geometry(geoms, rotation=0, mirror=False, anchor='bl', margin=0.0):
    """
    Mirror (about the vertical axis, first) and rotate (counter-clockwise, 0/90/180/270) all geometries around
    the centre of their common bounding box, then move them so the chosen anchor of that box, enlarged by
    margin (the clearance mask), is at the origin. Insert at `pos` to put the anchor there.

    :param geoms:   list of items; an item is a geometry or a list of geometries (kept as a list)
    :param anchor:  'bl', 'tl', 'br', 'tr' or 'c'
    :return:        list with the same structure
    """
    rot = int(rotation) % 360
    if rot not in (0, 90, 180, 270) or anchor not in ANCHORS:
        raise ValueError("Wrong rotation or anchor.")
    flat = [g for item in geoms for g in _as_list(item)]
    if not flat:
        return list(geoms)
    minx = min(g.bounds[0] for g in flat)
    miny = min(g.bounds[1] for g in flat)
    maxx = max(g.bounds[2] for g in flat)
    maxy = max(g.bounds[3] for g in flat)
    origin = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)

    def tf(g):
        if mirror:
            g = scale(g, xfact=-1.0, yfact=1.0, origin=origin)
        if rot:
            g = rotate(g, rot, origin=origin)
        return g

    a, b, c, d = tf(box(minx, miny, maxx, maxy)).bounds
    a, b, c, d = a - margin, b - margin, c + margin, d + margin
    ax = {'bl': a, 'tl': a, 'br': c, 'tr': c, 'c': (a + c) / 2.0}[anchor]
    ay = {'bl': b, 'br': b, 'tl': d, 'tr': d, 'c': (b + d) / 2.0}[anchor]
    out = []
    for item in geoms:
        if isinstance(item, BaseGeometry):
            out.append(translate(tf(item), xoff=-ax, yoff=-ay))
        else:
            out.append([translate(tf(g), xoff=-ax, yoff=-ay) for g in _as_list(item)])
    return out


# --- tokens --------------------------------------------------------------------------------------------------------
def expand_tokens(text, context, serial_pad=0):
    """
    Replace {date} (yyyy-mm-dd), {time} (HH:MM), {project}, {object}, {serial} (zero padded to serial_pad).
    Unknown tokens, or tokens missing from context, stay as they are.

    :param context: dict; date / time may be datetime objects or ready strings
    """
    def value(key):
        if key not in context or context[key] is None:
            return None
        v = context[key]
        if key == 'date':
            return v.strftime('%Y-%m-%d') if hasattr(v, 'strftime') else str(v)
        if key == 'time':
            return v.strftime('%H:%M') if hasattr(v, 'strftime') else str(v)
        if key == 'serial':
            try:
                return str(int(v)).zfill(int(serial_pad))
            except (TypeError, ValueError):
                return str(v)
        return str(v)

    def repl(m):
        v = value(m.group(1)) if m.group(1) in ('date', 'time', 'project', 'object', 'serial') else None
        return m.group(0) if v is None else v

    return re.sub(r'\{(\w+)\}', repl, text)


# --- insertion -----------------------------------------------------------------------------------------------------
def effective_margin(margin, border_size, box_size, units):
    """Clearance around the QR: margin when given (app units), else border * module size."""
    if margin is None:
        return float(border_size) * module_size(box_size, units)
    return max(0.0, float(margin))


def _mask_polygon(utility, rounded, margin_value):
    a, b, c, d = utility.bounds
    base = box(a, b, c, d)
    if margin_value <= 0:
        return base
    return base.buffer(margin_value) if rounded == 'r' else base.buffer(margin_value, join_style='mitre')


def mask_opening(qrcode_utility_geometry, pos, border_size, box_size, rounded, units='MM', margin=None):
    """The clearance polygon around the QR placed at pos (also the opening for a soldermask companion)."""
    mask = _mask_polygon(qrcode_utility_geometry, rounded, effective_margin(margin, border_size, box_size, units))
    return translate(mask, xoff=pos[0], yoff=pos[1])


def plan_insertion(qrcode_geometry, qrcode_utility_geometry, pos, border_size, box_size, rounded, polarity,
                   units='MM', margin=None):
    """What an insertion at pos adds: QRInsertion(mask, geometry, outline, modules), all translated to pos."""
    margin_value = effective_margin(margin, border_size, box_size, units)
    mask_geo = _mask_polygon(qrcode_utility_geometry, rounded, margin_value)
    if polarity == 'pos':
        working = _as_list(qrcode_utility_geometry)
    else:
        working = _as_list(mask_geo.difference(qrcode_utility_geometry))
    return QRInsertion(
        mask=translate(mask_geo, xoff=pos[0], yoff=pos[1]),
        geometry=[translate(g, xoff=pos[0], yoff=pos[1]) for g in working],
        outline=[translate(g, xoff=pos[0], yoff=pos[1]) for g in _as_list(qrcode_utility_geometry)],
        modules=[translate(g, xoff=pos[0], yoff=pos[1]) for g in _as_list(qrcode_geometry)])


def _key_maker(tools):
    """Aperture keys are int (as the Gerber parser makes them); a dict that has only str keys keeps str."""
    if tools and all(isinstance(k, str) for k in tools):
        return str
    return int


def _new_aperture_id(tools):
    numeric = []
    for k in tools:
        try:
            numeric.append(int(k))
        except (TypeError, ValueError):
            pass
    return max(max(numeric) + 1, 10) if numeric else 10


def _aperture_record(ins, polarity, box_size, units):
    side = module_size(box_size, units)
    record = {'type': 'R', 'geometry': []}
    # Keep the 1% enlargement so the exported Gerber reconstructs joined QR modules.
    record['height'] = side * 1.01
    record['width'] = side * 1.01
    record['size'] = math.sqrt(side ** 2 + side ** 2)
    if polarity == 'pos':
        record['geometry'] = [{'solid': geo, 'follow': geo.centroid} for geo in ins.modules]
    else:
        record['geometry'] = [{'solid': geo} for geo in ins.geometry]
    return record


def insert_geometry(solid_geometry, tools, qrcode_geometry, qrcode_utility_geometry,
                    pos, border_size, box_size, rounded, polarity, units='MM', margin=None, with_outline=False):
    """
    Return the new solid geometry (list) and aperture records without mutating the source. Copper that
    intersects the clearance mask is cut by it (also when it only overlaps partly).

    :param units:         'MM' or 'IN': units of the geometry and of the object
    :param margin:        clearance in units; None = border_size modules
    :param with_outline:  also return the inserted QR outline (list of polygons) as a third item
    """
    ins = plan_insertion(qrcode_geometry, qrcode_utility_geometry, pos, border_size, box_size, rounded, polarity,
                         units, margin)
    new_solid = []
    for poly in _as_list(solid_geometry):
        if poly.intersects(ins.mask):
            new_solid.extend(_as_list(poly.difference(ins.mask)))
        else:
            new_solid.append(poly)
    new_solid.extend(ins.geometry)

    new_tools = dict(tools) if tools else {}
    make_key = _key_maker(tools)
    apid = make_key(_new_aperture_id(new_tools))
    new_tools[apid] = _aperture_record(ins, polarity, box_size, units)
    _add_region_record(new_tools, make_key, {'clear': ins.mask})
    if with_outline:
        return new_solid, new_tools, ins.outline
    return new_solid, new_tools


def _add_region_record(new_tools, make_key, record):
    """Append a record to a copy of the region aperture 0 (int or '0' key) in new_tools."""
    reg_key = next((k for k in (0, '0') if k in new_tools), None)
    if reg_key is None:
        reg_key = make_key(0)
        reg = {'type': 'REG', 'size': 0.0, 'geometry': []}
    else:
        reg = dict(new_tools[reg_key])
        reg['geometry'] = list(reg.get('geometry', []))
    reg['geometry'].append(record)
    new_tools[reg_key] = reg


def add_region(solid_geometry, tools, polygon):
    """
    Add a dark region (a soldermask opening) without cutting the geometry that is already there.
    Return the new solid geometry (list) and aperture records; the source is not changed.
    """
    new_solid = _as_list(solid_geometry) + _as_list(polygon)
    new_tools = dict(tools) if tools else {}
    _add_region_record(new_tools, _key_maker(tools), {'solid': polygon})
    return new_solid, new_tools


def new_gerber_geometry(qrcode_geometry, qrcode_utility_geometry, pos, border_size, box_size, rounded, polarity,
                        units='MM', margin=None):
    """(solid_geometry list, tools) for a new Gerber object that contains only the QR (positive or negative)."""
    ins = plan_insertion(qrcode_geometry, qrcode_utility_geometry, pos, border_size, box_size, rounded, polarity,
                         units, margin)
    return list(ins.geometry), {10: _aperture_record(ins, polarity, box_size, units)}


def preview_geometry(qrcode_geometry, qrcode_utility_geometry, box_poly, pos, selection_limit):
    """
    Preview shapes at pos for the already transformed geometry: the rings of the QR outline when the code has
    at most selection_limit modules, else its bounding box (box_poly, or the box of the utility geometry).
    """
    if len(_as_list(qrcode_geometry)) > selection_limit:
        if box_poly is None:
            box_poly = box(*qrcode_utility_geometry.bounds)
        return [translate(box_poly, xoff=pos[0], yoff=pos[1])]
    offset_geo = []
    for poly in _as_list(qrcode_utility_geometry):
        offset_geo.append(translate(poly.exterior, xoff=pos[0], yoff=pos[1]))
        for geo_int in poly.interiors:
            offset_geo.append(translate(geo_int, xoff=pos[0], yoff=pos[1]))
    return offset_geo


def size_warnings(module_size_in_units, units, min_module_mm, border):
    """Warning keys: 'module_below_min' (module smaller than min_module_mm) and 'quiet_zone' (border < 4)."""
    out = []
    module_mm = module_size_in_units * MM_PER_IN if units == 'IN' else module_size_in_units
    if module_mm < min_module_mm - 1e-9:
        out.append('module_below_min')
    if border < 4:
        out.append('quiet_zone')
    return out
