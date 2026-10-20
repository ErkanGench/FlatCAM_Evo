# Reviewed translations

This folder lists, for every language, each translation that the "reviewed translations" change brought into
`locale/<lang>/LC_MESSAGES/strings.po`, so that native speakers can check and approve them.

## Where they come from

The translations of all languages were brought up to date with the code of 19 September 2026 in a fork of FlatCAM
Evo, then moved onto the current catalogs with `scripts/i18n_tool.py` (`extract` + `merge`, then each reviewed
translation applied to the same English text):

- **Fuzzy entries**, which the program never shows (users saw English), were confirmed or corrected.
- **Missing translations** were translated.
- **Format errors** were fixed (a broken `%s`, `{name}`, `%%` or HTML tag can make the program fail).
- **Wrong or poor translations** were corrected: wrong meaning, mistranslated CNC/PCB term, English left in the text,
  grammar, a missing part of the sentence.

Method: for each chunk of entries a translator model made the changes and gave a reason for each; a second,
independent reviewer model accepted, rejected or corrected every change; every change was checked with
`scripts/i18n_tool.py` (placeholders, `%%`, HTML tags, `<argument>` names, newlines, and a real `%` formatting test).
Turkish was also checked on screen. A translation that Marius's catalog had changed since September was kept as it
is; nothing that failed the check was applied.

**These are machine-assisted changes. They need a native translator's approval.**

| Language | Reviewed entries in this change | Still untranslated (newer texts) |
|---|---|---|
| Deutsch (de) | 1486 | 443 |
| Español (es) | 1042 | 443 |
| Français (fr) | 1305 | 443 |
| Italiano (it) | 894 | 443 |
| Português do Brasil (pt_BR) | 574 | 443 |
| Română (ro) | 924 | 443 |
| Русский (ru) | 1353 | 443 |
| Türkçe (tr) | 1097 | 443 |
| 简体中文 (zh) | 1009 | 443 |

The texts added to the program after September are not translated here; they show in English until they are.

## How to approve

- `<lang>.md`: readable table (type, English, old translation, new translation, reason).
- `<lang>.csv`: the same rows for a spreadsheet (UTF-8). Fill in *Approved (yes/no)* and, if needed, your own text
  in *Translator note*, and send the file back (an issue with the *Translation problem* form, or a pull request).

You can also work directly in the `.po` file (for example with Poedit): every entry changed this way carries the
comment `# auto-review 2026-10-09: <type>`. Delete the comment when you have checked the entry, then run

    python scripts/i18n_tool.py check <lang>
    python scripts/i18n_tool.py compile <lang>

## Change types

| Type | Meaning |
|---|---|
| format | Format fix (placeholder / %% / tag / newline error that could break the program) |
| corrected | Correction of an existing translation |
| fuzzy corrected | A fuzzy (unused) translation was corrected; the program now uses it |
| fuzzy confirmed | A fuzzy (unused) translation was right; the program now uses it |
| untranslated copy | The translation was a copy of the English text; now translated |
| new | New translation (the text had no translation) |
| manual | Terminology fix made by hand after checking the program in that language |
