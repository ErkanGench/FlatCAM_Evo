"""Raster polygonization and image geometry transforms. No Qt here."""

import numpy as np
from rasterio import open as rasterio_open
from rasterio.features import shapes
from shapely.affinity import scale, translate
from shapely.geometry import shape


def scale_geometry(geometry, units='MM', dpi=96):
    """Scale pixel coordinates to application units without changing the source."""
    scale_factor = 25.4 / dpi if units.lower() == 'mm' else 1 / dpi
    return [translate(scale(g, scale_factor, scale_factor, origin=(0, 0))) for g in geometry]


def import_raster(filename, flip=True, units='MM', dpi=96, mode='black', mask=None, raster_opener=None):
    """Read image bands, apply the masks, and polygonize in application units."""
    if mask is None:
        mask = [128, 128, 128, 128]

    if raster_opener is None:
        raster_opener = rasterio_open
    with raster_opener(filename) as src:
        red = green = blue = src.read(1)
        try:
            green = src.read(2)
        except Exception:
            pass
        try:
            blue = src.read(3)
        except Exception:
            pass

    if mode == 'black':
        mask_setting = red <= mask[0]
        total = red
    else:
        mask_setting = (red <= mask[1]) + (green <= mask[2]) + (blue <= mask[3])
        total = np.zeros(red.shape, dtype=np.float32)
        for band in red, green, blue:
            total += band
        total /= 3

    geos = scale_geometry([shape(geom) for geom, val in shapes(total, mask=mask_setting)], units, dpi)
    if flip:
        geos = [translate(scale(g, 1.0, -1.0, origin=(0, 0))) for g in geos]
    return geos


def flatten_list(obj_list):
    """Yield the leaves of nested image geometry lists."""
    for item in obj_list:
        if hasattr(item, '__iter__') and not isinstance(item, (str, bytes)):
            yield from flatten_list(item)
        else:
            yield item
