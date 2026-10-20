# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# MIT Licence                                              #
# ##########################################################
"""
The canvas of the headless mode (flatcam.py --headless): no window, no OpenGL context, nothing is drawn.

The application calls the plot canvas, its shape collections and its text groups from many places. NullCanvas accepts
all of these calls. Only the display uses the canvas: a number taken from it (float(), int(), arithmetic, an order
comparison) raises TypeError, so canvas data can never reach a calculation such as G-code unnoticed.
"""


class NullObject:
    """
    Accepts any attribute access and any call and returns a NullObject. It is false in a condition and an empty
    collection (len() 0, iteration gives nothing): the headless mode draws nothing.
    """

    __slots__ = ('_name',)

    def __init__(self, name='null'):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, item):
        if item.startswith('__') and item.endswith('__'):
            raise AttributeError(item)
        return NullObject('%s.%s' % (self._name, item))

    def __setattr__(self, key, value):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __repr__(self):
        return '<NullObject %s>' % self._name

    def _no_number(self, *args):
        raise TypeError("the headless canvas has no data: %s" % self._name)

    __int__ = __float__ = __index__ = __round__ = _no_number
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _no_number
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = __neg__ = __abs__ = _no_number
    __lt__ = __le__ = __gt__ = __ge__ = _no_number


class NullCanvas(NullObject):
    """The plot canvas of the headless mode. It has the factory methods of PlotCanvas; all of them draw nothing."""

    __slots__ = ()

    def __init__(self, app=None):
        NullObject.__init__(self, 'plotcanvas')

    def new_shape_collection(self, **kwargs):
        return NullObject('shape_collection')

    def new_shape_group(self, shape_collection=None):
        return NullObject('shape_group')

    def new_text_collection(self, **kwargs):
        return NullObject('text_collection')

    def new_text_group(self, collection=None):
        return NullObject('text_group')

    def new_cursor(self, big=None):
        return NullObject('cursor')
