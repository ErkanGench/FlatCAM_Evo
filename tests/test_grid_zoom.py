"""Run: .venv/Scripts/python.exe tests/test_grid_zoom.py"""

import unittest

import numpy as np
from vispy.util.quaternion import Quaternion

import test_plotcanvas3d as canvas_tests


class TestGridZoom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        canvas_tests.TestPlotCanvas3d.setUpClass()

    def test_grid_lines_remain_continuous_when_rotated_at_maximum_zoom(self):
        self.check_grid_zoom('MM')

    def test_inch_grid_lines_remain_continuous_at_maximum_zoom(self):
        self.check_grid_zoom('IN')

    def check_grid_zoom(self, units):
        fixture = canvas_tests.TestPlotCanvas3d()
        self.addCleanup(fixture.doCleanups)
        canvas = fixture.make_canvas(units=units)
        canvas.view.bgcolor = 'black'
        canvas.grid._grid_color_fn['color'] = (1, 1, 1, 1)
        canvas.xaxis.visible = False
        canvas.yaxis.visible = False
        canvas.xyz_axis.visible = False
        canvas.workspace_line.visible = False
        camera = canvas.view.camera
        center = canvas.workspace_size[0] / 2
        camera.center = (center, center, 0)
        camera.scale_factor = camera.minimum_scene_size

        for tilt in (0, 30, 50, 70, 110, 150, 180):
            with self.subTest(tilt=tilt):
                camera.set_state(_quaternion=(
                    Quaternion.create_from_axis_angle(-90 + tilt, 1, 0, 0, degrees=True) *
                    Quaternion.create_from_axis_angle(8, 0, 1, 0, degrees=True)
                ))
                image = canvas.render()
                inverse = canvas.grid.get_transform('document', 'visual')
                vectors = inverse.map([(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)])
                plane_vectors = vectors[:2] - vectors[2] * (vectors[:2, 2:3] / vectors[2, 2])
                pixel_size = np.abs(plane_vectors[:, :2]).sum(axis=0)
                # Test the next-brighter decade, away from the minor-line fade threshold.
                spacing = 10 ** (np.floor(np.log10(pixel_size)) + 3)
                for axis in (0, 1):
                    points = np.zeros((2000, 3))
                    points[:, axis] = np.round(center / spacing[axis]) * spacing[axis]
                    radius = camera.minimum_scene_size * 3
                    points[:, 1 - axis] = np.linspace(center - radius, center + radius, len(points))
                    projected = camera._scene_transform.map(points)
                    pixels = np.round(projected[:, :2] / projected[:, 3:] * canvas.pixel_scale).astype(int)
                    pixels = pixels[(pixels[:, 0] > 3) & (pixels[:, 0] < image.shape[1] - 4) &
                                    (pixels[:, 1] > 3) & (pixels[:, 1] < image.shape[0] - 4)]
                    self.assertGreater(len(pixels), 50)
                    hits = np.zeros(len(pixels), dtype=bool)
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            hits |= image[pixels[:, 1] + dy, pixels[:, 0] + dx, :3].max(axis=1) > 30
                    self.assertGreater(hits.mean(), 0.98,
                                       'A grid line must not break into dashes (axis %d, spacing %g)' %
                                       (axis, spacing[axis]))

        camera.set_view('right')
        image = canvas.render()
        self.assertEqual(image[4:-4, 4:-4, :3].max(), 0, 'An edge-on plane must not produce grid artifacts')


if __name__ == '__main__':
    unittest.main()
