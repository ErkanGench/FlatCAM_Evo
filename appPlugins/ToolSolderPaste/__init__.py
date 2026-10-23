"""Legacy public imports for the SolderPaste plugin."""

from appPlugins.ToolSolderPaste.SolderPaste import (
    SolderPaste, AppTool, AppDefaults, VerticalScrollArea, FCFileSaveDialog, FCComboBox2,
    FCInputSpinner, traceback, deepcopy, dt, LoudDict, parse_numbers, extract_pads, grace,
    AppTextEditor, StringIO
)
from appPlugins.ToolSolderPaste.SolderPasteUI import (
    SolderUI, QtWidgets, QtCore, QtGui, FCLabel, FCButton, FCFrame, GLay, FCComboBox,
    FCEntry, FCDoubleSpinner, FCSpinner, FCTable, SolderPasteSettings, gettext, fcTranslate, builtins
)
from appPlugins.ToolSolderPaste.SolderPasteGen import pad_paths, parameters, PREFIX
from shapely import LineString, MultiLineString, Polygon, MultiPolygon, Point
import re
