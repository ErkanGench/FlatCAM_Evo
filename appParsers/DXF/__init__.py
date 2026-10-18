"""
Clean DXF importer: ezdxf document -> Shapely geometries.
"""
from .reader import dxf_to_shapes
from .text import text_entity_to_shapes, TEXT_RENDERING_AVAILABLE

__all__ = ['dxf_to_shapes', 'text_entity_to_shapes', 'TEXT_RENDERING_AVAILABLE']
