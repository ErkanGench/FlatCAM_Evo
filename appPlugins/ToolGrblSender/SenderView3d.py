# ##########################################################
# FlatCAM Evo: 2D Post-processing for Manufacturing        #
# File by:  Marius Adrian Stanciu (c)                      #
# Date:     10/16/2026                                     #
# License:  MIT Licence                                    #
# ##########################################################

"""The visuals of the GRBL Sender in the Plot 3D tab: toolpath, accepted path, tool marker, height map."""

import numpy as np
from vispy import scene
from vispy.color import Colormap

RAPID_COLOR = (0.55, 0.55, 0.55, 0.6)
CUT_COLOR = (0.10, 0.45, 0.90, 1.0)
# an arc that the sender streams as an arc and the display could not split: drawn as its chord
CHORD_COLOR = (0.35, 0.35, 0.35, 1.0)
ACCEPTED_COLOR = (0.10, 0.70, 0.30, 1.0)
TOOL_COLOR = (0.90, 0.10, 0.10, 1.0)


class SenderView3d:
    def __init__(self, canvas):
        """:param canvas: the PlotCanvas3d of app.plotcanvas3d."""
        self.canvas = canvas
        parent = canvas.view.scene
        self.path = scene.visuals.Line(parent=parent, connect='segments', width=1.5, method='gl')
        self.accepted = scene.visuals.Line(parent=parent, connect='segments', width=2.5, method='gl')
        self.tool = scene.visuals.Markers(parent=parent)
        self.mesh = None
        self.z_scale = 10.0
        self._segments = []

    def set_toolpath(self, segments, chord_lines=()):
        """
        :param segments:    the list of gcode_segment.parse_toolpath(): (stream line index, start, end, rapid).
        :param chord_lines: the stream line indexes whose segment is the chord of an arc that was not split:
                            they are drawn in the grey CHORD_COLOR.
        """
        self._segments = list(segments)
        chord_lines = set(chord_lines)
        if not self._segments:
            self.path.set_data(pos=np.zeros((0, 3), dtype=np.float32))
            self.set_accepted(-1)
            return
        pos = np.array([p for _i, a, b, _r in self._segments for p in (a, b)], dtype=np.float32)
        colors = np.array(
            [c for i, _a, _b, r in self._segments
             for c in ((CHORD_COLOR if i in chord_lines else (RAPID_COLOR if r else CUT_COLOR)),) * 2],
            dtype=np.float32)
        self.path.set_data(pos=pos, color=colors)
        self.set_accepted(-1)

    def set_accepted(self, last_line_index):
        """
        Draw the segments of the lines up to and including `last_line_index` in the accepted color:
        the lines that GRBL accepted. The tool marker shows the real position of the tool.
        """
        accepted = [s for s in self._segments if s[0] <= last_line_index]
        if not accepted:
            self.accepted.set_data(pos=np.zeros((0, 3), dtype=np.float32))
            return
        pos = np.array([p for _i, a, b, _r in accepted for p in (a, b)], dtype=np.float32)
        self.accepted.set_data(pos=pos, color=ACCEPTED_COLOR)

    def set_tool_position(self, xyz):
        self.tool.set_data(pos=np.array([xyz], dtype=np.float32), face_color=TOOL_COLOR, size=10)

    def set_height_map(self, grid_data, z_scale=None):
        """
        :param grid_data: (xs, ys, grid) of build_bilinear_grid(), or None to remove the mesh.
        :param z_scale:   the factor of the height for the display.
        """
        if z_scale is not None:
            self.z_scale = z_scale
        if self.mesh is not None:
            self.mesh.parent = None
            self.mesh = None
        if grid_data is None:
            return
        xs, ys, grid = grid_data
        vertices = np.array([(x, y, grid[j][i] * self.z_scale)
                             for j, y in enumerate(ys) for i, x in enumerate(xs)], dtype=np.float32)
        faces = []
        nx = len(xs)
        for j in range(len(ys) - 1):
            for i in range(nx - 1):
                a = j * nx + i
                faces.append((a, a + 1, a + nx))
                faces.append((a + 1, a + nx + 1, a + nx))
        z = vertices[:, 2]
        span = float(z.max() - z.min()) or 1.0
        cmap = Colormap([(0.13, 0.27, 0.65), (0.19, 0.72, 0.47), (0.84, 0.19, 0.15)])
        colors = cmap.map((z - z.min()) / span)
        self.mesh = scene.visuals.Mesh(vertices=vertices, faces=np.array(faces, dtype=np.uint32),
                                       vertex_colors=colors, parent=self.canvas.view.scene)
        self.mesh.opacity = 0.7

    def clear(self):
        """Remove the visuals from the scene. It is safe to call it more than 1 time."""
        for visual in (self.path, self.accepted, self.tool):
            if visual.parent is not None:
                visual.parent = None
        self.set_height_map(None)
