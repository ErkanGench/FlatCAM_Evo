"""Presentation for the canvas-only Move command."""

from PyQt6 import QtWidgets


class MoveUI:

    def __init__(self, tool):
        tool.layout.setContentsMargins(0, 0, 3, 0)
        tool.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Maximum)

    @staticmethod
    def draw_shape(shapes, shape):
        face = '#0000FF' + str(hex(int(0.2 * 255)))[2:]
        outline = '#0000FFAF'
        shapes.add(shape, color=outline, face_color=face, update=False, layer=0, tolerance=None)
