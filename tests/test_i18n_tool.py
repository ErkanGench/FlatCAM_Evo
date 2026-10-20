"""
scripts/i18n_tool.py: extraction of the strings, .po read / write / merge, .mo compilation, placeholder checks.

    python tests/test_i18n_tool.py
"""

import contextlib
import functools
import gettext
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import i18n_tool as t       # noqa: E402


@functools.lru_cache(maxsize=None)
def extract_program_strings():
    """1 extraction of the strings of the program (about 4 seconds) for the tests that only read the result."""
    return t.extract()


PO = textwrap.dedent('''\
    msgid ""
    msgstr ""
    "Content-Type: text/plain; charset=UTF-8\\n"
    "Language: tr_TR\\n"

    #: a.py:1
    msgid "Title"
    msgstr "Başlık"

    #: a.py:2
    msgid ""
    "Two lines.\\n"
    "Second \\"quoted\\" line"
    msgstr ""
    "İki satır.\\n"
    "İkinci \\"tırnaklı\\" satır"

    #: a.py:3
    #, fuzzy
    #| msgid "Fuzzy"
    msgid "Fuzzy one"
    msgstr "Belirsiz"

    #: a.py:4
    msgid "Gone"
    msgstr "Gitti"

    # a translator comment
    #~| msgid "Older"
    #~ msgid "Old"
    #~ msgstr "Eski"
    ''')


class TestPo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.po = os.path.join(self.dir, 'strings.po')
        with open(self.po, 'w', encoding='utf-8') as f:
            f.write(PO)

    def test_read(self):
        header, entries = t.read_po(self.po)
        self.assertIn('Language: tr_TR', header.msgstr)
        self.assertEqual(['Title', 'Two lines.\nSecond "quoted" line', 'Fuzzy one', 'Gone', 'Old'],
                         [e.msgid for e in entries])
        self.assertEqual('İki satır.\nİkinci "tırnaklı" satır', entries[1].msgstr)
        self.assertTrue(entries[2].fuzzy)
        self.assertTrue(entries[4].obsolete)
        self.assertFalse(entries[3].obsolete)
        # the previous English texts that Poedit shows next to a fuzzy entry
        self.assertEqual(['msgid "Fuzzy"'], entries[2].previous)
        self.assertEqual(['msgid "Older"'], entries[4].previous)
        self.assertEqual([], entries[0].previous)

    def test_write_read_round_trip(self):
        header, entries = t.read_po(self.po)
        entries.append(t.Entry('A long string ' * 12 + 'with\ttab and back\\slash', 'Uzun ' * 30, ['b.py:9']))
        out = os.path.join(self.dir, 'out.po')
        t.write_po(out, header, entries)
        h2, e2 = t.read_po(out)
        self.assertEqual(header.msgstr, h2.msgstr)
        self.assertEqual([(e.msgid, e.msgstr, e.obsolete, e.flags, e.previous) for e in entries],
                         [(e.msgid, e.msgstr, e.obsolete, e.flags, e.previous) for e in e2])
        with open(out, encoding='utf-8') as f:
            text = f.read()
        self.assertTrue(all(len(line) <= 81 for line in text.splitlines() if not line.startswith('#')))
        self.assertIn('#, fuzzy\n#| msgid "Fuzzy"\nmsgid "Fuzzy one"\n', text)
        self.assertIn('#~| msgid "Older"\n#~ msgid "Old"\n', text)

    def test_compile_skips_fuzzy_and_obsolete(self):
        mo = os.path.join(self.dir, 'strings.mo')
        self.assertEqual(3, t.compile_mo(self.po, mo))
        with open(mo, 'rb') as f:
            catalog = gettext.GNUTranslations(f)
        self.assertEqual('Başlık', catalog.gettext('Title'))
        self.assertEqual('İki satır.\nİkinci "tırnaklı" satır', catalog.gettext('Two lines.\nSecond "quoted" line'))
        self.assertEqual('Fuzzy one', catalog.gettext('Fuzzy one'))
        self.assertEqual('Old', catalog.gettext('Old'))

    def test_read_rejects_malformed_strings_with_the_file_and_line(self):
        for invalid in ('msgid "Title', 'msgstr "Titel', 'msgstr Titel"',
                        'msgstr "Ti"tel"', 'msgstr "Titel" trailing',
                        '"unfinished continuation', '#~ msgstr "Titel', 'msgstr"Titel"'):
            with self.subTest(line=invalid):
                with open(self.po, 'w', encoding='utf-8') as f:
                    f.write('msgid ""\nmsgstr ""\n\nmsgid "Title"\n' + invalid + '\n')
                with self.assertRaises(ValueError) as raised:
                    t.read_po(self.po)
                self.assertIn(self.po + ':5:', str(raised.exception))

    def test_compile_does_not_overwrite_a_catalog_when_po_syntax_is_invalid(self):
        mo = os.path.join(self.dir, 'strings.mo')
        t.compile_mo(self.po, mo)
        with open(mo, 'rb') as f:
            original = f.read()
        with open(self.po, 'w', encoding='utf-8') as f:
            f.write('msgid "Title"\nmsgstr "Titel\n')
        with self.assertRaises(ValueError):
            t.compile_mo(self.po, mo)
        with open(mo, 'rb') as f:
            self.assertEqual(original, f.read())

    def test_merge(self):
        lang_dir = os.path.join(self.dir, 'locale', 'xx', 'LC_MESSAGES')
        os.makedirs(lang_dir)
        shutil.copy(self.po, os.path.join(lang_dir, 'strings.po'))
        old_root = t.ROOT
        t.ROOT = self.dir
        try:
            strings = {'Title': ['a.py:10'], 'Fuzzy one': ['a.py:11'], 'Old': ['a.py:12'], 'New text': ['a.py:13']}
            counts = t.merge('xx', strings)
            header, entries = t.read_po(os.path.join(lang_dir, 'strings.po'))
        finally:
            t.ROOT = old_root
        self.assertEqual({'kept': 2, 'revived': 1, 'new': 1, 'obsolete': 2}, counts)
        active = {e.msgid: e for e in entries if not e.obsolete}
        self.assertEqual(['Title', 'Fuzzy one', 'Old', 'New text'], list(active))
        self.assertEqual('Eski', active['Old'].msgstr)
        self.assertEqual(['a.py:10'], active['Title'].refs)
        self.assertEqual('', active['New text'].msgstr)
        # the fuzzy entry keeps its flag and its previous English text, the revived one too
        self.assertTrue(active['Fuzzy one'].fuzzy)
        self.assertEqual(['msgid "Fuzzy"'], active['Fuzzy one'].previous)
        self.assertEqual(['msgid "Older"'], active['Old'].previous)
        self.assertEqual({'Two lines.\nSecond "quoted" line', 'Gone'}, {e.msgid for e in entries if e.obsolete})


class TestTranslatorTools(unittest.TestCase):
    """init, stats, glossary and the .mo check, in a throw-away locale folder."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.old_root = t.ROOT
        t.ROOT = self.dir
        self.addCleanup(setattr, t, 'ROOT', self.old_root)
        self.lang_dir = os.path.join(self.dir, 'locale', 'xx', 'LC_MESSAGES')
        os.makedirs(self.lang_dir)
        with open(os.path.join(self.lang_dir, 'strings.po'), 'w', encoding='utf-8') as f:
            f.write(PO)
        self.template = os.path.join(self.dir, 'strings.pot')
        t.write_template({'Title': ['a.py:1'], 'Tools Table:': ['a.py:2']}, self.template)

    def test_init_makes_an_untranslated_po_with_the_plural_rule(self):
        path = t.init_po('ar', self.template)
        header, entries = t.read_po(path)
        self.assertIn('Language: ar', header.msgstr)
        self.assertIn('Plural-Forms: nplurals=6;', header.msgstr)
        self.assertEqual(['Title', 'Tools Table:'], [e.msgid for e in entries])
        self.assertEqual(['', ''], [e.msgstr for e in entries])
        self.assertEqual(['a.py:1'], entries[0].refs)
        with self.assertRaises(FileExistsError):
            t.init_po('ar', self.template)

    def test_stats_counts_and_mo_state(self):
        s = t.stats('xx')
        # active: Title, Two lines, Fuzzy one, Gone; the fuzzy one is not shown by the program
        self.assertEqual({'strings': 4, 'translated': 3, 'untranslated': 0, 'fuzzy': 1, 'errors': 0, 'warnings': 0,
                          'mo_current': False}, s)
        t.compile_mo(t.po_path('xx'), t.po_path('xx')[:-3] + '.mo')
        self.assertTrue(t.mo_is_current('xx'))
        self.assertIn('| xx | 4 | 3 (75 %) | 0 | 1 | 0 | 0 | yes |', t.stats_markdown([('xx', t.stats('xx'))]))
        status = os.path.join(self.dir, 'status.md')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, t.main(['stats', 'xx', '--markdown', status]))
        with open(status, encoding='utf-8') as f:
            text = f.read()
        self.assertTrue(text.startswith('# Translation status\n\nMade by '), text)
        self.assertIn('| xx | 4 | 3 (75 %) | 0 | 1 | 0 | 0 | yes |', text)

    def test_check_fails_on_errors_only(self):
        def run_check():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = t.main(['check', 'xx'])
            return code, out.getvalue()

        with open(t.po_path('xx'), encoding='utf-8') as f:
            text = f.read()
        self.assertEqual(0, run_check()[0])
        # a warning: the program shows the added tag as it is
        with open(t.po_path('xx'), 'w', encoding='utf-8') as f:
            f.write(text.replace('msgstr "Gitti"', 'msgstr "<i>Gitti</i>"'))
        code, out = run_check()
        self.assertEqual(0, code)
        self.assertIn("warning: 'Gone': HTML tags differ", out)
        self.assertEqual((0, 1), (t.stats('xx')['errors'], t.stats('xx')['warnings']))
        # an error: the translation lost the %s, formatting it raises "not all arguments converted"
        with open(t.po_path('xx'), 'w', encoding='utf-8') as f:
            f.write(text.replace('msgid "Gone"', 'msgid "Gone %s"'))
        code, out = run_check()
        self.assertEqual(1, code)
        self.assertIn("error: 'Gone %s': formatting with % fails", out)
        self.assertEqual((1, 0), (t.stats('xx')['errors'], t.stats('xx')['warnings']))

    def test_mo_check_sees_a_po_change(self):
        t.compile_mo(t.po_path('xx'), t.po_path('xx')[:-3] + '.mo')
        with open(t.po_path('xx'), encoding='utf-8') as f:
            text = f.read()
        with open(t.po_path('xx'), 'w', encoding='utf-8') as f:
            f.write(text.replace('msgstr "Başlık"', 'msgstr "Başlık 2"'))
        self.assertFalse(t.mo_is_current('xx'))
        self.assertEqual(1, t.main(['compile', '--check', 'xx']))

    def test_mo_check_ignores_the_header(self):
        # Poedit and msgfmt leave some header fields out of the .mo: the same translations are up to date
        messages = t.po_messages(t.po_path('xx'))
        self.assertEqual({'', 'Title', 'Two lines.\nSecond "quoted" line', 'Gone'}, set(messages))
        messages[''] = 'Content-Type: text/plain; charset=UTF-8\n'
        with open(t.po_path('xx')[:-3] + '.mo', 'wb') as f:
            f.write(t.mo_bytes(messages))
        self.assertEqual(messages, t.read_mo(t.po_path('xx')[:-3] + '.mo'))
        self.assertTrue(t.mo_is_current('xx'))
        self.assertEqual(0, t.main(['compile', '--check', 'xx']))

    def test_glossary_ignores_case_colon_and_fuzzy(self):
        rows = t.glossary([('title', 'a note'), ('fuzzy one', ''), ('Missing', '')], ['xx'])
        self.assertEqual([['title', 'a note', 'Başlık'], ['fuzzy one', '', ''], ['Missing', '', '']], rows)

    def test_the_terms_file_and_the_real_languages(self):
        t.ROOT = self.old_root
        terms = t.read_terms(t.GLOSSARY_TERMS)
        self.assertGreater(len(terms), 50)
        self.assertTrue(all(term and note for term, note in terms))
        # every term is a string of the program (case and a final ':' ignored), so a language can translate it
        strings, __ = extract_program_strings()
        texts = {s.strip().rstrip(':').strip().casefold() for s in strings}
        self.assertEqual([], [term for term, __ in terms if term.casefold() not in texts])
        langs = [lang for lang in t.languages() if lang != 'en']
        rows = t.glossary(terms, langs)
        self.assertEqual([len(langs) + 2] * len(terms), [len(r) for r in rows])


class TestChecks(unittest.TestCase):
    def test_correct_translations(self):
        self.assertEqual(([], []), t.check_entry('Done %s of %d', '%s / %d yapıldı'))
        self.assertEqual(([], []), t.check_entry('Downloading: %s%%', 'İndiriliyor: %%%s'))
        self.assertEqual(([], []), t.check_entry('Less than 100%%.', '%%100 den az.'))
        self.assertEqual(([], []), t.check_entry('Name: {name}', 'Ad: {name}'))
        self.assertEqual(([], []), t.check_entry('<b>Bold</b>', '<b>Kalın</b>'))
        self.assertEqual(([], []), t.check_entry('Anything', ''))

    def test_errors_make_the_formatting_fail(self):
        def errors(msgid, msgstr):
            return t.check_entry(msgid, msgstr)[0]

        self.assertTrue(errors('Done %s', 'Yapıldı'))                  # not all arguments converted
        self.assertTrue(errors('Done %s of %d', '%d / %s yapıldı'))    # %d of a text
        self.assertTrue(errors('%s at 100%%', '%s 100 % de'))          # a single % in a formatted text
        self.assertTrue(errors('%(count)s done', '%(sayi)s bitti'))    # KeyError
        self.assertTrue(errors('Name: {name}', 'Ad: {ad}'))

    def test_brace_checks_reject_invalid_syntax_and_escaped_fields(self):
        for translated in ('Name: {name} {', 'Name: {name} }', 'Name: {{name}}',
                           'Name: {name!}', 'Name: {name:{width}'):
            with self.subTest(translation=translated):
                errors, __ = t.check_entry('Name: {name}', translated)
                self.assertTrue(errors)
        self.assertTrue(t.check_entry('Name: {user.name}', 'Name: {user.other}')[0])

    def test_brace_checks_allow_escaped_literals_and_reordered_fields(self):
        self.assertEqual(([], []), t.check_entry(
            '{{literal}} {name!r:>10} {count}', '{count} {name!r:>10} {{translated literal}}'))
        self.assertEqual(([], []), t.check_entry('{value:{width}.{precision}f}', '{value:{width}.{precision}f}'))
        self.assertEqual(([], []), t.check_entry('First: {} second: {}', '{} then {}'))

    def test_warnings_are_shown_as_they_are(self):
        def only_warnings(msgid, msgstr):
            found_errors, found_warnings = t.check_entry(msgid, msgstr)
            self.assertEqual([], found_errors, msgstr)
            return found_warnings

        # written differently, still formats
        self.assertEqual(["printf placeholders ['%s'] != ['% s']"], only_warnings('It is %s.', '% s.'))
        # a %s added to a text that the program does not format: the user sees "%s"
        self.assertEqual(["printf placeholders [] != ['%s']"], only_warnings('Skipping file', '%s atlandı'))
        # a %%-only text is not formatted by the program
        self.assertTrue(only_warnings('Less than 100%%.', '% 100 den az.'))
        self.assertEqual(['HTML tags differ'], only_warnings('<b>Bold</b>', 'Kalın'))
        self.assertEqual(['argument placeholders <...> differ'],
                         only_warnings('Type help <command_name> for usage.', 'help <komut_adi> yazın.'))
        # <center> is an argument of the Tcl scale and skew commands, not the HTML tag
        self.assertEqual(['argument placeholders <...> differ'],
                         only_warnings('-origin <center>', '-origin <merkez>'))
        self.assertEqual(['final newline differs'], only_warnings('Line\n', 'Satır'))


class TestExtract(unittest.TestCase):
    def test_literals_and_problems(self):
        src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, src, True)
        with open(os.path.join(src, 'mod.py'), 'w', encoding='utf-8') as f:
            f.write(textwrap.dedent('''\
                a = _("First")
                b = _("Implicit " "concatenation")
                c = _("First")
                d = _(name)
                e = _("Bad %s" % 3)
                g = _("")
                '''))
        os.makedirs(os.path.join(src, 'tests'))
        with open(os.path.join(src, 'tests', 'skip.py'), 'w', encoding='utf-8') as f:
            f.write('x = _("Not extracted")\n')
        strings, problems = t.extract(src)
        self.assertEqual(['First', 'Implicit concatenation'], list(strings))
        self.assertEqual(['mod.py:1', 'mod.py:3'], strings['First'])
        self.assertEqual(2, len(problems))

    def test_the_application_strings(self):
        strings, problems = extract_program_strings()
        self.assertGreater(len(strings), 3000)
        # the format operator inside _() makes a string that can not be translated
        self.assertFalse([p for p in problems if 'BinOp' in p or 'JoinedStr' in p], problems)


if __name__ == '__main__':
    unittest.main()
