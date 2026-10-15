import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vispy.visuals import TextVisual
from vispy.visuals.transforms import MatrixTransform, STTransform

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appGUI.VisPyVisuals import TextCollectionVisual


class TestAnnotationZoom(unittest.TestCase):
    def test_annotation_shrinks_with_zoom_without_changing_configured_size(self):
        collection = TextCollectionVisual()
        collection.transforms.dpi = 96
        collection.add(['1'], [(10, 20)], font_size=12)
        transform = STTransform(scale=(10, 10, 10))
        view = SimpleNamespace(transforms=SimpleNamespace(get_transform=lambda *args: transform))

        def prepare_draw(visual, unused_view):
            visual.shared_program['u_npix'] = visual.font_size / 72. * visual.transforms.dpi

        # GPU glyph preparation needs an OpenGL context; exercise real transforms and uniforms here.
        with patch.object(TextVisual, '_prepare_draw', prepare_draw):
            collection._prepare_draw(view)
            initial_size = collection.shared_program['u_npix']
            transform.scale = (5, 5, 5)
            collection._prepare_draw(view)
            self.assertAlmostEqual(collection.shared_program['u_npix'], initial_size / 2)

            # Panning and rebuilding annotations must preserve their zoom scale.
            transform.translate = (100, 200, 0)
            collection.clear()
            collection.add(['2'], [(30, 40)], font_size=12)
            collection._prepare_draw(view)
            self.assertAlmostEqual(collection.shared_program['u_npix'], initial_size / 2)

            rotation = MatrixTransform()
            rotation.rotate(45, (1, 1, 0))
            rotated_transform = transform * rotation
            view.transforms.get_transform = lambda *args: rotated_transform
            collection._prepare_draw(view)
            self.assertAlmostEqual(collection.shared_program['u_npix'], initial_size / 2, places=5)

            view.transforms.get_transform = lambda *args: transform
            transform.scale = (20, 20, 20)
            collection._prepare_draw(view)
            self.assertAlmostEqual(collection.shared_program['u_npix'], initial_size)
            self.assertEqual(collection.font_size, 12)
            self.assertEqual(collection.data[1]['font_size'], 12)


if __name__ == '__main__':
    unittest.main()
