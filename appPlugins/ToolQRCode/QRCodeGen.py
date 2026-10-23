"""QR encoding and Gerber geometry generation from explicit data."""

from copy import deepcopy
from io import BytesIO
from typing import Iterable
import math

import qrcode
import qrcode.image.svg
import qrcode.image.pil
from shapely import MultiPolygon, Polygon, box
from shapely.affinity import translate
from shapely.ops import unary_union


def make_qr_image(text_data, version, error, box_size, border, file_type,
                  fill_color=None, back_color=None):
    error_code = {
        'L': qrcode.constants.ERROR_CORRECT_L,
        'M': qrcode.constants.ERROR_CORRECT_M,
        'Q': qrcode.constants.ERROR_CORRECT_Q,
        'H': qrcode.constants.ERROR_CORRECT_H
    }[error]
    factory = {
        'fragment': qrcode.image.svg.SvgFragmentImage,
        'png': qrcode.image.pil.PilImage,
        'svg': qrcode.image.svg.SvgPathImage
    }[file_type]
    qr = qrcode.QRCode(version=version, error_correction=error_code, box_size=box_size,
                       border=border, image_factory=factory)
    qr.add_data(text_data)
    if file_type == 'fragment':
        qr.make()
        return qr.make_image()
    if file_type == 'png':
        qr.make(fit=True)
    return qr.make_image(fill_color=fill_color, back_color=back_color)


def flatten_list(geo_list):
    for item in geo_list:
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            yield from flatten_list(item)
        else:
            yield item


def utility_geometry(svg_geometry):
    return unary_union(svg_geometry).buffer(0.0000001).buffer(-0.0000001)


def insert_geometry(solid_geometry, tools, qrcode_geometry, qrcode_utility_geometry,
                    pos, border_size, box_size, rounded, polarity):
    """Return the new solid geometry and aperture records without mutating the source."""
    if not isinstance(solid_geometry, Iterable):
        solid_geometry = [solid_geometry]
    geo_list = solid_geometry
    if isinstance(solid_geometry, MultiPolygon):
        geo_list = list(solid_geometry.geoms)

    a, b, c, d = qrcode_utility_geometry.bounds
    buff_val = border_size * (box_size / 10)
    if rounded == 'r':
        mask_geo = box(a, b, c, d).buffer(buff_val)
    else:
        mask_geo = box(a, b, c, d).buffer(buff_val, join_style="mitre")

    new_solid_geometry = []
    offset_mask_geo = translate(mask_geo, xoff=pos[0], yoff=pos[1])
    for poly in geo_list:
        if poly.contains(offset_mask_geo):
            new_solid_geometry.append(poly.difference(offset_mask_geo))
        else:
            if poly not in new_solid_geometry:
                new_solid_geometry.append(poly)
    geo_list = deepcopy(list(new_solid_geometry))
    working_geo = qrcode_utility_geometry if polarity == 'pos' else mask_geo.difference(qrcode_utility_geometry)
    try:
        for geo in working_geo:
            geo_list.append(translate(geo, xoff=pos[0], yoff=pos[1]))
    except TypeError:
        geo_list.append(translate(working_geo, xoff=pos[0], yoff=pos[1]))

    tools = deepcopy(tools)
    box_size = float(box_size) / 10.0
    sort_apid = []
    new_apid = 10
    if tools:
        for k, v in list(tools.items()):
            sort_apid.append(int(k))
        max_apid = max(sorted(sort_apid))
        if max_apid >= 10:
            new_apid = str(max_apid + 1)
    if new_apid not in tools:
        tools[new_apid] = {'type': 'R', 'geometry': []}
        # Keep the existing 1% enlargement so the exported Gerber reconstructs joined QR modules.
        tools[new_apid]['height'] = deepcopy(box_size * 1.01)
        tools[new_apid]['width'] = deepcopy(box_size * 1.01)
        tools[new_apid]['size'] = deepcopy(math.sqrt(box_size ** 2 + box_size ** 2))
    if 0 not in tools:
        tools[0] = {'type': 'REG', 'size': 0.0, 'geometry': []}
    tools[0]['geometry'].append(deepcopy({'clear': offset_mask_geo}))
    try:
        for geo in qrcode_geometry:
            geo_elem = {
                'solid': translate(geo, xoff=pos[0], yoff=pos[1]),
                'follow': translate(geo.centroid, xoff=pos[0], yoff=pos[1])
            }
            tools[new_apid]['geometry'].append(deepcopy(geo_elem))
    except TypeError:
        tools[new_apid]['geometry'].append(deepcopy({'solid': qrcode_geometry}))
    return deepcopy(geo_list), tools


def preview_geometry(qrcode_geometry, qrcode_utility_geometry, box_poly, pos, selection_limit):
    offset_geo = []
    qrcode_geometry_len = len(qrcode_geometry.geoms) if isinstance(qrcode_geometry, MultiPolygon) else \
        len(qrcode_geometry)
    if qrcode_geometry_len <= selection_limit:
        qrcode_geo = qrcode_utility_geometry.geoms if isinstance(qrcode_utility_geometry, MultiPolygon) else \
            qrcode_utility_geometry
        try:
            for poly in qrcode_geo:
                offset_geo.append(translate(poly.exterior, xoff=pos[0], yoff=pos[1]))
                for geo_int in poly.interiors:
                    offset_geo.append(translate(geo_int, xoff=pos[0], yoff=pos[1]))
        except TypeError:
            assert isinstance(qrcode_utility_geometry, Polygon)
            offset_geo.append(translate(qrcode_utility_geometry.exterior, xoff=pos[0], yoff=pos[1]))
            for geo_int in qrcode_utility_geometry.interiors:
                offset_geo.append(translate(geo_int, xoff=pos[0], yoff=pos[1]))
    else:
        offset_geo = [translate(box_poly, xoff=pos[0], yoff=pos[1])]
    return offset_geo
