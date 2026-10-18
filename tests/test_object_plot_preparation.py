"""Shared buffer preparation used by Geometry and Gerber plotting."""
from unittest.mock import patch

import numpy as np
from shapely import LineString
from vispy.color import Color

import appGUI.VisPyVisuals as visuals


def test_repeated_plot_colors_are_parsed_once():
    cached_color = getattr(visuals, '_cached_color_rgba', None)
    if cached_color is not None:
        cached_color.cache_clear()
    with patch.object(visuals, 'Color', wraps=Color) as parse_color:
        for x in range(4):
            data = visuals._update_shape_buffers(dict(
                geometry=LineString([(x, 0), (x + 1, 1)]), color='#1A2B3C4D',
                face_color=None, tolerance=0))
            np.testing.assert_array_equal(data['line_colors'],
                                          np.tile(Color('#1A2B3C4D').rgba, (2, 1)))
        assert parse_color.call_count == 1


def test_ring_segments_accept_numpy_coordinates_and_preserve_closure():
    for coords in ([(0, 0), (2, 0), (1, 1)], [(0, 0), (2, 0), (1, 1), (0, 0)]):
        segments = visuals._linearring_to_segments(np.asarray(coords))
        np.testing.assert_array_equal(segments, [(0, 0), (2, 0), (2, 0), (1, 1), (1, 1), (0, 0)])


def test_lines_and_unhashable_colors_keep_exact_buffer_values():
    geometry = LineString([(0, 0), (1, 2), (3, 4)])
    for color in ([0.1, 0.2, 0.3, 0.4], np.asarray([0.1, 0.2, 0.3, 0.4])):
        data = visuals._update_shape_buffers(dict(geometry=geometry, color=color,
                                                 face_color=None, tolerance=0))
        np.testing.assert_array_equal(data['line_pts'], [(0, 0), (1, 2), (1, 2), (3, 4)])
        np.testing.assert_array_equal(data['line_colors'], np.tile(Color(color).rgba, (4, 1)))
        assert data['line_pts'].dtype == np.float32
