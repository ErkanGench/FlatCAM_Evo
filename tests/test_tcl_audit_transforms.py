"""Multi-object commands validate their full input before changing any object."""
from unittest.mock import Mock

import pytest

from tclCommands.TclCommandMirror import TclCommandMirror
from tclCommands.TclCommandOffset import TclCommandOffset
from tclCommands.TclCommandScale import TclCommandScale
from tclCommands.TclCommandSkew import TclCommandSkew
from tclCommands.TclCommandPlotObjects import TclCommandPlotObjects
from test_tcl_audit_regressions import object_app, FCShell


@pytest.mark.parametrize('cls,args,method', [
    (TclCommandMirror, {'axis': 'X'}, 'mirror'),
    (TclCommandOffset, {'x': 1}, 'offset'),
    (TclCommandScale, {'factor': 2}, 'scale'),
    (TclCommandSkew, {'x': 5}, 'skew')])
def test_unsupported_later_target_does_not_partially_transform(cls, args, method):
    first = Mock(kind='geometry', obj_options={})
    first.bounds.return_value = (0, 0, 1, 1)
    second = Mock(kind='cncjob')
    second.bounds.return_value = (0, 0, 1, 1)
    app = object_app(first)
    app.collection.get_by_name.side_effect = lambda n: {'a': first, 'b': second}.get(n)
    try:
        cls(app).execute(args, ['a', 'b'])
    except FCShell.TclErrorException:
        pass
    getattr(first, method).assert_not_called()


def test_invalid_mirror_axis_is_rejected_before_mutation():
    obj = Mock(kind='geometry', obj_options={})
    obj.bounds.return_value = (0, 0, 1, 1)
    with pytest.raises(FCShell.TclErrorException):
        TclCommandMirror(object_app(obj)).execute({'axis': 'invalid'}, ['a'])
    obj.mirror.assert_not_called()


def test_single_object_origin_refreshes_bounds_source_and_dirty_state():
    from tclCommands.TclCommandSetOrigin import TclCommandSetOrigin
    obj = Mock(kind='geometry', obj_options={})
    obj.bounds.return_value = (1, 2, 3, 4)
    app = object_app(obj)
    app.app_obj = Mock()
    TclCommandSetOrigin(app).execute({'loc': '4,8', 'obj_name': 'g'}, [])
    obj.offset.assert_called_once_with((3, 6))
    obj.regenerate_source.assert_called_once_with()
    app.app_obj.object_changed.emit.assert_called_once_with(obj)
    assert app.should_we_save is True
    assert obj.obj_options['xmin'] == 1
    assert '3.0000, 6.0000' in app.inform_shell.emit.call_args.args[0]

