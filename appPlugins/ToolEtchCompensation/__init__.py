"""Legacy public imports for the Etch Compensation plugin."""

from appPlugins.ToolEtchCompensation.EtchCompensation import ToolEtchCompensation
from appPlugins.ToolEtchCompensation.EtchCompensationUI import EtchUI
from appPlugins.ToolEtchCompensation.EtchCompensation import (
    AppTool, AppDefaults, VerticalScrollArea, safe_eval, deepcopy, log
)
from appPlugins.ToolEtchCompensation.EtchCompensationUI import (
    QtWidgets, QtCore, QtGui, FCLabel, FCButton, FCFrame, GLay, FCComboBox, FCEntry,
    RadioSet, FCDoubleSpinner, NumericalEvalEntry
)
from appPlugins.ToolEtchCompensation.EtchCompensationGen import math, unary_union
