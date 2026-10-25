# -*- coding: UTF-8 -*-
# Claude Desktop Access: NVDA app module for Claude Desktop (claude.exe).
# Copyright (C) 2026 Sontech - Eyal Sonsino.
# This file is covered by the GNU General Public License, version 2. See the file LICENSE.
"""Gives one keyboard shortcut that closes the side panel you are in, and a list of
all open panels when focus is lost. It finds panels by their accessible names, so
it does not depend on hovering or on element ids, which change on every render.
"""

import re
import time

import addonHandler
import api
import appModuleHandler
import controlTypes
import core
import gui
import ui
import wx
from keyboardHandler import KeyboardInputGesture
from logHandler import log
from scriptHandler import script

addonHandler.initTranslation()

VERSION = "0.7.0"
log.info("claudeAccess %s loaded (%s)", VERSION, "scratchpad" if "scratchpad" in __file__.lower() else "add-on")

SCRIPT_CATEGORY = "Claude Desktop Access"

# Accessible names of panel close buttons. "Close split view" also matches.
CLOSE_NAME_RE = re.compile(r"^(close|dismiss|סגור|סגירה)\b", re.IGNORECASE)
PLAIN_CLOSE_NAMES = {"close", "dismiss", "סגור", "סגירה"}
CONTROLS_SUFFIX_RE = re.compile(r"\s+controls$", re.IGNORECASE)

MAX_ANCESTORS = 40
FULL_DEPTH = 40
MAX_REAL_DEPTH = 80
# How far above a close button its named owner (usually the toolbar) may be.
OWNER_LEVELS = 4
MAX_CHILDREN = 300
# Large areas that never hold a panel close button. Skipping them keeps searches fast.
SKIPPED_SUBTREES = {"chat messages", "sidebar", "user-generated artifact content"}
# A Dismiss button inside the chat feed belongs to a message, not to a panel.
FEED_NAMES = {"chat messages"}
# The session's own pane. Being somewhere inside it does not pick a side panel to close.
MAIN_PANE_NAMES = {"primary pane"}

FOCUS_HISTORY = 12

# Some panels have no Close button. A toggle button in the top toolbar shows and hides them,
# and pressing it while it is on closes the panel. Maps the toggle to its panel's name.
TOGGLE_TOOLBARS = {"session tools"}
TOGGLE_PANELS = {"session rail": "session details"}
# Spoken name for a closable item, where the button's own name says little.
SPOKEN_NAMES = {"session rail": "Session details"}

# Translators: announced after a panel was closed. {panel} is its name, such as Artifacts.
MSG_CLOSED = _("Closed: {panel}")
# Translators: announced when no open panel was found.
MSG_NOTHING = _("No panel to close")
# Translators: the prompt above the list of open panels.
MSG_PICK = _("Choose a panel to close")
# Translators: the title of the dialog that lists the open panels.
MSG_DIALOG_TITLE = _("Close a panel in Claude")
# Translators: announced when pressing the close button did not work. {panel} is its name.
MSG_FAILED = _("Could not close: {panel}")
# Translators: announced after the diagnostics command wrote to the NVDA log.
MSG_LOGGED = _("Diagnostics written to the NVDA log")


class Budget:
    """Caps how long and how far one search may run, so NVDA never freezes."""

    def __init__(self, maxNodes=4000, seconds=2.0):
        self.nodes = 0
        self.maxNodes = maxNodes
        self.deadline = time.monotonic() + seconds

    def take(self):
        self.nodes += 1
        return self.nodes <= self.maxNodes and time.monotonic() < self.deadline

    def exhausted(self):
        return self.nodes > self.maxNodes or time.monotonic() >= self.deadline


def _iterChildren(node):
    try:
        child = node.firstChild
    except Exception:
        return
    count = 0
    while child is not None and count < MAX_CHILDREN:
        yield child
        count += 1
        try:
            child = child.next
        except Exception:
            return


def _safeName(node):
    try:
        return (node.name or "").strip()
    except Exception:
        return ""


def _isTransparent(node):
    """An unnamed wrapper element. It does not count as a level when measuring depth."""
    try:
        return not _safeName(node) and node.role != controlTypes.Role.BUTTON
    except Exception:
        return False


def walk(root, maxDepth, budget, skipSubtrees=False):
    """Yield (node, depth) for root and its descendants, depth first, within budget.

    Depth counts named levels only. Unnamed wrappers are walked through for free.
    """
    stack = [(root, 0, 0)]
    while stack:
        node, depth, real = stack.pop()
        yield node, depth
        if depth >= maxDepth or real >= MAX_REAL_DEPTH:
            continue
        if skipSubtrees and _safeName(node).lower() in SKIPPED_SUBTREES:
            continue
        if not budget.take():
            return
        kids = list(_iterChildren(node))
        for kid in reversed(kids):
            stack.append((kid, depth + (0 if _isTransparent(kid) else 1), real + 1))


def _namedOwner(node):
    """Nearest named ancestor within OWNER_LEVELS, usually the toolbar holding the button."""
    parent = node
    for _ in range(OWNER_LEVELS):
        try:
            parent = parent.parent
        except Exception:
            return None
        if parent is None:
            return None
        if _safeName(parent):
            return parent
    return None


def isPanelCloseButton(node):
    """A close button that sits in a named toolbar or panel, a few wrappers above it."""
    try:
        if node.role != controlTypes.Role.BUTTON:
            return False
        if not CLOSE_NAME_RE.match(_safeName(node)):
            return False
        owner = _namedOwner(node)
        return owner is not None and _safeName(owner).lower() not in FEED_NAMES
    except Exception:
        return False


def isOpenPanelToggle(node):
    """A toggle button in the top toolbar that is on, meaning its panel is open."""
    try:
        if node.role != controlTypes.Role.TOGGLEBUTTON:
            return False
        states = node.states
        if controlTypes.State.PRESSED not in states and controlTypes.State.CHECKED not in states:
            return False
        owner = _namedOwner(node)
        return owner is not None and _safeName(owner).lower() in TOGGLE_TOOLBARS
    except Exception:
        return False


def isClosable(node):
    return isPanelCloseButton(node) or isOpenPanelToggle(node)


def describe(button):
    """Spoken label for a close button: its own name if specific, else its owner's."""
    name = _safeName(button)
    if name.lower() in SPOKEN_NAMES:
        return SPOKEN_NAMES[name.lower()]
    if name.lower() not in PLAIN_CLOSE_NAMES:
        return name
    owner = _namedOwner(button)
    title = CONTROLS_SUFFIX_RE.sub("", _safeName(owner)) if owner is not None else ""
    return title or name


PAGE_WINDOW_CLASS = "Chrome_RenderWidgetHostHWND"


def _isWindow(node):
    try:
        return node.role in (controlTypes.Role.WINDOW, controlTypes.Role.APPLICATION)
    except Exception:
        return False


def findContentRoot(node):
    """Topmost ancestor of node that is still page content, just below the window.

    NVDA does not reach Claude's page content by walking down from the window, only by
    walking up from a node inside it, so searches start here.
    """
    top = node
    for _ in range(MAX_REAL_DEPTH):
        try:
            parent = top.parent
            if parent is None or parent.role in (controlTypes.Role.WINDOW, controlTypes.Role.APPLICATION):
                break
        except Exception:
            break
        top = parent
    return top


def _signature(node):
    """Stable identity for a node across separate walks: role, name and screen position."""
    try:
        location = getattr(node, "location", None)
        rect = tuple(location) if location is not None else None
        return (node.role, _safeName(node), rect)
    except Exception:
        return None


def _panelOf(button):
    """The named levels a close button belongs to: its toolbar, then the panel holding it."""
    if isOpenPanelToggle(button):
        return []  # a toggle sits in the top toolbar, not in the panel it controls
    owner = _namedOwner(button)
    if owner is None:
        return []
    levels = [owner]
    node = owner
    for _ in range(MAX_ANCESTORS):
        try:
            node = node.parent
        except Exception:
            break
        if node is None:
            break
        if _safeName(node):
            levels.append(node)
            break
    return levels


def _ancestorNames(node):
    """Lower-cased names of node and its ancestors below the window, mapped to their index."""
    indexes = {}
    for index in range(MAX_REAL_DEPTH):
        if node is None or _isWindow(node):
            break
        name = _safeName(node).lower()
        if name:
            indexes.setdefault(name, index)
        try:
            node = node.parent
        except Exception:
            break
    return indexes


def _ancestorSignatures(node):
    """Signature of node and each ancestor below the window, innermost first, mapped to its index."""
    indexes = {}
    for index in range(MAX_REAL_DEPTH):
        if node is None or _isWindow(node):
            break
        indexes.setdefault(_signature(node), index)
        try:
            node = node.parent
        except Exception:
            break
    return indexes


def findNearestClose(focus, buttons):
    """The close button whose panel is nearest above focus, or None.

    Works from the buttons upward instead of searching down from each ancestor. Pages hold
    thousands of nodes, and reading them through NVDA is slow.
    """
    if focus is None or not buttons:
        return None
    chain = _ancestorSignatures(focus)
    names = _ancestorNames(focus)
    best, bestIndex = None, None
    for button in buttons:
        panelName = TOGGLE_PANELS.get(_safeName(button).lower())
        if panelName is not None and isOpenPanelToggle(button):
            index = names.get(panelName)
            if index is not None and (bestIndex is None or index < bestIndex):
                best, bestIndex = button, index
        for level in _panelOf(button):
            # Focus anywhere in the main pane says nothing about which side panel is meant.
            if _safeName(level).lower() in MAIN_PANE_NAMES:
                continue
            index = chain.get(_signature(level))
            if index is not None and (bestIndex is None or index < bestIndex):
                best, bestIndex = button, index
    return best


def findCloseAbove(focus, budget=None):
    """Fast path: look only inside the named panels that contain focus, nearest first.

    Reading a node through NVDA costs several milliseconds, so this avoids scanning the
    whole page. Returns None when focus is not inside a panel, or when the budget runs out.
    """
    budget = budget or Budget(maxNodes=120, seconds=0.8)
    panels = []
    node = focus
    for _ in range(MAX_ANCESTORS):
        if node is None or _isWindow(node):
            break
        name = _safeName(node).lower()
        if name in SKIPPED_SUBTREES:
            # Everything below this point is page content, not a panel.
            panels = []
        elif name and name not in MAIN_PANE_NAMES:
            panels.append(node)
        try:
            node = node.parent
        except Exception:
            break
    for panel in panels:
        for desc, depth in walk(panel, 2, budget, skipSubtrees=True):
            if isPanelCloseButton(desc):
                return desc
        if budget.exhausted():
            return None
    return None


def scanPage(root, budget=None):
    """One pass over the page for panel close buttons. Returns (buttons, nodes visited)."""
    budget = budget or Budget()
    buttons = []
    for node, _depth in walk(root, FULL_DEPTH, budget, skipSubtrees=True):
        if isClosable(node):
            buttons.append(node)
    return buttons, budget.nodes


def collectCloseButtons(root, budget=None):
    """All panel close buttons under root, in tree order."""
    return scanPage(root, budget)[0]


MAX_ROOTS = 3
BROWSER_NAME = "browser"


def candidateRoots(root, history):
    """The page root of the focus, then roots of other places focus has been. No duplicates.

    The Browser pane shows a web page of its own, which is a separate document from the main
    Claude page. When focus is in it, the panels have to be looked for in the main page.
    """
    roots, seen = [], set()
    candidates = [root] + [findContentRoot(obj) for obj in reversed(history)]
    for candidate in candidates:
        if candidate is None:
            continue
        signature = _signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        roots.append(candidate)
        if len(roots) >= MAX_ROOTS:
            break
    return roots


def scanRoots(roots):
    """Scan roots in order and stop at the first one that has panels.

    Returns (buttons, index of that root, nodes visited). Index 0 is the focus's own page.
    """
    total = 0
    for index, root in enumerate(roots):
        buttons, nodes = scanPage(root)
        total += nodes
        if buttons:
            return buttons, index, total
    return [], None, total


def defaultChoice(buttons, focusInMainPage):
    """Index to preselect in the list. Focus in an unknown web page means the Browser pane."""
    if not focusInMainPage:
        for index, button in enumerate(buttons):
            if describe(button).lower() == BROWSER_NAME:
                return index
    return 0


def dropDuplicateToggles(buttons):
    """A panel can have both a Close button and a toggle in the top bar. List it once."""
    closeLabels = {describe(b).lower() for b in buttons if not isOpenPanelToggle(b)}
    return [b for b in buttons if not (isOpenPanelToggle(b) and describe(b).lower() in closeLabels)]


def chooserLabels(buttons):
    """Spoken labels for the list. Two panels with the same name get their pane added."""
    labels = [describe(b) for b in buttons]
    counts = {}
    for label in labels:
        counts[label.lower()] = counts.get(label.lower(), 0) + 1
    result = []
    for button, label in zip(buttons, labels):
        if counts[label.lower()] > 1:
            levels = _panelOf(button)
            pane = _safeName(levels[-1]) if levels else ""
            if pane:
                label = "%s, %s" % (label, pane)
        result.append(label)
    return result


def _rect(node):
    try:
        location = getattr(node, "location", None)
        return tuple(location) if location is not None else None
    except Exception:
        return None


def _centerInside(outer, inner):
    if outer is None or inner is None:
        return False
    left, top, width, height = outer
    x = inner[0] + inner[2] / 2
    y = inner[1] + inner[3] / 2
    return left <= x <= left + width and top <= y <= top + height


def findReturnTarget(history, button):
    """Most recent place focus was, outside the panel that button closes."""
    levels = _panelOf(button)
    panelRect = _rect(levels[-1]) if levels else None
    if panelRect is None:
        return None
    for obj in reversed(history):
        rect = _rect(obj)
        if rect is not None and not _centerInside(panelRect, rect):
            return obj
    return None


CLOSE_LIKE_RE = re.compile(r"clos|dismiss|סגור|סגירה", re.IGNORECASE)
OUTLINE_MAX_DEPTH = 8
OUTLINE_MAX_LINES = 300
# Diagnostics write names only for parts of Claude's own interface. Documents, headings,
# text, list items and other buttons can carry session titles or page content.
NAMED_ROLES = {"TOOLBAR", "REGION", "LANDMARK", "TOGGLEBUTTON", "TAB", "TABCONTROL"}
MAX_LOGGED_NAME = 40


def _roleName(node):
    role = node.role
    return getattr(role, "name", str(role))


def _loggableName(node):
    """The node's name if it is safe to log, else an empty string."""
    try:
        role = _roleName(node)
    except Exception:
        return ""
    name = _safeName(node)
    if role in NAMED_ROLES or (role == "BUTTON" and CLOSE_LIKE_RE.search(name)):
        return name[:MAX_LOGGED_NAME]
    return ""


def _nodeInfo(node):
    if node is None:
        return "None"
    try:
        name = _loggableName(node)
        return "%s %r" % (_roleName(node), name) if name else _roleName(node)
    except Exception:
        return "unreadable node"


def outline(root, maxLines=OUTLINE_MAX_LINES):
    """Indented role/name lines for the top of the tree, skipping the chat feed."""
    lines = []
    for node, depth in walk(root, OUTLINE_MAX_DEPTH, Budget(maxNodes=2500, seconds=3.0), skipSubtrees=True):
        if len(lines) >= maxLines:
            lines.append("... truncated")
            break
        lines.append("%s%s" % ("  " * depth, _nodeInfo(node)))
    return lines


def toggleButtons(root):
    """Name and state of every toggle button on the page, to check which panels are open."""
    lines = []
    for node, depth in walk(root, FULL_DEPTH, Budget(maxNodes=4000, seconds=2.0), skipSubtrees=True):
        try:
            if node.role != controlTypes.Role.TOGGLEBUTTON:
                continue
            states = sorted(s.name for s in node.states)
        except Exception:
            continue
        lines.append("  %d %r states=%s open-panel-toggle=%s" % (depth, _loggableName(node), states, isOpenPanelToggle(node)))
    return lines


def closeLikeNodes(root):
    """Every button whose name looks like a close button, whatever its parent."""
    lines = []
    for node, depth in walk(root, FULL_DEPTH, Budget(maxNodes=4000, seconds=2.0), skipSubtrees=True):
        try:
            isButton = node.role in (controlTypes.Role.BUTTON, controlTypes.Role.TOGGLEBUTTON)
        except Exception:
            continue
        if isButton and CLOSE_LIKE_RE.search(_safeName(node)):
            try:
                parent = _nodeInfo(node.parent)
            except Exception:
                parent = "unreadable"
            lines.append("  %d %s | parent: %s" % (depth, _nodeInfo(node), parent))
    return lines


def activate(button):
    """Press a button: default action first, then focus and Space."""
    try:
        button.doAction()
        return True
    except Exception:
        log.debugWarning("claudeAccess: doAction failed", exc_info=True)
    try:
        button.setFocus()
        KeyboardInputGesture.fromName("space").send()
        return True
    except Exception:
        log.debugWarning("claudeAccess: focus and space failed", exc_info=True)
    return False


class AppModule(appModuleHandler.AppModule):

    @script(
        # Translators: describes the close panel command in NVDA's Input Gestures dialog.
        description=_("Closes the panel that has the focus, or lists the open panels"),
        category=SCRIPT_CATEGORY,
        gesture="kb:control+shift+j",
    )
    def script_closePanel(self, gesture):
        focus, root = self._focusAndContentRoot()
        started = time.monotonic()
        button = findCloseAbove(focus)
        if button is not None:
            log.info("claudeAccess: fast path in %.2fs", time.monotonic() - started)
            self._closeWith(button)
            return
        roots = candidateRoots(root, getattr(self, "_focusHistory", [])) if root is not None else []
        buttons, rootIndex, nodes = scanRoots(roots)
        buttons = dropDuplicateToggles(buttons)
        focusInMainPage = rootIndex == 0
        button = findNearestClose(focus, buttons) if focusInMainPage else None
        # Counts and times only. Names can carry session titles, see NAMED_ROLES.
        log.info(
            "claudeAccess: full scan of %d nodes in %.2fs; pages %d, panels in page %r; panels %d; focus in a panel %s",
            nodes, time.monotonic() - started, len(roots), rootIndex, len(buttons), button is not None,
        )
        if button is not None:
            self._closeWith(button)
            return
        if not buttons:
            ui.message(MSG_NOTHING)
            return
        if len(buttons) == 1:
            self._closeWith(buttons[0])
            return
        self._chooseAndClose(buttons, defaultChoice(buttons, focusInMainPage))

    @script(
        # Translators: describes the diagnostics command in NVDA's Input Gestures dialog.
        description=_("Writes diagnostics about the focus and the panels to the NVDA log"),
        category=SCRIPT_CATEGORY,
        gesture="kb:nvda+control+shift+j",
    )
    def script_diagnose(self, gesture):
        self._writeDiagnostics()
        ui.message(MSG_LOGGED)

    def event_gainFocus(self, obj, nextHandler):
        # Remember where focus last was inside the page, so a later search can start there
        # even after focus is lost. Storing the object costs nothing; climbing happens on demand.
        if getattr(obj, "windowClassName", "") == PAGE_WINDOW_CLASS:
            self._lastPageFocus = obj
            history = self.__dict__.setdefault("_focusHistory", [])
            history.append(obj)
            del history[:-FOCUS_HISTORY]
        nextHandler()

    def _focusAndContentRoot(self):
        """Focus object and the top of Claude's page content, or None when it cannot be found."""
        focus = api.getFocusObject()
        root = findContentRoot(focus) if focus is not None else None
        remembered = getattr(self, "_lastPageFocus", None)
        if remembered is not None and (root is None or _isWindow(root)):
            root = findContentRoot(remembered)
            if _isWindow(root):
                root = None
        return focus, root

    def _writeDiagnostics(self):
        focus, root = self._focusAndContentRoot()
        lines = [
            "claudeAccess %s: diagnostics (roles, and names of Claude's own controls only)" % VERSION,
            "focus: " + _nodeInfo(focus),
            "content root: " + _nodeInfo(root),
        ]
        lines.append("focus chain (innermost first):")
        node = focus
        for level in range(MAX_ANCESTORS):
            if node is None:
                break
            lines.append("  %d %s" % (level, _nodeInfo(node)))
            try:
                node = node.parent
            except Exception:
                break
        roots = candidateRoots(root, getattr(self, "_focusHistory", [])) if root is not None else []
        found, rootIndex, _nodes = scanRoots(roots)
        found = dropDuplicateToggles(found)
        lines.append("page roots tried: %d, panels found in root %r" % (len(roots), rootIndex))
        for index, candidate in enumerate(roots):
            lines.append("  root %d: %s" % (index, _nodeInfo(candidate)))
        nearest = findNearestClose(focus, found) if rootIndex == 0 else None
        lines.append("nearest close: %r" % (describe(nearest) if nearest else None))
        if root is not None:
            lines.append("panel close buttons under root: %r" % [describe(b) for b in found])
            for b in found:
                lines.append("  %r owner/panel: %r" % (describe(b), [_nodeInfo(x) for x in _panelOf(b)]))
            lines.append("toggle buttons (depth, name, states):")
            lines.extend(toggleButtons(root))
            lines.append("close-like nodes under root, any role (depth, node, parent):")
            lines.extend(closeLikeNodes(root))
            lines.append("outline of root, outside the chat feed:")
            lines.extend(outline(root))
        log.info("\n".join(lines))

    def _closeWith(self, button):
        label = describe(button)
        # Pick where focus should return before pressing, while the panel still exists.
        target = findReturnTarget(getattr(self, "_focusHistory", []), button)
        if activate(button):
            ui.message(MSG_CLOSED.format(panel=label))
            core.callLater(400, self._restoreFocus, target)
        else:
            ui.message(MSG_FAILED.format(panel=label))

    def _chooseAndClose(self, buttons, selected=0):
        labels = chooserLabels(buttons)
        dialog = wx.SingleChoiceDialog(gui.mainFrame, MSG_PICK, MSG_DIALOG_TITLE, labels)
        dialog.SetSelection(selected)

        def callback(result):
            if result == wx.ID_OK:
                index = dialog.GetSelection()
                # Give focus back to Claude before pressing the button.
                core.callLater(150, self._closeWith, buttons[index])

        gui.runScriptModalDialog(dialog, callback)

    def _restoreFocus(self, target):
        """After a panel closes, focus is often lost. Return it to where it was before the panel."""
        try:
            if target is not None:
                target.setFocus()
        except Exception:
            log.debugWarning("claudeAccess: restoring focus failed", exc_info=True)
