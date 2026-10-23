"""Legacy public imports for the QRCode plugin."""

from appPlugins.ToolQRCode.QRCode import (
    QRCode, AppTool, AppDefaults, VerticalScrollArea, FCFileSaveDialog,
    history_of, svg_to_shapes, SvgImportError, logging, log, StringIO, BytesIO,
    gettext, fcTranslate, builtins
)
from appPlugins.ToolQRCode.QRCodeUI import (
    QRcodeUI, QtWidgets, QtCore, QtGui, Qt, FCLabel, FCButton, FCFrame, GLay, FCComboBox,
    FCCheckBox, RadioSet, FCTextArea, FCSpinner, FCEntry
)
from appPlugins.ToolQRCode.QRCodeGen import (
    deepcopy, Iterable, math, MultiPolygon, box, Polygon, unary_union, translate, qrcode
)
