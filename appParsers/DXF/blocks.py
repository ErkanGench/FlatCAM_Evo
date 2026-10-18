"""
INSERT (block reference) expansion, including MINSERT arrays and nested blocks.
"""
import logging

from .context import CIRCLE_MARK

log = logging.getLogger('base')

# internal ezdxf API; without it, circles in non-uniformly scaled blocks import as outlines
try:
    from ezdxf.entities.copy import CopySettings, CopyStrategy
    from ezdxf.entities.insert import virtual_block_reference_entities
    HAS_COPY_STRATEGY = True
except ImportError:
    CopySettings = CopyStrategy = object
    virtual_block_reference_entities = None
    HAS_COPY_STRATEGY = False

MAX_NESTING = 16


class CircleMarkingCopy(CopyStrategy):
    """
    Copy strategy that tags CIRCLE copies, so that a circle which ezdxf turns into an ELLIPSE
    (non-uniform scale) can still be recognised and stay a filled disk.
    """

    def copy(self, entity):
        """
        :param entity:  entity of the block definition
        :return:        its copy; copies of CIRCLEs carry CIRCLE_MARK as LTSCALE
        """
        clone = super().copy(entity)
        if entity.dxftype() == 'CIRCLE':
            clone.dxf.ltscale = CIRCLE_MARK
        return clone


def _block_entities(insert):
    """
    :param insert:  ezdxf INSERT entity (no MINSERT array)
    :return:        list of the transformed block content, circles tagged
    """
    if not HAS_COPY_STRATEGY:
        return list(insert.virtual_entities())
    entities = []
    strategy = CircleMarkingCopy(CopySettings())
    for entity in virtual_block_reference_entities(insert, copy_strategy=strategy):
        entity.set_source_block_reference(insert)
        entities.append(entity)
    return entities


def expand_insert(insert, ctx=None, depth=0):
    """
    Resolve a block reference into plain (virtual) entities, recursing into nested INSERTs.
    Scale, mirroring, rotation, extrusion and MINSERT arrays are applied by ezdxf.

    :param insert:  ezdxf INSERT entity
    :param ctx:     ImportContext; invisible INSERTs and INSERTs on hidden layers yield nothing
    :param depth:   current nesting level
    :return:        generator of non-INSERT ezdxf entities in WCS
    """
    if depth > MAX_NESTING:
        log.debug("DXF block nesting too deep, skipped.")
        return
    if ctx is not None and not ctx.is_visible(insert):
        return
    try:
        if insert.mcount > 1:
            # MINSERT array: ezdxf splits it into one single INSERT per cell
            virtual = list(insert.multi_insert())
        else:
            virtual = _block_entities(insert)
            virtual.extend(insert.attribs)
    except Exception as err:
        log.debug("DXF INSERT skipped: %s" % str(err))
        return
    for entity in virtual:
        if entity.dxftype() == 'INSERT':
            yield from expand_insert(entity, ctx, depth + 1)
        else:
            yield entity
