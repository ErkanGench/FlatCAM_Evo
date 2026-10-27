"""Typing into the FlatCAM input widgets (GUIElements)."""
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtTest import QTest

from appGUI.GUIElements import FCDoubleSpinner, FCSpinner


@pytest.fixture(scope='module', autouse=True)
def qt_application():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def spinner_with_800(cls):
    """A spinner with the range 0 to 1000 and the value 800, its text selected for typing."""
    spinner = cls()
    spinner.set_range(0, 1000)
    spinner.set_value(800)
    spinner.lineEdit().selectAll()
    return spinner


@pytest.mark.parametrize('cls', [FCSpinner, FCDoubleSpinner])
def test_typed_number_over_the_maximum_keeps_the_previous_value(cls):
    spinner = spinner_with_800(cls)
    values = []
    spinner.valueChanged.connect(values.append)

    QTest.keyClicks(spinner.lineEdit(), '1500')
    QTest.keyClick(spinner.lineEdit(), QtCore.Qt.Key.Key_Return)

    assert spinner.get_value() == 800  # not 150, the last prefix in the range
    assert values == []  # the prefixes 1, 15 and 150 were not committed


@pytest.mark.parametrize('cls', [FCSpinner, FCDoubleSpinner])
def test_typed_number_reaches_the_slots_of_the_keypad_enter(cls):
    spinner = spinner_with_800(cls)
    seen = []
    spinner.returnPressed.connect(lambda: seen.append(spinner.get_value()))

    QTest.keyClicks(spinner.lineEdit(), '950')
    QTest.keyClick(spinner, QtCore.Qt.Key.Key_Enter)

    assert spinner.get_value() == 950
    assert seen and set(seen) == {950}
