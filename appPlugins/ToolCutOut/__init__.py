"""Cutout plugin and compatibility exports for its former single-file module."""

from appParsers.feature_access import fused_solid
from appPlugins.ToolCutOut import CutOutGen
from appPlugins.ToolCutOut.CutOut import CutOut
from appPlugins.ToolCutOut.CutOutUI import CutoutUI
from appPlugins.ToolCutOut.CutOutGen import (
    Contour, CutoutResult, _OPEN_PATH, _closed_loops, _cutout_anchor_points, _cutout_intervals,
    _cutout_paths, _cutout_substring, _geometry_items,
    _manual_gap_geometry, _manual_subtract_selected, _record_width, _rings_of, _sample_path,
    _valid_mouse_bite_step, _validate_thin_depth, offset_contours,
)


def gerber_cutout_geometry(cutout_obj, convex_box):
    """Keep the legacy package-level copper dependency replaceable."""
    return CutOutGen.gerber_cutout_geometry(cutout_obj, convex_box, fused_solid)


def _gerber_items(obj, warnings):
    return CutOutGen._gerber_items(obj, warnings, fused_solid)


def outline_contours(source_geo, convex_box, kind, warnings=None):
    return CutOutGen.outline_contours(source_geo, convex_box, kind, warnings, fused_solid)


def _inner_contour_paths(cutout_obj, kind, cut_dia, margin, gaps, gapsize, convex_box, gap_type, thin_entry,
                         mb_dia, mb_spacing, handler, inner_gaps):
    return CutOutGen._inner_contour_paths(
        cutout_obj, kind, cut_dia, margin, gaps, gapsize, convex_box, gap_type, thin_entry,
        mb_dia, mb_spacing, handler, inner_gaps, fused_solid)


def freeform_cutout_paths(cutout_obj, kind, cut_dia, margin, gaps, gapsize, convex_box, gap_type, thin_entry,
                          mb_dia, mb_spacing, handler, inner_active=False, inner_gaps=False):
    return CutOutGen.freeform_cutout_paths(
        cutout_obj, kind, cut_dia, margin, gaps, gapsize, convex_box, gap_type, thin_entry,
        mb_dia, mb_spacing, handler, inner_active, inner_gaps, fused_solid)
