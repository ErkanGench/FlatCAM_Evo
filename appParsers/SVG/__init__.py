"""Clean-room SVG to Shapely importer."""
from .errors import SvgImportError
from .reader import svg_to_shapes

__all__ = ['SvgImportError', 'svg_to_shapes']
