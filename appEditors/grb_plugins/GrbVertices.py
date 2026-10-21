"""
Vertex editing of 1 Gerber record: the grips on the canvas and the Edit vertices dialog.

A region edits the vertices of its 'solid'. A track (circular aperture, FOLLOW line) edits its 'follow' and makes the
'solid' again with the radius and the steps that give the current solid (sweep_parameters). A flash has no vertices.
"""

import gettext
import builtins

from PyQt6 import QtWidgets
from shapely import LineString, LinearRing, Polygon
from shapely.errors import GEOSException

from appEditors.vertex_ops import vertex_address, edit_vertex, check_vertex_result, parts_of, rings_of, \
    DEFAULT_CIRCLE_STEPS
from appEditors.grb_plugins.GrbCommon import DrawToolShape
from appEditors.grb_plugins.GrbHistory import gerber_operation
from appEditors.grb_plugins.GrbFollowPlugin import selected_entries, commit, edit_state
from appEditors.grb_plugins.GrbTrackBend import scene_state, sweep_parameters
from appGUI.GUIElements import FCLabel, GLay, FCButton, FCEntry
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


def vertex_plan(editor, shape):
    """
    :return: (kind, geometry, parameters), or None for a shape without vertices (a flash). kind is 'region' (geometry
             is the solid polygon) or 'track' (geometry is the FOLLOW line, parameters are (radius, steps)).
    :raises ValueError: the shape cannot be edited by its vertices
    """
    editor.get_pick_index()
    apertures = editor._shape_apertures.get(shape)
    if not apertures or len(apertures) != 1 or next(iter(apertures)) not in editor.storage_dict:
        raise ValueError(_("The selected shape changed. Select it again."))
    aperture = editor.storage_dict[next(iter(apertures))]
    follow, solid = shape.geo.get('follow'), shape.geo.get('solid')
    kind = aperture.get('type')
    # a track is a line in a circular aperture; every other record with a polygon outline is a region
    if kind == 'REG' or isinstance(follow, Polygon) or (isinstance(follow, LinearRing) and kind != 'C'):
        if not isinstance(solid, Polygon) or solid.is_empty:
            raise ValueError(_("Only a polygon region has editable vertices."))
        return 'region', solid, None
    if not isinstance(follow, LineString) or follow.is_empty:
        return None
    return 'track', follow, sweep_parameters(editor, aperture, shape)


def grip_geometry(editor, shape):
    """The geometry that carries the grips of shape, None if it has none."""
    plan = vertex_plan(editor, shape)
    return None if plan is None else plan[1]


def grip_state(editor):
    """What a grip drag compares before it commits."""
    return editor.history.session, editor.geometry_revision, scene_state(editor)


def rebuild(kind, shape, geometry, parameters):
    """The geometry dict of shape for the edited vertex geometry."""
    if kind == 'region':
        if geometry.geom_type != 'Polygon':
            raise ValueError(_("The edit would create invalid geometry."))
        # the FOLLOW of a region is its exterior, in the form that the shape already has
        follow = shape.geo.get('follow')
        if isinstance(follow, Polygon):
            return dict(shape.geo, solid=geometry, follow=geometry)
        if isinstance(follow, LinearRing):
            return dict(shape.geo, solid=geometry, follow=geometry.exterior)
        if follow is not None:
            return dict(shape.geo, solid=geometry, follow=LineString(geometry.exterior.coords))
        return dict(shape.geo, solid=geometry)
    radius, steps = parameters
    if geometry.is_closed:
        raise ValueError(_("The edit would close the track."))
    solid = geometry.buffer(radius, steps)
    if solid.is_empty or not solid.is_valid:
        raise ValueError(_("The edit would create invalid geometry."))
    return dict(shape.geo, follow=geometry, solid=solid)


@gerber_operation(_('Edit vertices'))
def apply_vertex_edit(editor, action, index, point=None, target=None, on_segment=True):
    """
    1 call is 1 history step.

    :param action:      'move', 'insert', 'remove' or an arc action of vertex_ops.ARC_ACTIONS
    :param index:       a vertex index of a single contour, or a (part, ring, index) / (part, ring, start, end) address
    :param target:      the shape that the caller edits; the edit fails if another shape is selected
    :param on_segment:  True (the dialog): an inserted vertex must lie inside the chosen segment
    """
    try:
        before = edit_state(editor)
        entries = selected_entries(editor) if editor.selected else []
        if len(entries) != 1:
            raise ValueError(_("Select exactly one shape to edit vertices."))
        apid, position, shape = entries[0]
        if target is not None and shape is not target:
            raise ValueError(_("The selected shape changed. Reopen the vertex editor."))
        plan = vertex_plan(editor, shape)
        if plan is None:
            raise ValueError(_("A flashed pad has no vertices. Use Move to move it."))
        kind, geometry, parameters = plan
        address = vertex_address(geometry, index)
        steps = editor.app.options.get('gerber_circle_steps', DEFAULT_CIRCLE_STEPS)
        result_geo = edit_vertex(geometry, action, address, point, on_segment=on_segment, steps=steps)
        check_vertex_result(result_geo, address)
        if result_geo.equals_exact(geometry, 0.0):
            return
        result = DrawToolShape(rebuild(kind, shape, result_geo, parameters))
        if edit_state(editor) != before:
            raise ValueError(_("Geometry or selection changed during the operation. Select the shape again."))
    except (ValueError, TypeError, OverflowError, GEOSException) as err:
        editor.app.inform.emit('[WARNING_NOTCL] %s' % str(err))
        return 'fail'
    if kind == 'track':
        editor.history.native_shapes.add(result)
    commit(editor, {apid: {position: [result]}}, [result])


def edit_vertices_dialog(editor):
    """The numeric Edit vertices dialog of the selected shape."""
    if not editor.history.ready():
        return 'fail'
    try:
        if len(editor.selected) != 1:
            raise ValueError(_("Select exactly one shape to edit vertices."))
        target = editor.selected[0]
        if vertex_plan(editor, target) is None:
            raise ValueError(_("A flashed pad has no vertices. Use Move to move it."))
    except ValueError as err:
        editor.app.inform.emit('[WARNING_NOTCL] %s' % str(err))
        return 'fail'

    dialog = QtWidgets.QDialog(editor.ui.grb_edit_widget)
    dialog.setWindowTitle(_("Edit vertices"))
    grid = GLay(v_spacing=5, h_spacing=3)
    dialog.setLayout(grid)
    hint = FCLabel(_("Indexes start at 0. A region edits its solid: ring 0 is the exterior; rings 1+ are the holes.\n"
                     "A track edits its FOLLOW line.\n"
                     "Insert uses the segment from index to index + 1.\n"
                     "The closing coordinate is an alias of vertex 0."))
    grid.addWidget(hint, 0, 0, 1, 2)
    part_entry, ring_entry, index_entry = QtWidgets.QSpinBox(), QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
    part_entry.setObjectName('vertex_part')
    ring_entry.setObjectName('vertex_ring')
    index_entry.setObjectName('vertex_index')
    x_entry, y_entry = FCEntry(), FCEntry()
    x_entry.setObjectName('vertex_x')
    y_entry.setObjectName('vertex_y')
    action_entry = QtWidgets.QComboBox()
    for label, action in [(_("Move"), 'move'), (_("Insert"), 'insert'), (_("Remove"), 'remove')]:
        action_entry.addItem(label, action)
    for row, (label, widget) in enumerate([(_("Part"), part_entry), (_("Ring"), ring_entry),
                                            (_("Vertex / segment index"), index_entry),
                                            ('X', x_entry), ('Y', y_entry),
                                            (_("Operation"), action_entry)], 1):
        grid.addWidget(FCLabel(label), row, 0)
        grid.addWidget(widget, row, 1)
    apply_btn, close_btn = FCButton(_("Apply")), FCButton(_("Close"))
    apply_btn.setObjectName('vertex_apply')
    grid.addWidget(apply_btn, 7, 0)
    grid.addWidget(close_btn, 7, 1)

    def load_vertex():
        try:
            geometry = vertex_plan(editor, target)[1]
        except (ValueError, TypeError):
            dialog.reject()
            return
        parts = parts_of(geometry)
        part_entry.setMaximum(len(parts) - 1)
        rings = rings_of(parts[part_entry.value()])
        ring_entry.setMaximum(len(rings) - 1)
        coords = list(rings[ring_entry.value()].coords)
        index_entry.setMaximum(len(coords) - 1)
        x_entry.setText(str(coords[index_entry.value()][0]))
        y_entry.setText(str(coords[index_entry.value()][1]))

    def apply():
        nonlocal target
        address = (part_entry.value(), ring_entry.value(), index_entry.value())
        if editor.apply_vertex_edit(action_entry.currentData(), address,
                                    (x_entry.text(), y_entry.text()), target=target) == 'fail':
            return
        target = editor.selected[0]
        load_vertex()

    def change_action():
        for entry in (x_entry, y_entry):
            entry.setEnabled(action_entry.currentData() != 'remove')

    index_entry.valueChanged.connect(load_vertex)
    part_entry.valueChanged.connect(load_vertex)
    ring_entry.valueChanged.connect(load_vertex)
    action_entry.currentIndexChanged.connect(change_action)
    apply_btn.clicked.connect(apply)
    close_btn.clicked.connect(dialog.reject)
    load_vertex()
    dialog.exec()
    dialog.deleteLater()
