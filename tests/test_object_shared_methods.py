"""Methods shared by the object classes. Headless: ShapeCollection is patched, the ObjectUI is a Mock."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from appObjects.GeometryObject import GeometryObject
from appObjects.GerberObject import GerberObject
from tests.helpers_objects import make_app_0b as make_app, no_shape_collection  # noqa: F401,E402


def make_obj(cls):
    app = make_app()
    return cls('obj', app)


def test_random_color_is_an_opaque_rgba_array(no_shape_collection):  # noqa: F811
    obj = make_obj(GerberObject)
    for _ in range(20):
        color = obj.random_color()
        assert isinstance(color, np.ndarray)
        assert color.shape == (4,)
        assert color[3] == 1
        assert np.all((color >= 0) & (color <= 1))


@pytest.mark.parametrize('cls', [GerberObject, GeometryObject])
def test_set_offset_values_writes_the_bounds_centre(cls, no_shape_collection):  # noqa: F811
    obj = make_obj(cls)
    obj.ui = MagicMock()
    obj.app.dec_format = lambda value, decimals: round(value, decimals)
    with patch.object(cls, 'bounds', return_value=(1.0, 2.0, 5.0, 3.0)):
        obj.set_offset_values()
    obj.ui.offsetvector_entry.set_value.assert_called_once_with('(3.0, 2.5)')
