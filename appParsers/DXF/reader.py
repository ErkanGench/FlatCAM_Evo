"""
Entry point: DXF document -> flat list of Shapely geometries.
"""
import logging

from .blocks import expand_insert
from .context import ImportContext
from .entities import convert_entity

log = logging.getLogger('base')


def dxf_to_shapes(doc, text_mode='stroke', options=None, kind='geometry'):
    """
    Convert the modelspace of a DXF document to Shapely geometry in WCS 2D.
    The flattening tolerance is 0.01 mm in the drawing units of the document ($INSUNITS;
    unitless drawings count as mm). Invisible entities and entities on off or frozen layers
    are skipped.

    :param doc:         ezdxf Document
    :param text_mode:   'stroke', 'outline' or 'none' for TEXT, ATTRIB and MTEXT;
                        anything else logs a warning and acts as 'stroke'
    :param options:     application options for the circle steps (POINT disks, filled circles); None = the factory
                        defaults
    :param kind:        'gerber' or 'geometry': whose circle preferences are used
    :return:            flat list of Shapely geometries; a bad entity is skipped
    """
    ctx = ImportContext(doc, text_mode, options=options, kind=kind)
    result = []
    for entity in doc.modelspace():
        try:
            if entity.dxftype() == 'INSERT':
                for sub in expand_insert(entity, ctx):
                    result.extend(convert_entity(sub, ctx))
            else:
                result.extend(convert_entity(entity, ctx))
        except Exception as err:
            log.debug("DXF entity skipped: %s" % str(err))
    return result
