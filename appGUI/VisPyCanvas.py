# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Dennis Hayrullin                            #
# Date: 2/5/2016                                           #
# MIT Licence                                              #
# ##########################################################

from PyQt6.QtGui import QFont, QFontMetricsF, QPalette
from PyQt6.QtCore import QSettings

import numpy as np

import vispy.scene as scene
from vispy.scene.cameras.base_camera import BaseCamera
# from vispy.scene.widgets import Widget as VisPyWidget
from vispy.color import Color
from appGUI.VisPyVisuals import GridLines

import time

white = Color("#ffffff")
black = Color("#000000")


class VisPyCanvas(scene.SceneCanvas):

    def __init__(self, config=None):
        # scene.SceneCanvas.__init__(self, keys=None, config=config)
        super().__init__(config=config, keys=None)

        self.unfreeze()

        # Text uses logical pixels; Qt already handles the device pixel ratio.
        self.dpi = self.native.logicalDpiY()

        settings = QSettings("Open Source", "FlatCAM_EVO")
        if settings.contains("axis_font_size"):
            a_fsize = settings.value('axis_font_size', type=int)
        else:
            a_fsize = 6

        if settings.contains("theme"):
            theme = settings.value('theme', type=str)
        else:
            theme = 'default'

        if settings.contains("dark_canvas"):
            dark_canvas = settings.value('dark_canvas', type=bool)
        else:
            dark_canvas = False

        if (theme == 'default' or theme == 'light') and not dark_canvas:
            theme_color = Color('#FFFFFF')
            tick_color = Color('#000000')
            window_color = QPalette().color(QPalette.ColorRole.Window)
            back_color = str(window_color.name())
            if window_color.lightness() < 128:
                # a dark window (Qt could not follow the theme): black ticks and numbers would not be readable
                tick_color = Color('gray')
        else:
            if theme not in ['default', 'light']:
                theme_color = Color('#202124')
                back_color = Color('#202124')
            else:
                theme_color = Color('#000000')
                back_color = Color('#000000')
            tick_color = Color('gray')
            # back_color = Color('#272822') # darker
            # back_color = Color('#3c3f41') # lighter

        self.central_widget.bgcolor = back_color
        self.central_widget.border_color = back_color

        self.grid_widget = self.central_widget.add_grid(margin=0)
        self.grid_widget.spacing = 0

        top_padding = self.grid_widget.add_widget(row=0, col=0, col_span=2)
        top_padding.height_max = 0

        self.yaxis = scene.AxisWidget(
            orientation='left', axis_color=tick_color, text_color=tick_color, font_size=a_fsize, axis_width=1
        )
        self.yaxis.width_max = 55
        self.yaxis.axis._text.rotation = 45
        self.grid_widget.add_widget(self.yaxis, row=1, col=0)

        self.xaxis = scene.AxisWidget(
            orientation='bottom', axis_color=tick_color, text_color=tick_color, font_size=a_fsize, axis_width=1,
            anchors=['center', 'bottom']
        )
        # Reserve only the ticks, horizontal labels and a small bottom gap.
        font = QFont(self.xaxis.axis._text.face)
        font.setPointSizeF(self.xaxis.axis.tick_font_size)
        label_height = QFontMetricsF(font, self.native).ascent()
        axis_height = np.ceil(self.xaxis.axis.major_tick_length +
                              self.xaxis.axis.tick_label_margin + label_height + 4)
        self.xaxis.height_min = axis_height
        self.xaxis.height_max = axis_height
        self.grid_widget.add_widget(self.xaxis, row=2, col=1)

        right_padding = self.grid_widget.add_widget(row=0, col=2, row_span=2)
        right_padding.width_min = 8
        right_padding.width_max = 8

        view = self.grid_widget.add_view(row=1, col=1, border_color=tick_color, bgcolor=theme_color)
        view.camera = Camera(aspect=1, rect=(-25, -25, 150, 150))

        # Following function was removed from 'prepare_draw()' of 'Grid' class by patch,
        # it is necessary to call manually
        self.grid_widget._update_child_widget_dim()

        self.xaxis.link_view(view)
        self.yaxis.link_view(view)

        # grid1 = scene.GridLines(parent=view.scene, color='dimgray')
        # grid1.set_gl_state(depth_test=False)

        settings = QSettings("Open Source", "FlatCAM_EVO")
        if settings.contains("theme"):
            theme = settings.value('theme', type=str)
        else:
            theme = 'default'

        if settings.contains("dark_canvas"):
            dark_canvas = settings.value('dark_canvas', type=bool)
        else:
            dark_canvas = False

        self.view = view
        if (theme == 'default' or theme == 'light') and not dark_canvas:
            self.grid = GridLines(parent=self.view.scene, color='dimgray')
        else:
            self.grid = GridLines(parent=self.view.scene, color='#dededeff')

        self.grid.set_gl_state(depth_test=False)

        self.freeze()

        # self.measure_fps()

    def translate_coords(self, pos):
        """
        Translate pixels to FlatCAM units.

        """
        tr = self.grid.get_transform('canvas', 'visual')
        return tr.map(pos)

    def pixel_size(self):
        """
        Plot units per screen pixel.
        """
        a = self.translate_coords((0, 0))
        b = self.translate_coords((1, 0))
        return float(np.hypot(b[0] - a[0], b[1] - a[1]))

    def translate_coords_2(self, pos):
        """
        Translate FlatCAM units to logical canvas pixels (the inverse of translate_coords).
        """
        tr = self.grid.get_transform('visual', 'canvas')
        return tr.map(pos)


class Camera(scene.PanZoomCamera):

    def __init__(self, **kwargs):
        super(Camera, self).__init__(**kwargs)

        self.minimum_scene_size = 0.01
        self.maximum_scene_size = 10000

        self.last_event = None
        self.last_time = 0

        # Default mouse button for panning is RMB
        self.pan_button_setting = "2"

        self.zoom_callback = lambda *args: None

    def zoom(self, factor, center=None):
        center = center if (center is not None) else self.center
        super(Camera, self).zoom(factor, center)

    def viewbox_mouse_event(self, event):
        """
        The SubScene received a mouse event; update transform
        accordingly.

        Parameters
        ----------
        event : instance of Event
            The event.
        """
        if event.handled or not self.interactive:
            return

        # key modifiers
        modifiers = event.mouse_event.modifiers

        # Limit mouse move events
        last_event = event.last_event
        t = time.time()
        if t - self.last_time > 0.015:
            self.last_time = t
            if self.last_event:
                last_event = self.last_event
                self.last_event = None
        else:
            if not self.last_event:
                self.last_event = last_event
            event.handled = True
            return

        # ################### Scrolling ##########################
        BaseCamera.viewbox_mouse_event(self, event)

        if event.type == 'mouse_wheel':
            if not modifiers:
                center = self._scene_transform.imap(event.pos)
                scale = (1 + self.zoom_factor) ** (-event.delta[1] * 30)
                self.limited_zoom(scale, center)

            if self.zoom_callback:
                self.zoom_callback()
            event.handled = True

        elif event.type == 'mouse_move':
            if event.press_event is None:
                return

            # ################ Panning ############################
            # self.pan_button_setting is actually self.FlatCAM.APP.defaults['global_pan_button']
            if event.button == int(self.pan_button_setting) and not modifiers:
                # Translate
                p1 = np.array(last_event.pos)[:2]
                p2 = np.array(event.pos)[:2]
                p1s = self._transform.imap(p1)
                p2s = self._transform.imap(p2)
                self.pan(p1s-p2s)
                event.handled = True
            elif event.button in [2, 3] and 'Shift' in modifiers:
                # Zoom
                p1c = np.array(last_event.pos)[:2]
                p2c = np.array(event.pos)[:2]
                scale = ((1 + self.zoom_factor) **
                         ((p1c-p2c) * np.array([1, -1])))
                center = self._transform.imap(event.press_event.pos[:2])
                self.limited_zoom(scale, center)
                event.handled = True
            else:
                event.handled = False
        elif event.type == 'mouse_press':
            # accept the event if it is button 1 or 2.
            # This is required in order to receive future events
            event.handled = event.button in [1, 2, 3]
        else:
            event.handled = False

    def limited_zoom(self, scale, center):

        try:
            zoom_in = scale[1] < 1
        except IndexError:
            zoom_in = scale < 1

        if (not zoom_in and self.rect.width < self.maximum_scene_size) \
                or (zoom_in and self.rect.width > self.minimum_scene_size):
            self.zoom(scale, center)
