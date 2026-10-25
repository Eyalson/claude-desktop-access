"""Tests for tools/build_addon.py and for the add-on's packaging files."""

import gettext
import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_addon", ROOT / "tools" / "build_addon.py")
build_addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_addon)

HEBREW_PO = ROOT / "addon" / "locale" / "he" / "LC_MESSAGES" / "nvda.po"


class PackagingTests(unittest.TestCase):
    def test_manifest_and_module_versions_match(self):
        manifest, problems = build_addon.check()
        self.assertEqual(problems, [])
        self.assertEqual(manifest["version"], build_addon.moduleVersion())

    def test_manifest_values_are_read_without_quotes(self):
        manifest = build_addon.readManifest(ROOT / "addon" / "manifest.ini")
        self.assertEqual(manifest["name"], "claudeAccess")
        self.assertEqual(manifest["summary"], "Claude Desktop Access")
        self.assertEqual(manifest["author"], "Sontech - Eyal Sonsino")
        self.assertNotIn('"', manifest["description"])

    def test_archive_has_the_files_nvda_expects(self):
        with tempfile.TemporaryDirectory() as folder:
            target = build_addon.build(Path(folder))
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                mo = archive.read("locale/he/LC_MESSAGES/nvda.mo")
        self.assertTrue(target.name.startswith("claudeAccess-"))
        self.assertTrue(target.name.endswith(".nvda-addon"))
        for expected in ("manifest.ini", "appModules/claude.py", "doc/en/readme.html", "locale/he/LC_MESSAGES/nvda.mo"):
            self.assertIn(expected, names)
        self.assertFalse([n for n in names if n.endswith(".po")])
        self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])
        self.assertFalse([n for n in names if "\\" in n])
        translation = gettext.GNUTranslations(io.BytesIO(mo))
        self.assertEqual(translation.gettext("No panel to close"), "לא נמצא פאנל לסגירה")

    def test_help_file_is_english(self):
        text = (ROOT / "addon" / "doc" / "en" / "readme.html").read_text(encoding="utf-8")
        self.assertIn('lang="en"', text)

    def test_missing_required_file_stops_the_build(self):
        original = build_addon.REQUIRED
        build_addon.REQUIRED = original + ("appModules/does_not_exist.py",)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(SystemExit):
                    build_addon.build(Path(folder))
        finally:
            build_addon.REQUIRED = original


class TranslationTests(unittest.TestCase):
    def test_every_message_in_the_code_is_translated(self):
        entries = build_addon.parsePo(HEBREW_PO.read_text(encoding="utf-8"))
        self.assertEqual(build_addon.messagesInCode() - set(entries), set())
        self.assertGreaterEqual(len(build_addon.messagesInCode()), 8)

    def test_placeholders_survive_translation(self):
        entries = build_addon.parsePo(HEBREW_PO.read_text(encoding="utf-8"))
        for msgid, msgstr in entries.items():
            if "{panel}" in msgid:
                self.assertIn("{panel}", msgstr)

    def test_po_parser_joins_continued_lines_and_skips_untranslated(self):
        text = 'msgid ""\nmsgstr "header"\n\nmsgid "a"\n"b"\nmsgstr "x"\n"y"\n\nmsgid "empty"\nmsgstr ""\n'
        self.assertEqual(build_addon.parsePo(text), {"": "header", "ab": "xy"})

    def test_compiled_mo_is_read_by_gettext(self):
        mo = build_addon.compileMo({"": "Content-Type: text/plain; charset=UTF-8\n", "Hello": "שלום"})
        translation = gettext.GNUTranslations(io.BytesIO(mo))
        self.assertEqual(translation.gettext("Hello"), "שלום")
        self.assertEqual(translation.gettext("Other"), "Other")


if __name__ == "__main__":
    unittest.main()
