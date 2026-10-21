from PyQt6 import QtCore, QtGui, QtWidgets

import builtins
import gettext
import sys
from weakref import WeakSet
import appTranslation as fcTranslate

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class WindowResizeHandle(QtWidgets.QWidget):
    """Let Qt's window manager resize first; support platforms without that API."""

    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.start_position = None
        self.start_geometry = None
        self.setCursor(cursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized() or window.isFullScreen():
                return
            if not window.windowHandle().startSystemResize(self.edges):
                self.start_position = event.globalPosition().toPoint()
                self.start_geometry = window.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.start_position is None:
            return
        window = self.window()
        delta = event.globalPosition().toPoint() - self.start_position
        left = bool(self.edges & QtCore.Qt.Edge.LeftEdge)
        right = bool(self.edges & QtCore.Qt.Edge.RightEdge)
        top = bool(self.edges & QtCore.Qt.Edge.TopEdge)
        bottom = bool(self.edges & QtCore.Qt.Edge.BottomEdge)
        minimum = window.minimumSize().expandedTo(window.minimumSizeHint())
        maximum = window.maximumSize()
        width = self.start_geometry.width() + (-delta.x() if left else delta.x() if right else 0)
        height = self.start_geometry.height() + (-delta.y() if top else delta.y() if bottom else 0)
        width = min(max(width, minimum.width()), maximum.width())
        height = min(max(height, minimum.height()), maximum.height())
        x = self.start_geometry.right() - width + 1 if left else self.start_geometry.x()
        y = self.start_geometry.bottom() - height + 1 if top else self.start_geometry.y()
        window.setGeometry(x, y, width, height)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.start_position = None
        self.start_geometry = None
        event.accept()


class WindowControlButton(QtWidgets.QToolButton):
    """Monochrome caption glyphs follow the current window's text palette."""

    def __init__(self, control, parent):
        super().__init__(parent)
        self.control = control

    def paintEvent(self, event):
        super().paintEvent(event)
        color = self.palette().color(QtGui.QPalette.ColorRole.ButtonText)
        if self.control == 'close' and self.underMouse() and self.isEnabled():
            color = QtGui.QColor('white')
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QPen(color, 1.0))
        painter.translate(self.width() / 2, self.height() / 2)
        scale = self.iconSize().width() / 16.0
        painter.scale(scale, scale)
        x = -4.5
        y = -4.5
        if self.control == 'minimize':
            painter.drawLine(QtCore.QPointF(x, y + 5), QtCore.QPointF(x + 9, y + 5))
        elif self.control == 'close':
            painter.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x + 9, y + 9))
            painter.drawLine(QtCore.QPointF(x + 9, y), QtCore.QPointF(x, y + 9))
        elif self.window().isMaximized():
            painter.drawPolyline(QtGui.QPolygonF([
                QtCore.QPointF(x + 3, y + 2), QtCore.QPointF(x + 3, y),
                QtCore.QPointF(x + 9, y), QtCore.QPointF(x + 9, y + 6),
                QtCore.QPointF(x + 7, y + 6)]))
            painter.drawRect(QtCore.QRectF(x, y + 3, 6, 6))
        else:
            painter.drawRect(QtCore.QRectF(x, y, 9, 9))


class MenuButton(QtWidgets.QToolButton):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.ButtonText), 0.8))
        x = (self.width() - 16) / 2
        y = (self.height() - 12) / 2
        for index in range(4):
            offset = y + index * 4
            painter.drawLine(QtCore.QPointF(x, offset), QtCore.QPointF(x + 16, offset))


class NotebookButton(QtWidgets.QToolButton):
    def paintEvent(self, event):
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QtGui.QIcon()
        option.text = ''
        painter = QtWidgets.QStylePainter(self)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ToolButton, option)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = self.palette().color(QtGui.QPalette.ColorRole.ButtonText)
        painter.setPen(QtGui.QPen(color, 0.8))
        x = (self.width() - 16) / 2
        y = (self.height() - 14) / 2
        painter.drawRect(QtCore.QRectF(x, y, 16, 14))
        painter.fillRect(QtCore.QRectF(x + 0.4, y + 0.4, 5, 13.2), color)


class TitleBar(QtWidgets.QWidget):
    """Project title, existing application menus and portable window controls."""

    def __init__(self, window, menu, notebook_action, history_actions=()):
        super().__init__(window)
        self.menu = menu
        self.project_title = None
        self.connected_menus = WeakSet()
        self.move_position = None
        self.move_geometry = None
        self.setObjectName('title_bar')
        window.setWindowFlags(window.windowFlags() | QtCore.Qt.WindowType.FramelessWindowHint)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 0)
        layout.setSpacing(2)
        self.setMinimumHeight(34)
        self.setStyleSheet("""
            QWidget#title_bar QToolButton {
                padding: 0px; margin: 0px; border: 0px; min-height: 0px; min-width: 0px;
            }
            QWidget#title_bar > QToolButton { min-width: 32px; max-width: 32px; }
            QWidget#title_bar WindowControlButton { min-width: 46px; max-width: 46px; }
            QWidget#title_bar QToolButton:hover { background-color: rgba(127, 127, 127, 0.2); }
            QWidget#title_bar QToolButton#title_close:hover { background-color: #c42b1c; }
            QMenuBar#title_menu { padding: 0px; margin: 0px; border: 0px; background: transparent; }
            QMenuBar#title_menu::item { padding: 0px 6px; }
            QToolBar#title_toolbar { padding: 0px; margin: 0px; border: 0px; spacing: 4px; }
            QToolBar#title_toolbar QToolButton { padding: 4px; }
        """)

        self.icon_button = QtWidgets.QToolButton(self)
        self.icon_button.setIcon(window.windowIcon())
        self.icon_button.setToolTip(_('Window'))
        self.icon_button.setAccessibleName(_('Window menu'))
        self.icon_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.system_menu = QtWidgets.QMenu(self.icon_button)
        self.restore_action = self.system_menu.addAction(_('Restore'), window.showNormal)
        self.minimize_action = self.system_menu.addAction(_('Minimize'), window.showMinimized)
        self.maximize_action = self.system_menu.addAction(_('Maximize'), window.showMaximized)
        self.system_menu.addSeparator()
        self.close_action = self.system_menu.addAction(_('Close'), window.close)
        self.icon_button.setMenu(self.system_menu)
        layout.addWidget(self.icon_button)

        menu.removeAction(notebook_action)
        self.notebook_button = NotebookButton(self)
        self.notebook_button.setDefaultAction(notebook_action)
        layout.addWidget(self.notebook_button)

        # Undo / Redo of the app history, just before the main menu button
        self.history_buttons = []
        for action in history_actions:
            button = QtWidgets.QToolButton(self)
            button.setDefaultAction(action)
            button.setAccessibleName(action.text())
            layout.addWidget(button)
            self.history_buttons.append(button)

        self.menu_button = MenuButton(self)
        self.menu_button.setToolTip(_('Main menu'))
        self.menu_button.setAccessibleName(_('Main menu'))
        self.menu_button.clicked.connect(self.expand_menu)
        layout.addWidget(self.menu_button)

        menu.setNativeMenuBar(False)
        menu.setObjectName('title_menu')
        menu.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        layout.addWidget(menu, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        menu.hide()
        menu.triggered.connect(self.collapse_menu)

        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.title_label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addStretch(1)

        self.toolbar = QtWidgets.QToolBar(self)
        self.toolbar.setObjectName('title_toolbar')
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QtCore.QSize(16, 16))
        self.toolbar.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Ignored)
        layout.addWidget(self.toolbar)

        self.minimize_button = WindowControlButton('minimize', self)
        self.minimize_button.setToolTip(_('Minimize'))
        self.minimize_button.setAccessibleName(_('Minimize'))
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button = WindowControlButton('maximize', self)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button = WindowControlButton('close', self)
        self.close_button.setObjectName('title_close')
        self.close_button.setToolTip(_('Close'))
        self.close_button.setAccessibleName(_('Close'))
        self.close_button.clicked.connect(window.close)
        for button in (self.icon_button, self.notebook_button, *self.history_buttons, self.menu_button,
                       self.minimize_button, self.maximize_button, self.close_button):
            button.setMinimumSize(30, 26)
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Ignored)
            button.setIconSize(QtCore.QSize(16, 16))
        window_controls = QtWidgets.QHBoxLayout()
        window_controls.setContentsMargins(0, 0, 0, 0)
        window_controls.setSpacing(0)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedWidth(46)
            window_controls.addWidget(button)
        layout.addLayout(window_controls)

        edge = QtCore.Qt.Edge
        cursor = QtCore.Qt.CursorShape
        self.resize_handles = {}
        for edges, shape in (
                (edge.LeftEdge, cursor.SizeHorCursor), (edge.RightEdge, cursor.SizeHorCursor),
                (edge.TopEdge, cursor.SizeVerCursor), (edge.BottomEdge, cursor.SizeVerCursor),
                (edge.TopEdge | edge.LeftEdge, cursor.SizeFDiagCursor),
                (edge.BottomEdge | edge.RightEdge, cursor.SizeFDiagCursor),
                (edge.TopEdge | edge.RightEdge, cursor.SizeBDiagCursor),
                (edge.BottomEdge | edge.LeftEdge, cursor.SizeBDiagCursor)):
            self.resize_handles[edges] = WindowResizeHandle(window, edges, shape)

        window.windowTitleChanged.connect(self.update_title)
        window.windowIconChanged.connect(self.icon_button.setIcon)
        self.resize_timer = QtCore.QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.update_resize_handles)
        self.resize_timer.timeout.connect(self.update_title)
        self.update_menu_font()
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.update_title()
        self.update_window_state()

    def update_title(self):
        # Symmetric bounds keep the text centered on the window, not the remaining space.
        left_widget = self.menu_button if self.menu.isHidden() else self.menu
        right_widget = self.minimize_button if self.toolbar.isHidden() else self.toolbar
        spacing = self.layout().spacing()
        margin = max(left_widget.geometry().right() + 1 + spacing,
                     self.width() - right_widget.x() + spacing)
        width = max(0, self.width() - 2 * margin)
        margins = self.layout().contentsMargins()
        self.title_label.setGeometry((self.width() - width) // 2, margins.top(), width,
                                     max(0, self.height() - margins.top() - margins.bottom()))
        title = self.project_title or self.window().windowTitle() or _('Untitled')
        title = '%s %s' % (_('Project:'), title)
        self.title_label.setToolTip(title)
        self.title_label.setText(self.title_label.fontMetrics().elidedText(
            title, QtCore.Qt.TextElideMode.ElideMiddle, self.title_label.contentsRect().width()))

    def update_menu_font(self):
        general_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        title_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.TitleFont)
        for widget, selector, font in (
                (self.menu, 'QMenuBar, QMenu', general_font),
                (self.system_menu, 'QMenu', general_font),
                (self.menu_button, 'QToolButton', general_font),
                (self.title_label, 'QLabel', title_font)):
            size = font.pointSizeF()
            unit = 'pt'
            if size <= 0:
                size = font.pixelSize()
                unit = 'px'
            widget.setFont(font)
            widget.setStyleSheet(
                '%s { font-family: "%s"; font-size: %.2f%s; font-weight: %d; icon-size: 16px; }' %
                (selector, font.family(), size, unit, font.weight()))
        self.setMinimumHeight(max(34, self.title_label.sizeHint().height() + 5))
        self.update_title()

    def update_native_corners(self):
        if sys.platform != 'win32' or not self.window().effectiveWinId():
            return
        import ctypes
        from ctypes import wintypes

        # Older Windows versions ignore the Windows 11 rounded-corner preference.
        flat = self.window().isMaximized() or self.window().isFullScreen()
        handle = wintypes.HWND(int(self.window().effectiveWinId()))
        preference = ctypes.c_int(1 if flat else 2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, 33,
            ctypes.byref(preference), ctypes.sizeof(preference))
        # DWMWA_BORDER_COLOR: COLOR_NONE when maximized, COLOR_DEFAULT when restored.
        border = ctypes.c_uint32(0xfffffffe if flat else 0xffffffff)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            handle, 34, ctypes.byref(border), ctypes.sizeof(border))

    def expand_menu(self):
        for menu in self.menus():
            if menu not in self.connected_menus:
                menu.triggered.connect(self.collapse_menu)
                self.connected_menus.add(menu)
        self.menu_button.hide()
        self.menu.show()

    def menus(self):
        pending = self.menu.findChildren(QtWidgets.QMenu)
        pending.extend(action.menu() for action in self.menu.actions() if action.menu() is not None)
        seen = set()
        while pending:
            menu = pending.pop()
            if menu in seen:
                continue
            seen.add(menu)
            yield menu
            pending.extend(action.menu() for action in menu.actions() if action.menu() is not None)

    def collapse_menu(self):
        if self.menu.isHidden():
            return
        for menu in self.menus():
            menu.close()
        self.menu.setActiveAction(None)
        self.menu.hide()
        self.menu_button.show()

    def toggle_maximized(self):
        if self.window().isMaximized():
            self.window().showNormal()
        else:
            self.window().showMaximized()

    def update_window_state(self):
        window = self.window()
        maximized = window.isMaximized()
        fullscreen = window.isFullScreen()
        self.setVisible(not fullscreen)
        self.restore_action.setEnabled(maximized or fullscreen or window.isMinimized())
        self.minimize_action.setEnabled(not window.isMinimized())
        self.maximize_action.setEnabled(not maximized and not fullscreen)
        self.maximize_button.setToolTip(_('Restore') if maximized else _('Maximize'))
        self.maximize_button.setAccessibleName(self.maximize_button.toolTip())
        self.maximize_button.update()
        self.update_native_corners()
        if fullscreen:
            self.collapse_menu()
        self.update_resize_handles()

    def update_resize_handles(self):
        window = self.window()
        width, height = window.size().width(), window.size().height()
        border = 5
        corner = 10
        edge = QtCore.Qt.Edge
        for edges, handle in self.resize_handles.items():
            horizontal = bool(edges & (edge.LeftEdge | edge.RightEdge))
            vertical = bool(edges & (edge.TopEdge | edge.BottomEdge))
            if horizontal and vertical:
                x = 0 if edges & edge.LeftEdge else width - corner
                y = 0 if edges & edge.TopEdge else height - corner
                handle.setGeometry(x, y, corner, corner)
            elif horizontal:
                x = 0 if edges & edge.LeftEdge else width - border
                handle.setGeometry(x, corner, border, max(0, height - 2 * corner))
            else:
                y = 0 if edges & edge.TopEdge else height - border
                handle.setGeometry(corner, y, max(0, width - 2 * corner), border)
            handle.setVisible(window.isVisible() and not window.isMaximized() and not window.isFullScreen())
            handle.raise_()

    def eventFilter(self, obj, event):
        event_type = event.type()
        if obj is self.window():
            if event_type in (QtCore.QEvent.Type.WindowStateChange, QtCore.QEvent.Type.Show,
                              QtCore.QEvent.Type.StyleChange):
                self.update_window_state()
                self.resize_timer.start(0)
            elif event_type == QtCore.QEvent.Type.Resize:
                self.update_resize_handles()
                self.resize_timer.start(0)
            elif event_type in (QtCore.QEvent.Type.LayoutRequest, QtCore.QEvent.Type.ChildAdded):
                # QMainWindow may stack newly added docks/status widgets above the handles.
                self.resize_timer.start(0)
            elif event_type == QtCore.QEvent.Type.WinIdChange:
                self.update_native_corners()
            elif event_type == QtCore.QEvent.Type.WindowDeactivate and not self.menu.isHidden():
                self.collapse_menu()
        if obj is self.title_label and event_type == QtCore.QEvent.Type.Resize:
            self.update_title()
        if obj in (self.menu, self.menu_button, self.toolbar, self.minimize_button) and event_type in (
                QtCore.QEvent.Type.Move, QtCore.QEvent.Type.Resize):
            self.update_title()
        if obj is self and event_type == QtCore.QEvent.Type.FontChange:
            self.update_menu_font()
        if obj is self and event_type in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.LayoutRequest):
            self.resize_timer.start(0)
        if not self.menu.isHidden():
            if event_type == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
                self.collapse_menu()
                return True
            if event_type == QtCore.QEvent.Type.MouseButtonPress:
                position = event.globalPosition().toPoint()
                widgets = [self.menu] + list(self.menus())
                if not any(widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(position))
                           for widget in widgets):
                    self.collapse_menu()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            window = self.window()
            self.move_position = event.globalPosition().toPoint()
            self.move_geometry = window.geometry()
            if not window.isMaximized() and window.windowHandle().startSystemMove():
                self.move_position = None
                self.move_geometry = None
            event.accept()
        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            self.system_menu.popup(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.move_position is None:
            return
        window = self.window()
        position = event.globalPosition().toPoint()
        if window.isMaximized():
            if (position - self.move_position).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return
            restore_size = window.normalGeometry().size()
            ratio = (self.move_position.x() - self.move_geometry.x()) / max(1, self.move_geometry.width())
            offset_y = min(self.height() - 1, max(0, self.move_position.y() - self.move_geometry.y()))
            window.showNormal()
            window.resize(restore_size)
            window.move(position.x() - round(restore_size.width() * ratio), position.y() - offset_y)
            self.move_position = position
            self.move_geometry = window.geometry()
            if window.windowHandle().startSystemMove():
                self.move_position = None
                self.move_geometry = None
                event.accept()
                return
        window.move(self.move_geometry.topLeft() + position - self.move_position)
        event.accept()

    def mouseReleaseEvent(self, event):
        self.move_position = None
        self.move_geometry = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
