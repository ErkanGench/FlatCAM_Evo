"""
The messages of the Gerber parser are looked up in the translation catalog with their literal text; the values are
put in after the translation. A % formatting inside _() looks up a text that no catalog holds, so the message is
always shown in English.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import appParsers.ParseGerber as ParseGerber
from appParsers.ParseGerber import Gerber

UNDEFINED_APERTURE = ("Gerber implementation format not supported. Undefined aperture at line: %s. "
                      "Report to developers.")


class TestGerberTranslatedMessages(unittest.TestCase):
    def test_undefined_aperture_message_is_translated(self):
        catalog = {UNDEFINED_APERTURE: "Translated: undefined aperture at line %s."}
        messages = []
        parser = SimpleNamespace(tools={}, app=SimpleNamespace(inform=SimpleNamespace(emit=messages.append)))
        with mock.patch.object(ParseGerber, '_', lambda text: catalog.get(text, text), create=True):
            path, aperture = Gerber._handle_region_start(parser, [[0.0, 0.0], [1.0, 0.0]], None, [], [], 4, 12, None)
        self.assertEqual(['[ERROR] Translated: undefined aperture at line 12.'], messages)
        self.assertEqual([[1.0, 0.0]], path)
        self.assertIsNone(aperture)


if __name__ == '__main__':
    unittest.main()
