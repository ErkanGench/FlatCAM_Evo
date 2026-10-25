"""The preference rows that set how the circles of an object kind are made of segments: Adaptive or Fixed."""

from appGUI.GUIElements import FCSpinner, FCDoubleSpinner, RadioSet, FCLabel

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class CircleStepsRows:
    """
    The rows "Circles" (Adaptive / Fixed), "Max Deviation" (Adaptive mode) and "Circle Steps" (Fixed mode).
    Fixed mode shows the Circle Steps; Adaptive mode shows the Max Deviation.
    """

    def __init__(self, grid, row, what, max_steps=9999):
        """
        :param grid:        the grid layout that takes the rows
        :param row:         the first row of the grid
        :param what:        the circles that the setting changes, for the tooltip (e.g. "pads, track ends, arcs")
        :param max_steps:   the upper limit of the Circle Steps
        """
        self.mode_label = FCLabel('%s:' % _("Circles"))
        self.mode_label.setToolTip(
            '%s (%s)\n%s' % (
                _("How the circles are made of straight line segments"), what,
                _("- Adaptive: each circle gets the number of segments that keeps\n"
                  "it within the Max Deviation of the true circle. Small circles get\n"
                  "few segments, large circles get many.\n"
                  "- Fixed: every circle gets the same number of segments (Circle Steps)."))
        )
        self.mode_radio = RadioSet([{'label': _('Adaptive'), 'value': 'adaptive'},
                                    {'label': _('Fixed'), 'value': 'fixed'}], compact=True)
        grid.addWidget(self.mode_label, row, 0)
        grid.addWidget(self.mode_radio, row, 1, 1, 2)

        self.tol_label = FCLabel('%s:' % _("Max Deviation"))
        self.tol_label.setToolTip(
            _("The largest distance, in micrometers, between a circle\n"
              "and the straight segments that replace it.\n"
              "A smaller value gives smoother circles and more segments.")
        )
        self.tol_entry = FCDoubleSpinner()
        self.tol_entry.set_precision(2)
        self.tol_entry.set_range(0.01, 1000.0)
        self.tol_entry.setSingleStep(0.5)
        self.tol_units = FCLabel('%s' % _("µm"))
        grid.addWidget(self.tol_label, row + 1, 0)
        grid.addWidget(self.tol_entry, row + 1, 1)
        grid.addWidget(self.tol_units, row + 1, 2)

        self.steps_label = FCLabel('%s:' % _("Circle Steps"))
        self.steps_label.setToolTip(
            _("The number of circle steps for \n"
              "linear approximation of circles.")
        )
        self.steps_entry = FCSpinner()
        self.steps_entry.set_range(0, max_steps)
        grid.addWidget(self.steps_label, row + 2, 0)
        grid.addWidget(self.steps_entry, row + 2, 1, 1, 2)

        self.mode_radio.activated_custom.connect(self.on_mode_changed)
        self.on_mode_changed('adaptive')

    def on_mode_changed(self, mode):
        fixed = mode == 'fixed'
        self.steps_label.setVisible(fixed)
        self.steps_entry.setVisible(fixed)
        self.tol_label.setVisible(not fixed)
        self.tol_entry.setVisible(not fixed)
        self.tol_units.setVisible(not fixed)
