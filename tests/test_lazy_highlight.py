"""
The code editor of FCTextAreaLineNumber (Source Editor, G-code editor) highlights only the lines that are shown; the
other lines are highlighted when they are scrolled into view. Qt highlighted every line when the text was set: the
View Source of a G-code of 94000 lines took 11 s.

    python tests/test_lazy_highlight.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6 import QtGui, QtWidgets                        # noqa: E402

from appGUI.GUIElements import FCTextAreaLineNumber        # noqa: E402

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def gcode(lines):
    rows = ['(G-code test)', 'G21', 'G90']
    for k in range(lines):
        rows.append('G1 X%.4f Y%.4f F1000.00' % (k * 0.01, -k * 0.02))
    return '\n'.join(rows)


def pump():
    for __ in range(5):
        APP.processEvents()


class EditorCase(unittest.TestCase):
    LINES = 5000

    def setUp(self):
        self.frame = FCTextAreaLineNumber(theme='default')
        self.frame.resize(600, 400)
        self.frame.show()
        self.edit = self.frame.edit
        pump()
        self.edit.setPlainText(gcode(self.LINES))
        pump()

    def tearDown(self):
        self.frame.close()
        self.frame.deleteLater()
        pump()

    def block(self, number):
        return self.edit.document().findBlockByNumber(number)

    def formatted(self, number):
        return bool(self.block(number).layout().formats())

    def scroll_to(self, number):
        self.edit.verticalScrollBar().setValue(number)
        pump()

    def replace_line(self, number, text):
        # what Replace does to a line that is not shown
        cursor = QtGui.QTextCursor(self.block(number))
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock, QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        pump()


class TestLazyHighlight(EditorCase):

    def test_only_the_lines_shown_are_highlighted_when_the_text_is_set(self):
        self.assertTrue(self.formatted(5))
        self.assertFalse(self.formatted(4000))
        self.assertEqual(self.block(4000).userState(), -1)
        self.assertLess(self.edit.shown_blocks[1], 4000)

    def test_lines_are_highlighted_when_scrolled_into_view(self):
        self.scroll_to(4000)
        shown = self.edit.firstVisibleBlock().blockNumber()
        self.assertTrue(shown >= 3990)
        # every line shown (a 400 px high editor shows more than 15 lines)
        for number in range(shown, shown + 15):
            self.assertTrue(self.formatted(number), number)
        # the lines highlighted before stay highlighted
        self.assertTrue(self.formatted(5))

    def test_highlighting_does_not_report_text_changes(self):
        changes = []
        self.edit.textChanged.connect(lambda: changes.append(1))
        self.edit.document().setModified(False)
        text = self.edit.toPlainText()

        self.scroll_to(4000)
        self.frame.resize(600, 1000)
        pump()
        self.assertTrue(self.formatted(4001))
        self.assertEqual(self.edit.toPlainText(), text)
        self.assertFalse(self.edit.document().isModified())
        self.assertEqual(changes, [])

        # Real edits must still notify the editor and enable saving.
        self.replace_line(4001, 'G1 X1.0000 Y2.0000 F800.00')
        self.assertTrue(changes)
        self.assertTrue(self.edit.document().isModified())

    def test_lines_shown_by_a_taller_editor_are_highlighted(self):
        # a resize of the height only (the Tcl Shell dock closed, the window made taller) emits no updateRequest
        self.frame.resize(600, 1000)
        pump()
        self.assertEqual(self.edit.firstVisibleBlock().blockNumber(), 0)
        top = self.edit.blockBoundingGeometry(self.block(40)).translated(self.edit.contentOffset()).top()
        self.assertLess(top, self.edit.viewport().height())
        for number in range(3, 41):
            self.assertTrue(self.formatted(number), number)

    def test_typed_line_is_highlighted(self):
        self.edit.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.edit.insertPlainText('\nG0 X1.0000 Y2.0000')
        pump()
        self.assertTrue(self.formatted(self.edit.document().blockCount() - 1))

    def test_changed_line_not_shown_keeps_its_colors(self):
        self.scroll_to(1000)
        for number in (1001, 1002, 1003):
            self.assertTrue(self.formatted(number))
        self.scroll_to(0)
        self.assertEqual(self.edit.firstVisibleBlock().blockNumber(), 0)

        self.replace_line(1001, 'G1 X1.0000 Y2.0000 F800.00')
        self.assertTrue(self.formatted(1001))
        self.assertTrue(self.formatted(1002))

        # Undo: the line keeps its colors
        self.edit.undo()
        pump()
        self.assertIn('F1000.00', self.block(1001).text())
        self.assertTrue(self.formatted(1001))

    def test_changed_line_never_shown_is_left_for_later(self):
        self.replace_line(2500, 'G1 X1.0000 Y2.0000 F800.00')
        self.assertEqual(self.block(2500).userState(), -1)
        self.assertFalse(self.formatted(2500))
        self.assertFalse(self.formatted(2501))

        self.scroll_to(2498)
        self.assertTrue(self.formatted(2500))


class TestPrint(EditorCase):
    LINES = 400

    def test_printed_document_is_highlighted_on_every_line(self):
        self.assertFalse(self.formatted(350))
        changes = []
        self.edit.textChanged.connect(lambda: changes.append(1))
        with tempfile.TemporaryDirectory() as folder:
            self.edit.print(QtGui.QPdfWriter(os.path.join(folder, 'print.pdf')))
        self.assertEqual(changes, [])
        for number in (5, 350, self.LINES + 2):
            self.assertTrue(self.formatted(number), number)
        # the highlighting of the lines shown goes on
        self.assertIs(self.edit.highlighter.editor, self.edit)
        self.assertFalse(self.edit.highlighting_shown)

    def test_print_does_not_look_for_the_lines_shown_after_each_line(self):
        # each line highlighted by print() emits updateRequest; highlight_shown_blocks() must not run for each one
        calls = []
        first_visible_block = self.edit.firstVisibleBlock
        self.edit.firstVisibleBlock = lambda: calls.append(1) or first_visible_block()
        try:
            with tempfile.TemporaryDirectory() as folder:
                self.edit.print(QtGui.QPdfWriter(os.path.join(folder, 'print.pdf')))
        finally:
            del self.edit.firstVisibleBlock
        self.assertTrue(self.formatted(350))
        self.assertLess(len(calls), 10)

    def test_second_print_does_not_highlight_again(self):
        # (Print Preview prints again on each render)
        calls = []
        rehighlight = self.edit.highlighter.rehighlight
        self.edit.highlighter.rehighlight = lambda: calls.append(1) or rehighlight()
        with tempfile.TemporaryDirectory() as folder:
            for name in ('first.pdf', 'second.pdf'):
                self.edit.print(QtGui.QPdfWriter(os.path.join(folder, name)))
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.formatted(350))


class TestSmallText(EditorCase):
    LINES = 20

    def test_every_line_is_highlighted(self):
        # (the G1 lines have X and Y coordinates)
        self.assertTrue(all(self.formatted(n) for n in range(3, self.LINES + 3)))


if __name__ == '__main__':
    unittest.main()
