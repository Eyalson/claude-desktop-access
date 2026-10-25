"""Builds dist/claudeAccess-<version>.nvda-addon from the addon folder.

Run: python tools/build_addon.py
Uses only the standard library. Stops before building if the tests fail, if the
version in the manifest and in appModules/claude.py disagree, or if a translation
is missing. Translations (.po) are compiled to .mo inside the package.
"""

import ast
import hashlib
import re
import struct
import subprocess
import sys
import zipfile
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "addon"
REQUIRED = ("manifest.ini", "appModules/claude.py")


def readManifest(path):
    """Simple key = value reader. Handles quoted and triple-quoted values."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'"""(.*?)"""', lambda m: '"' + m.group(1).replace("\n", " ") + '"', text, flags=re.S)
    values = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
    return values


def parsePo(text):
    """Returns {msgid: msgstr} from the text of a .po file. Untranslated entries are left out."""
    entries, msgid, msgstr, current = {}, None, None, None

    def finish():
        if msgid is not None and msgstr:
            entries[msgid] = msgstr

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            finish()
            msgid, msgstr, current = ast.literal_eval(line[6:]), None, "id"
        elif line.startswith("msgstr "):
            msgstr, current = ast.literal_eval(line[7:]), "str"
        elif line.startswith('"'):
            if current == "id":
                msgid += ast.literal_eval(line)
            elif current == "str":
                msgstr += ast.literal_eval(line)
    finish()
    return entries


def compileMo(entries):
    """The bytes of a GNU .mo file for {msgid: msgstr}, the format NVDA's gettext reads."""
    keys = sorted(entries)
    ids = strs = b""
    offsets = []
    for key in keys:
        keyBytes, valueBytes = key.encode("utf-8"), entries[key].encode("utf-8")
        offsets.append((len(ids), len(keyBytes), len(strs), len(valueBytes)))
        ids += keyBytes + b"\0"
        strs += valueBytes + b"\0"
    keyStart = 7 * 4 + 16 * len(keys)
    valueStart = keyStart + len(ids)
    keyTable, valueTable = [], []
    for idOffset, idLength, strOffset, strLength in offsets:
        keyTable += [idLength, idOffset + keyStart]
        valueTable += [strLength, strOffset + valueStart]
    header = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    return header + array("i", keyTable + valueTable).tobytes() + ids + strs


def messagesInCode():
    """Every string passed to _() in the app module."""
    code = (ADDON / "appModules" / "claude.py").read_text(encoding="utf-8")
    return set(re.findall(r'_\("((?:[^"\\]|\\.)*)"\)', code))


def moduleVersion():
    match = re.search(r'^VERSION = "([^"]+)"', (ADDON / "appModules" / "claude.py").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


def check():
    """Returns (manifest, problems)."""
    problems = []
    manifest = readManifest(ADDON / "manifest.ini")
    for relative in REQUIRED:
        if not (ADDON / relative).is_file():
            problems.append("missing file: addon/%s" % relative)
    for key in ("name", "summary", "description", "author", "version", "minimumNVDAVersion", "lastTestedNVDAVersion"):
        if not manifest.get(key):
            problems.append("manifest.ini has no %s" % key)
    if manifest.get("version") != moduleVersion():
        problems.append("version mismatch: manifest %r, claude.py %r" % (manifest.get("version"), moduleVersion()))
    doc = manifest.get("docFileName")
    if doc and not list((ADDON / "doc").glob("*/" + doc)):
        problems.append("docFileName %s not found under addon/doc/<language>/" % doc)
    if doc and not (ADDON / "doc" / "en" / doc).is_file():
        problems.append("the English help addon/doc/en/%s is missing" % doc)
    for po in ADDON.glob("locale/*/LC_MESSAGES/nvda.po"):
        missing = messagesInCode() - set(parsePo(po.read_text(encoding="utf-8")))
        for message in sorted(missing):
            problems.append("%s has no translation for %r" % (po.relative_to(ADDON).as_posix(), message))
    return manifest, problems


def collectFiles():
    return sorted(
        path for path in ADDON.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".mo")
    )


def build(outDir):
    manifest, problems = check()
    if problems:
        raise SystemExit("Not building:\n  " + "\n  ".join(problems))
    outDir.mkdir(parents=True, exist_ok=True)
    target = outDir / ("%s-%s.nvda-addon" % (manifest["name"], manifest["version"]))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in collectFiles():
            name = path.relative_to(ADDON).as_posix()
            if path.suffix == ".po":
                mo = compileMo(parsePo(path.read_text(encoding="utf-8")))
                archive.writestr(name[:-3] + ".mo", mo)
            else:
                archive.write(path, name)
    return target


def runTests():
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests")], cwd=ROOT)
    return result.returncode == 0


def main():
    if not runTests():
        raise SystemExit("Tests failed. Not building.")
    target = build(ROOT / "dist")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print("Built %s (%d bytes)" % (target, target.stat().st_size))
    print("SHA-256 %s" % digest)
    with zipfile.ZipFile(target) as archive:
        for info in archive.infolist():
            print("  %s (%d bytes)" % (info.filename, info.file_size))


if __name__ == "__main__":
    main()
