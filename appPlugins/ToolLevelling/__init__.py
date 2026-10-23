"""Legacy public imports and patch targets for the Levelling plugin."""

from appPlugins.ToolLevelling.LevellingUI import (
    LevelUI, QtWidgets, QtCore, QtGui, FCLabel, FCButton, FCFrame, GLay, FCComboBox,
    build_probe_points_ui, gettext, fcTranslate, builtins
)
from appPlugins.ToolLevelling.Levelling import (
    ToolLevelling, AppTool, AppDefaults, VerticalScrollArea, FCFileSaveDialog,
    logging, log, deepcopy, sys, dt, AppTextEditor, CNCjob, StringIO,
    LevellingCoreMixin, _AlContext, _iter_polygons, VORONOI_ENABLED, MAX_AVOID_TRIES
)
