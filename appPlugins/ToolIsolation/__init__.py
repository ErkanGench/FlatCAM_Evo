"""Isolation plugin and compatibility exports for its former single-file module."""

from appPlugins.ToolIsolation.Isolation import (
    ToolIsolation, IsoUI, QtWidgets, QtCore, QtGui, AppTool, AppDefaults,
    VerticalScrollArea, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCCheckBox,
    FCComboBox2, RadioSet, FCDoubleSpinner, FCSpinner, FCInputDialogSpinnerButton, FCTable,
    OptionalInputSection, logging, deepcopy, Iterable, np, sys, math, shapely,
    LineString, MultiLineString, Polygon, MultiPolygon, Point, LinearRing, unary_union,
    history_of, gettext, fcTranslate, builtins, load_tools_database, tools_database_error_message,
    Geometry, grace, flatten_shapely_geometry, polygon_gap_pairs, outline_area, clip_paths_to_area,
    area_outline_paths, boundary_passes_message, isolation_leftover_paths, milling_orient,
    pass_covers_area, safe_eval, log,
)
from appPlugins.ToolIsolation.IsolationGen import generate_rest_geometry
