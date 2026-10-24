"""Every project object kind can be constructed.

FlatCAMObj.__init__ forwarded the 'app' keyword to the next class in the MRO. For ScriptObject and DocumentObject
no camlib base follows QObject, so PyQt6 raised "TypeError: 'app' is an unknown keyword argument" and the app could
not create a Script or a Document object.
"""

import pytest

from appObjects.CNCJobObject import CNCJobObject
from appObjects.DocumentObject import DocumentObject
from appObjects.ExcellonObject import ExcellonObject
from appObjects.GeometryObject import GeometryObject
from appObjects.GerberObject import GerberObject
from appObjects.ScriptObject import ScriptObject
from tests.helpers_objects import make_app_0b as make_app, no_shape_collection  # noqa: F401,E402

KINDS = {
    GerberObject: 'gerber', ExcellonObject: 'excellon', GeometryObject: 'geometry', CNCJobObject: 'cncjob',
    ScriptObject: 'script', DocumentObject: 'document',
}


@pytest.mark.parametrize('cls', list(KINDS), ids=lambda c: c.__name__)
def test_object_kind_can_be_constructed(cls, no_shape_collection):  # noqa: F811
    app = make_app()
    obj = cls('obj', app)
    assert obj.kind == KINDS[cls]
    assert obj.obj_options['name'] == 'obj'
    assert obj.app is app


@pytest.mark.parametrize('cls', [ScriptObject, DocumentObject], ids=lambda c: c.__name__)
def test_from_dict_of_an_old_file_without_all_keys(cls, no_shape_collection):  # noqa: F811
    obj = cls('obj', make_app())
    obj.from_dict({'kind': KINDS[cls]})
    assert obj.kind == KINDS[cls]
