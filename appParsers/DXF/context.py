"""
Per-import settings and visibility rules shared by all converters.
"""
import logging

from ezdxf import units as ezunits

log = logging.getLogger('base')

TEXT_MODES = ('stroke', 'outline', 'none')
# Maximum distance between a curve and its flattened version, in millimetres.
TOLERANCE_MM = 0.01
# Drawing unit code of millimetres in $INSUNITS.
UNIT_MM = 4


def unit_tolerance(doc):
    """
    :param doc:     ezdxf Document (or None)
    :return:        0.01 mm expressed in the drawing units of the document ($INSUNITS);
                    unitless or unknown units are taken as millimetres
    """
    try:
        code = int(doc.header.get('$INSUNITS', 0))
        if code in (0, UNIT_MM):
            return TOLERANCE_MM
        factor = ezunits.conversion_factor(UNIT_MM, code)
        return TOLERANCE_MM * factor if factor and factor > 0 else TOLERANCE_MM
    except Exception as err:
        log.debug("DXF $INSUNITS not usable, assuming mm: %s" % str(err))
        return TOLERANCE_MM


class ImportContext:
    """
    Settings of one dxf_to_shapes() call; passed down to every converter (no global state).
    """

    def __init__(self, doc=None, text_mode='stroke', tolerance=None):
        """
        :param doc:         ezdxf Document, used for the layer table and the units
        :param text_mode:   'stroke', 'outline' or 'none'; anything else falls back to 'stroke'
        :param tolerance:   flattening tolerance in drawing units; None = derived from $INSUNITS
        """
        if text_mode not in TEXT_MODES:
            log.warning("DXF import: unknown text mode %r, using 'stroke'." % (text_mode,))
            text_mode = 'stroke'
        self.doc = doc
        self.text_mode = text_mode
        self.tolerance = unit_tolerance(doc) if tolerance is None else tolerance

    def layer_of(self, entity):
        """
        :param entity:  ezdxf entity
        :return:        layer name; entities of a block on layer '0' take the layer of their INSERT
        """
        layer = entity.dxf.get('layer', '0')
        if layer == '0':
            source = getattr(entity, 'source_block_reference', None)
            if source is not None and source is not entity:
                return self.layer_of(source)
        return layer

    def layer_hidden(self, entity):
        """
        :param entity:  ezdxf entity
        :return:        True when its layer is switched off or frozen
        """
        if self.doc is None:
            return False
        name = self.layer_of(entity)
        if name not in self.doc.layers:
            return False
        layer = self.doc.layers.get(name)
        return bool(layer.is_off() or layer.is_frozen())

    def is_visible(self, entity):
        """
        :param entity:  ezdxf entity
        :return:        False for invisible entities (also invisible ATTRIBs) and for entities
                        on an off or frozen layer
        """
        if entity.dxf.get('invisible', 0) == 1:
            return False
        if entity.dxftype() == 'ATTRIB' and getattr(entity, 'is_invisible', False):
            return False
        return not self.layer_hidden(entity)


# A CIRCLE copied out of a block with non-uniform scale comes back as an ELLIPSE without any
# trace of its origin. blocks.py tags such copies with this (otherwise unused) LTSCALE value.
CIRCLE_MARK = 0.0123456789


def is_circle_ellipse(entity):
    """
    :param entity:  ezdxf entity
    :return:        True for an ELLIPSE that blocks.py made out of a CIRCLE
    """
    return (entity.dxftype() == 'ELLIPSE'
            and abs(entity.dxf.get('ltscale', 1.0) - CIRCLE_MARK) < 1e-12)
