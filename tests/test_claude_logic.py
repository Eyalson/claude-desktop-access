"""Tests for the panel-finding logic in addon/appModules/claude.py.

NVDA is not installed here, so its modules are replaced with small stand-ins.
The fake tree copies the structure read from the live Claude window with
UI Automation: a toolbar named "Artifacts controls" holds the panel's Close
button, and the window's own Close button has an unnamed parent.
"""

import enum
import importlib.util
import sys
import types
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "addon" / "appModules" / "claude.py"


class Role(enum.Enum):
    WINDOW = 1
    APPLICATION = 2
    BUTTON = 3
    TOOLBAR = 4
    REGION = 5
    GROUP = 6
    DOCUMENT = 7
    EDITABLETEXT = 8
    FEED = 9
    STATICTEXT = 10
    TOGGLEBUTTON = 11


class State(enum.Enum):
    PRESSED = 1
    CHECKED = 2


def _install_stubs():
    def module(name, **attrs):
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        sys.modules[name] = m
        return m

    class _Log:
        def info(self, *a, **k): pass
        def debugWarning(self, *a, **k): pass
        def io(self, *a, **k): pass

    def initTranslation():
        sys._getframe(1).f_globals["_"] = lambda text: text

    module("addonHandler", initTranslation=initTranslation)
    module("api")
    module("appModuleHandler", AppModule=object)
    module("controlTypes", Role=Role, State=State)
    module("core")
    module("gui")
    module("ui")
    module("wx")
    module("keyboardHandler", KeyboardInputGesture=object)
    module("logHandler", log=_Log())
    module("scriptHandler", script=lambda **kw: (lambda f: f))


def _load():
    _install_stubs()
    spec = importlib.util.spec_from_file_location("claude_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


claude = _load()


class Node:
    def __init__(self, role, name="", *children):
        self.role = role
        self.name = name
        self.states = set()
        self.parent = None
        self.children = list(children)
        for child in self.children:
            child.parent = self

    @property
    def firstChild(self):
        return self.children[0] if self.children else None

    @property
    def next(self):
        if self.parent is None:
            return None
        siblings = self.parent.children
        index = siblings.index(self)
        return siblings[index + 1] if index + 1 < len(siblings) else None


def button(name, *children):
    return Node(Role.BUTTON, name, *children)


def nearest(focus):
    """What Ctrl+Shift+J would press for this focus."""
    root = claude.findContentRoot(focus)
    return claude.findNearestClose(focus, claude.collectCloseButtons(root))


def build_window():
    """Returns (window, handles) mirroring the live Claude window."""
    h = {}
    h["window_close"] = button("Close")
    h["artifact_close"] = button("Close")
    h["artifact_doc_inner"] = Node(Role.DOCUMENT, "My artifact")
    artifacts = Node(
        Role.REGION, "Artifacts",
        Node(Role.TOOLBAR, "Artifacts controls",
             button("Comment"), button("Expand"), h["artifact_close"]),
        Node(Role.DOCUMENT, "Artifacts", h["artifact_doc_inner"]),
    )
    h["split_close"] = button("Close split view")
    h["dismiss"] = button("Dismiss")
    h["prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    h["feed_message"] = Node(Role.GROUP, "")
    primary = Node(
        Role.REGION, "Primary pane",
        Node(Role.GROUP, "",
             artifacts,
             Node(Role.FEED, "Chat messages", Node(Role.GROUP, "", h["dismiss"], h["feed_message"])),
             h["prompt"]),
    )
    sessions = Node(Role.TOOLBAR, "Session tools", h["split_close"])
    window = Node(
        Role.WINDOW, "Claude",
        Node(Role.REGION, "Claude",
             Node(Role.REGION, "", Node(Role.REGION, "", Node(Role.REGION, "", h["window_close"])))),
        Node(Role.GROUP, "", Node(Role.REGION, "", primary, sessions)),
    )
    return window, h


class IsPanelCloseButtonTests(unittest.TestCase):
    def test_window_close_is_left_out_by_starting_at_the_page_content(self):
        _, h = build_window()
        root = claude.findContentRoot(h["prompt"])
        self.assertNotIn(h["window_close"], claude.collectCloseButtons(root))

    def test_toolbar_close_is_a_panel_close(self):
        _, h = build_window()
        self.assertTrue(claude.isPanelCloseButton(h["artifact_close"]))

    def test_close_split_view_matches(self):
        _, h = build_window()
        self.assertTrue(claude.isPanelCloseButton(h["split_close"]))

    def test_dismiss_inside_the_chat_feed_is_ignored(self):
        _, h = build_window()
        self.assertFalse(claude.isPanelCloseButton(h["dismiss"]))

    def test_hebrew_close_name(self):
        toolbar = Node(Role.TOOLBAR, "פקדים", button("סגור"))
        self.assertTrue(claude.isPanelCloseButton(toolbar.children[0]))

    def test_other_buttons_do_not_match(self):
        toolbar = Node(Role.TOOLBAR, "Artifacts controls", button("Closer look"), button("Share"))
        self.assertFalse(claude.isPanelCloseButton(toolbar.children[1]))


class DescribeTests(unittest.TestCase):
    def test_plain_close_uses_toolbar_title(self):
        _, h = build_window()
        self.assertEqual(claude.describe(h["artifact_close"]), "Artifacts")

    def test_specific_name_is_kept(self):
        _, h = build_window()
        self.assertEqual(claude.describe(h["split_close"]), "Close split view")


class FindNearestCloseTests(unittest.TestCase):
    def test_focus_inside_artifact_document(self):
        _, h = build_window()
        self.assertIs(nearest(h["artifact_doc_inner"]), h["artifact_close"])

    def test_focus_on_close_button_itself(self):
        _, h = build_window()
        self.assertIs(nearest(h["artifact_close"]), h["artifact_close"])

    def test_focus_in_prompt_finds_nothing(self):
        _, h = build_window()
        self.assertIsNone(nearest(h["prompt"]))

    def test_focus_in_chat_finds_nothing(self):
        _, h = build_window()
        self.assertIsNone(nearest(h["feed_message"]))

    def test_focus_on_window_finds_nothing(self):
        window, _ = build_window()
        self.assertIsNone(claude.findNearestClose(window, claude.collectCloseButtons(window)))

    def test_no_focus_or_no_buttons_finds_nothing(self):
        _, h = build_window()
        self.assertIsNone(claude.findNearestClose(None, [h["artifact_close"]]))
        self.assertIsNone(claude.findNearestClose(h["prompt"], []))


class CollectCloseButtonsTests(unittest.TestCase):
    def test_finds_panel_buttons_only(self):
        _, h = build_window()
        found = claude.collectCloseButtons(claude.findContentRoot(h["prompt"]))
        self.assertIn(h["artifact_close"], found)
        self.assertIn(h["split_close"], found)
        self.assertNotIn(h["window_close"], found)
        self.assertNotIn(h["dismiss"], found)
        self.assertEqual(len(found), 2)

    def test_empty_when_no_panels(self):
        window = Node(Role.WINDOW, "Claude", Node(Role.GROUP, "", Node(Role.EDITABLETEXT, "Prompt")))
        self.assertEqual(claude.collectCloseButtons(window), [])

    def test_budget_stops_the_search_without_error(self):
        window, _ = build_window()
        budget = claude.Budget(maxNodes=2, seconds=5)
        claude.collectCloseButtons(window, budget)  # must not raise


def build_nvda_style_artifacts():
    """Artifacts panel as NVDA shows it: unnamed section wrappers between every named level."""
    h = {}
    h["close"] = button("Close")
    h["doc"] = Node(Role.DOCUMENT, "My artifact")
    h["wrapper_around_two_panels"] = None
    panel = Node(
        Role.REGION, "Artifacts",
        Node(Role.GROUP, "", Node(Role.GROUP, "",
             Node(Role.TOOLBAR, "Artifacts controls",
                  Node(Role.GROUP, "", button("Share"), h["close"])))),
        Node(Role.GROUP, "", Node(Role.DOCUMENT, "Artifacts", Node(Role.GROUP, "", h["doc"]))),
    )
    other = Node(
        Role.REGION, "Secondary pane",
        Node(Role.GROUP, "", Node(Role.TOOLBAR, "Split controls", Node(Role.GROUP, "", button("Close split view")))),
    )
    h["prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    page = Node(Role.DOCUMENT, "Claude Code", Node(Role.GROUP, "", panel, other, h["prompt"]))
    window = Node(Role.WINDOW, "Claude", page)
    return window, page, h


class NvdaStyleTreeTests(unittest.TestCase):
    def test_close_is_found_through_unnamed_wrappers(self):
        _, _, h = build_nvda_style_artifacts()
        self.assertIs(nearest(h["doc"]), h["close"])

    def test_focus_in_prompt_does_not_close_a_sibling_panel(self):
        _, _, h = build_nvda_style_artifacts()
        self.assertIsNone(nearest(h["prompt"]))

    def test_focus_in_the_second_panel_closes_that_panel(self):
        _, page, h = build_nvda_style_artifacts()
        split = [b for b in claude.collectCloseButtons(page) if claude.describe(b) == "Close split view"][0]
        inside_secondary = Node(Role.EDITABLETEXT, "Secondary prompt")
        split.parent.parent.parent.parent.children.append(inside_secondary)
        inside_secondary.parent = split.parent.parent.parent.parent
        self.assertIs(nearest(inside_secondary), split)

    def test_large_artifact_content_is_not_searched(self):
        _, page, h = build_nvda_style_artifacts()
        huge = Node(Role.REGION, "User-generated artifact content",
                    *[Node(Role.GROUP, "item %d" % i, button("Close")) for i in range(50)])
        page.children[0].children[0].children.append(huge)
        huge.parent = page.children[0].children[0]
        names = [claude.describe(b) for b in claude.collectCloseButtons(page)]
        self.assertEqual(names, ["Artifacts", "Close split view"])

    def test_content_root_is_the_document_below_the_window(self):
        _, page, h = build_nvda_style_artifacts()
        self.assertIs(claude.findContentRoot(h["doc"]), page)

    def test_both_panels_found_from_the_content_root(self):
        _, page, _ = build_nvda_style_artifacts()
        names = [claude.describe(b) for b in claude.collectCloseButtons(page)]
        self.assertEqual(names, ["Artifacts", "Close split view"])


def build_two_panes():
    """A split view: each pane has its own prompt, and the artifact panel sits in the primary pane."""
    h = {}
    h["artifact_close"] = button("Close")
    h["split_close"] = button("Close split view")
    h["primary_prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    h["secondary_prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    h["artifact_doc"] = Node(Role.DOCUMENT, "My artifact")
    primary = Node(
        Role.REGION, "Primary pane",
        Node(Role.GROUP, "",
             Node(Role.REGION, "Artifacts",
                  Node(Role.TOOLBAR, "Artifacts controls", h["artifact_close"]),
                  h["artifact_doc"]),
             Node(Role.TOOLBAR, "Split controls", h["split_close"]),
             h["primary_prompt"]),
    )
    secondary = Node(Role.REGION, "Secondary pane", Node(Role.GROUP, "", h["secondary_prompt"]))
    page = Node(Role.DOCUMENT, "Claude Code", Node(Role.GROUP, "", primary, secondary))
    window = Node(Role.WINDOW, "Claude", page)
    return window, page, h


def build_session_toggles():
    """Top toolbar toggles that show and hide panels, with the Session details panel open."""
    h = {}

    def toggle(name, on):
        t = Node(Role.TOGGLEBUTTON, name)
        if on:
            t.states.add(State.PRESSED)
        return t

    h["rail"] = toggle("Session rail", True)
    h["terminal"] = toggle("Terminal", False)
    h["detail_item"] = Node(Role.GROUP, "Environment")
    h["prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    h["stray"] = toggle("Session rail", True)
    toolbar = Node(Role.TOOLBAR, "Session tools", h["rail"], h["terminal"])
    details = Node(Role.REGION, "Session details", Node(Role.GROUP, "", h["detail_item"]))
    other_bar = Node(Role.TOOLBAR, "Somewhere else", h["stray"])
    page = Node(Role.DOCUMENT, "Claude Code",
                Node(Role.GROUP, "", toolbar, other_bar, Node(Role.REGION, "Primary pane", h["prompt"], details)))
    window = Node(Role.WINDOW, "Claude", page)
    return window, page, h


class PanelToggleTests(unittest.TestCase):
    def test_only_open_toggles_in_the_session_toolbar_count(self):
        _, page, h = build_session_toggles()
        found = claude.collectCloseButtons(page)
        self.assertEqual(found, [h["rail"]])

    def test_spoken_name_says_what_closes(self):
        _, _, h = build_session_toggles()
        self.assertEqual(claude.describe(h["rail"]), "Session details")

    def test_focus_inside_the_panel_picks_its_toggle(self):
        _, page, h = build_session_toggles()
        self.assertIs(nearest(h["detail_item"]), h["rail"])

    def test_focus_in_the_prompt_does_not_pick_the_toggle(self):
        _, page, h = build_session_toggles()
        self.assertIsNone(nearest(h["prompt"]))

    def test_diagnostics_list_toggles_and_their_states(self):
        _, page, _ = build_session_toggles()
        text = "\n".join(claude.toggleButtons(page))
        self.assertIn("'Session rail' states=['PRESSED'] open-panel-toggle=True", text)
        self.assertIn("'Terminal' states=[] open-panel-toggle=False", text)

    def test_checked_state_also_counts_as_open(self):
        _, page, h = build_session_toggles()
        h["terminal"].states.add(State.CHECKED)
        self.assertIn(h["terminal"], claude.collectCloseButtons(page))


def build_browser_pane_case():
    """The Browser pane shows its own web page, a second document next to the main Claude page."""
    h = {}
    h["browser"] = Node(Role.TOGGLEBUTTON, "Browser")
    h["browser"].states.add(State.PRESSED)
    h["rail"] = Node(Role.TOGGLEBUTTON, "Session rail")
    h["rail"].states.add(State.PRESSED)
    h["prompt"] = Node(Role.EDITABLETEXT, "Prompt")
    toolbar = Node(Role.TOOLBAR, "Session tools", h["rail"], h["browser"])
    main = Node(Role.DOCUMENT, "My session - Claude Code", Node(Role.GROUP, "", toolbar, h["prompt"]))
    h["web_text"] = Node(Role.GROUP, "Some web page paragraph")
    webview = Node(Role.DOCUMENT, "Readme page", h["web_text"])
    window = Node(Role.WINDOW, "Claude", main, webview)
    h["main"], h["webview"] = main, webview
    return window, h


class BrowserPaneTests(unittest.TestCase):
    def setUp(self):
        self.window, self.h = build_browser_pane_case()

    def test_roots_are_distinct_and_start_with_the_focus_page(self):
        roots = claude.candidateRoots(self.h["webview"], [self.h["prompt"], self.h["prompt"], self.h["web_text"]])
        self.assertEqual(roots, [self.h["webview"], self.h["main"]])

    def test_scan_skips_a_page_without_panels(self):
        roots = claude.candidateRoots(self.h["webview"], [self.h["prompt"]])
        buttons, index, _ = claude.scanRoots(roots)
        self.assertEqual(index, 1)
        self.assertEqual([claude.describe(b) for b in buttons], ["Session details", "Browser"])

    def test_scan_of_the_main_page_stops_at_index_zero(self):
        roots = claude.candidateRoots(self.h["main"], [])
        _, index, _ = claude.scanRoots(roots)
        self.assertEqual(index, 0)

    def test_nothing_found_anywhere(self):
        empty = Node(Role.DOCUMENT, "Empty")
        self.assertEqual(claude.scanRoots([empty]), ([], None, claude.scanRoots([empty])[2]))

    def test_unknown_web_page_preselects_the_browser_panel(self):
        buttons = claude.collectCloseButtons(self.h["main"])
        self.assertEqual(claude.defaultChoice(buttons, False), 1)
        self.assertEqual(claude.defaultChoice(buttons, True), 0)

    def test_at_most_three_roots_are_tried(self):
        docs = [Node(Role.DOCUMENT, "page %d" % i) for i in range(6)]
        for i, doc in enumerate(docs):
            Node(Role.WINDOW, "w%d" % i, doc)
        roots = claude.candidateRoots(docs[0], docs[1:])
        self.assertEqual(len(roots), 3)


def build_browser_with_close():
    """Browser pane open: it has a toggle in the top bar and a Close button in its own toolbar."""
    window, h = build_browser_pane_case()
    h["browser_close"] = button("Close")
    panel = Node(Role.REGION, "Browser", Node(Role.TOOLBAR, "Browser controls", h["browser_close"]))
    h["main"].children[0].children.append(panel)
    panel.parent = h["main"].children[0]
    return window, h


class DuplicateEntryTests(unittest.TestCase):
    def test_toggle_is_dropped_when_the_panel_has_a_close_button(self):
        _, h = build_browser_with_close()
        found = claude.collectCloseButtons(h["main"])
        self.assertEqual(len(found), 3)
        kept = claude.dropDuplicateToggles(found)
        self.assertEqual([claude.describe(b) for b in kept], ["Session details", "Browser"])
        self.assertIn(h["browser_close"], kept)
        self.assertNotIn(h["browser"], kept)

    def test_toggle_stays_when_there_is_no_close_button(self):
        _, h = build_browser_pane_case()
        kept = claude.dropDuplicateToggles(claude.collectCloseButtons(h["main"]))
        self.assertEqual([claude.describe(b) for b in kept], ["Session details", "Browser"])

    def test_different_labels_stay_as_they_are(self):
        _, _, h = build_two_panes()
        self.assertEqual(claude.chooserLabels([h["split_close"], h["artifact_close"]]), ["Close split view", "Artifacts"])

    def test_two_identical_labels_are_told_apart(self):
        window, h = build_window()
        a = button("Close split view")
        b = button("Close split view")
        Node(Role.REGION, "Primary pane", Node(Role.TOOLBAR, "Session tools", a))
        Node(Role.REGION, "Secondary pane", Node(Role.TOOLBAR, "Session tools", b))
        self.assertEqual(claude.chooserLabels([a, b]), ["Close split view, Primary pane", "Close split view, Secondary pane"])


class SplitViewTests(unittest.TestCase):
    def test_prompt_in_main_pane_does_not_close_the_split_view(self):
        _, _, h = build_two_panes()
        self.assertIsNone(nearest(h["primary_prompt"]))

    def test_focus_in_artifact_still_closes_the_artifact(self):
        _, _, h = build_two_panes()
        self.assertIs(nearest(h["artifact_doc"]), h["artifact_close"])

    def test_fast_path_finds_the_artifact_close_from_inside_it(self):
        _, _, h = build_two_panes()
        self.assertIs(claude.findCloseAbove(h["artifact_doc"]), h["artifact_close"])

    def test_fast_path_ignores_the_main_pane(self):
        _, _, h = build_two_panes()
        self.assertIsNone(claude.findCloseAbove(h["primary_prompt"]))


class FastPathTests(unittest.TestCase):
    def test_focus_in_artifact_content_closes_the_artifact_without_reading_the_content(self):
        content_doc = Node(Role.DOCUMENT, "My artifact",
                           *[Node(Role.GROUP, "item %d" % i, Node(Role.STATICTEXT, "t")) for i in range(500)])
        close = button("Close")
        panel = Node(
            Role.REGION, "Artifacts",
            Node(Role.TOOLBAR, "Artifacts controls", close),
            Node(Role.REGION, "User-generated artifact content", content_doc),
        )
        page = Node(Role.DOCUMENT, "Claude Code", Node(Role.GROUP, "", panel))
        budget = claude.Budget(maxNodes=120, seconds=5)
        self.assertIs(claude.findCloseAbove(content_doc.children[3], budget), close)
        self.assertLess(budget.nodes, 25)

    def test_nothing_above_means_none(self):
        _, _, h = build_nvda_style_artifacts()
        self.assertIsNone(claude.findCloseAbove(h["prompt"]))

    def test_found_through_unnamed_wrappers(self):
        _, _, h = build_nvda_style_artifacts()
        self.assertIs(claude.findCloseAbove(h["doc"]), h["close"])

    def test_exhausted_budget_gives_none_without_error(self):
        _, _, h = build_nvda_style_artifacts()
        self.assertIsNone(claude.findCloseAbove(h["doc"], claude.Budget(maxNodes=0, seconds=5)))

    def test_no_focus_gives_none(self):
        self.assertIsNone(claude.findCloseAbove(None))


class ReturnTargetTests(unittest.TestCase):
    def setUp(self):
        _, _, self.h = build_two_panes()
        panel = self.h["artifact_close"].parent.parent  # region "Artifacts"
        panel.location = (400, 50, 300, 600)
        self.inside = Node(Role.DOCUMENT, "inside the panel")
        self.inside.location = (450, 100, 100, 20)
        self.prompt = self.h["primary_prompt"]
        self.prompt.location = (20, 650, 300, 40)

    def test_returns_most_recent_place_outside_the_panel(self):
        history = [self.prompt, self.inside]
        self.assertIs(claude.findReturnTarget(history, self.h["artifact_close"]), self.prompt)

    def test_skips_everything_inside_the_panel(self):
        self.assertIsNone(claude.findReturnTarget([self.inside], self.h["artifact_close"]))

    def test_unknown_panel_position_gives_none(self):
        self.h["artifact_close"].parent.parent.location = None
        self.assertIsNone(claude.findReturnTarget([self.prompt], self.h["artifact_close"]))

    def test_empty_history_gives_none(self):
        self.assertIsNone(claude.findReturnTarget([], self.h["artifact_close"]))


class ScriptTests(unittest.TestCase):
    """Runs the keyboard scripts against the fake tree with NVDA's calls recorded."""

    def setUp(self):
        self.window, self.h = build_window()
        self.spoken = []
        self.pressed = []
        self.logged = []
        self.chosen = []
        claude.ui.message = self.spoken.append
        claude.api.getForegroundObject = lambda: self.window
        self.later = []
        claude.core.callLater = lambda delay, fn, *a: self.later.append((fn, a))
        claude.log.info = lambda *a, **k: self.logged.append(a[0] % a[1:] if len(a) > 1 else a[0])
        for button in (self.h["artifact_close"], self.h["split_close"]):
            button.doAction = lambda b=button: self.pressed.append(b)
        self.module = claude.AppModule()
        self.selected = []
        self.module._chooseAndClose = lambda buttons, selected=0: (self.chosen.append(buttons), self.selected.append(selected))

    def test_focus_in_panel_presses_its_close_button(self):
        claude.api.getFocusObject = lambda: self.h["artifact_doc_inner"]
        self.module.script_closePanel(None)
        self.assertEqual(self.pressed, [self.h["artifact_close"]])
        self.assertEqual(self.spoken, ["Closed: Artifacts"])

    def test_closing_returns_focus_to_where_it_was_before_the_panel(self):
        window, page, h = build_two_panes()
        h["artifact_close"].parent.parent.location = (400, 50, 300, 600)
        h["primary_prompt"].location = (20, 650, 300, 40)
        h["artifact_doc"].location = (450, 100, 100, 20)
        for key in ("primary_prompt", "artifact_doc"):
            h[key].windowClassName = "Chrome_RenderWidgetHostHWND"
            self.module.event_gainFocus(h[key], lambda: None)
        focused = []
        h["primary_prompt"].setFocus = lambda: focused.append("prompt")
        h["artifact_close"].doAction = lambda: self.pressed.append(h["artifact_close"])
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: h["artifact_doc"]
        self.module.script_closePanel(None)
        self.assertEqual(self.pressed, [h["artifact_close"]])
        for fn, args in self.later:
            fn(*args)
        self.assertEqual(focused, ["prompt"])

    def test_fast_path_is_logged_with_its_time(self):
        claude.api.getFocusObject = lambda: self.h["artifact_doc_inner"]
        self.module.script_closePanel(None)
        self.assertTrue(any("fast path in" in line for line in self.logged))

    def test_full_scan_is_logged_with_its_time_and_panels(self):
        claude.api.getFocusObject = lambda: self.h["prompt"]
        self.module.script_closePanel(None)
        self.assertTrue(any("full scan of" in line and "focus in a panel" in line for line in self.logged))

    def test_press_log_holds_no_names(self):
        claude.api.getFocusObject = lambda: self.h["prompt"]
        self.module.script_closePanel(None)
        text = "\n".join(self.logged)
        for name in ("Artifacts", "Close split view", "Prompt", "Session tools"):
            self.assertNotIn(name, text)

    def test_focus_in_the_browser_pane_offers_the_list_with_browser_selected(self):
        window, h = build_browser_pane_case()
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: h["web_text"]
        h["prompt"].windowClassName = "Chrome_RenderWidgetHostHWND"
        self.module.event_gainFocus(h["prompt"], lambda: None)
        self.module.script_closePanel(None)
        self.assertEqual(len(self.chosen), 1)
        self.assertEqual([claude.describe(b) for b in self.chosen[0]], ["Session details", "Browser"])
        self.assertEqual(self.selected, [1])

    def test_browser_with_toggle_and_close_button_is_listed_once(self):
        window, h = build_browser_with_close()
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: h["web_text"]
        h["prompt"].windowClassName = "Chrome_RenderWidgetHostHWND"
        self.module.event_gainFocus(h["prompt"], lambda: None)
        self.module.script_closePanel(None)
        labels = [claude.describe(b) for b in self.chosen[0]]
        self.assertEqual(labels.count("Browser"), 1)
        self.assertEqual(self.selected, [labels.index("Browser")])

    def test_only_browser_open_closes_it_without_a_list(self):
        window, h = build_browser_with_close()
        h["rail"].states.clear()
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: h["web_text"]
        h["browser_close"].doAction = lambda: self.pressed.append(h["browser_close"])
        h["prompt"].windowClassName = "Chrome_RenderWidgetHostHWND"
        self.module.event_gainFocus(h["prompt"], lambda: None)
        self.module.script_closePanel(None)
        self.assertEqual(self.chosen, [])
        self.assertEqual(self.pressed, [h["browser_close"]])
        self.assertEqual(self.spoken, ["Closed: Browser"])

    def test_single_open_toggle_is_closed_from_the_prompt(self):
        window, page, h = build_session_toggles()
        h["rail"].doAction = lambda: self.pressed.append(h["rail"])
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: h["prompt"]
        self.module.script_closePanel(None)
        self.assertEqual(self.pressed, [h["rail"]])
        self.assertEqual(self.spoken, ["Closed: Session details"])

    def test_lost_focus_with_two_panels_offers_a_list(self):
        claude.api.getFocusObject = lambda: self.h["prompt"]
        self.module.script_closePanel(None)
        self.assertEqual(self.pressed, [])
        self.assertEqual(len(self.chosen), 1)
        self.assertEqual(len(self.chosen[0]), 2)

    def test_lost_focus_with_one_panel_closes_it(self):
        self.h["split_close"].parent.children.remove(self.h["split_close"])
        claude.api.getFocusObject = lambda: self.h["prompt"]
        self.module.script_closePanel(None)
        self.assertEqual(self.pressed, [self.h["artifact_close"]])

    def test_no_panels_says_so(self):
        window = Node(Role.WINDOW, "Claude", Node(Role.GROUP, "", Node(Role.EDITABLETEXT, "Prompt")))
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: window.children[0].children[0]
        self.module.script_closePanel(None)
        self.assertEqual(self.spoken, ["No panel to close"])
        # Diagnostics are written only on request, never automatically.
        self.assertNotIn("diagnostics", "\n".join(self.logged))

    def test_failed_press_is_reported(self):
        def boom():
            raise RuntimeError("no action")
        self.h["artifact_close"].doAction = boom
        claude.activate.__globals__["KeyboardInputGesture"] = None  # fallback path must fail safely
        claude.api.getFocusObject = lambda: self.h["artifact_doc_inner"]
        self.module.script_closePanel(None)
        self.assertEqual(self.spoken, ["Could not close: Artifacts"])

    def test_lost_focus_uses_the_last_focus_inside_the_page(self):
        window, page, h = build_nvda_style_artifacts()
        for b in claude.collectCloseButtons(page):
            b.doAction = lambda x=b: self.pressed.append(x)
        claude.api.getForegroundObject = lambda: window
        claude.api.getFocusObject = lambda: window  # NVDA focus fell back to the window
        self.module.event_gainFocus(types.SimpleNamespace(windowClassName="Other"), lambda: None)
        self.module._lastPageFocus = h["prompt"]
        self.module.script_closePanel(None)
        self.assertEqual(len(self.chosen), 1)
        self.assertEqual(len(self.chosen[0]), 2)

    def test_gain_focus_remembers_only_page_objects(self):
        called = []
        page_obj = types.SimpleNamespace(windowClassName="Chrome_RenderWidgetHostHWND")
        other = types.SimpleNamespace(windowClassName="Edit")
        self.module.event_gainFocus(page_obj, lambda: called.append(1))
        self.module.event_gainFocus(other, lambda: called.append(2))
        self.assertIs(self.module._lastPageFocus, page_obj)
        self.assertEqual(called, [1, 2])

    def test_diagnose_logs_the_tree_and_the_close_buttons(self):
        claude.api.getFocusObject = lambda: self.h["prompt"]
        self.module.script_diagnose(None)
        text = "\n".join(self.logged)
        self.assertIn("focus chain", text)
        self.assertIn("close-like nodes", text)
        self.assertIn("Close split view", text)
        self.assertIn("outline of root", text)
        self.assertEqual(self.spoken, ["Diagnostics written to the NVDA log"])


class FakeUIA(Node):
    """Stands in for an NVDA UI Automation object."""


class MouseReadingTests(unittest.TestCase):
    """Reading artifact content under the mouse where NVDA stops at the artifact's document."""

    def setUp(self):
        self.item = FakeUIA(Role.STATICTEXT, "private paragraph")
        self.doc = Node(Role.DOCUMENT, "My artifact title")
        self.content = Node(Role.REGION, "User-generated artifact content", self.doc)
        self.panel = Node(Role.REGION, "Artifacts", self.content)
        self.prompt = Node(Role.EDITABLETEXT, "Prompt")
        Node(Role.DOCUMENT, "Claude Code", Node(Role.GROUP, "", self.panel, self.prompt))
        self.uia_doc = FakeUIA(Role.DOCUMENT, "My artifact title")
        self.uia_doc.parent = self.content
        self.found = self.item
        self.spoken, self.logged, self.passed, self.queued = [], [], [], []

        handler = types.SimpleNamespace(
            clientObject=types.SimpleNamespace(ElementFromPointBuildCache=lambda point, cache: self.found),
            baseCacheRequest=None,
            MTAThreadQueue=types.SimpleNamespace(put_nowait=lambda fn: (self.queued.append(fn), fn())),
        )
        sys.modules["UIAHandler"] = types.SimpleNamespace(handler=handler)
        sys.modules["NVDAObjects"] = types.ModuleType("NVDAObjects")
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=self.makeUIA)
        sys.modules["speech"] = types.SimpleNamespace(
            cancelSpeech=lambda: None,
            speakObject=lambda obj, reason=None: self.spoken.append(obj.name),
        )
        claude.controlTypes.OutputReason = types.SimpleNamespace(MOUSE="mouse")
        claude.log.io = lambda *a, **k: self.logged.append(a[0] % a[1:])
        self.module = claude.AppModule()

    def makeUIA(self, UIAElement=None):
        # Called both as the class in isinstance checks and as the constructor.
        return UIAElement

    def tearDown(self):
        for name in ("UIAHandler", "NVDAObjects", "NVDAObjects.UIA", "speech"):
            sys.modules.pop(name, None)

    def move(self, obj, x=10, y=20):
        self.module._lastMouseCheck = 0.0
        self.module.event_mouseMove(obj, lambda: self.passed.append(obj), x=x, y=y)

    def test_stuck_on_artifact_document_reads_the_element_at_the_point(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        claude_uia = sys.modules["NVDAObjects.UIA"]
        claude_uia.UIA = FakeUIA
        self.found = self.item
        self.patch_constructor()
        self.move(self.doc)
        self.assertEqual(self.spoken, ["private paragraph"])
        self.assertEqual(self.passed, [self.doc])

    def patch_constructor(self):
        # isinstance needs a real class; construction must return the found element.
        original = claude.elementFromPoint

        def elementFromPoint(x, y, timeout=claude.UIA_WAIT_SECONDS):
            return self.found
        claude.elementFromPoint = elementFromPoint
        self.addCleanup(setattr, claude, "elementFromPoint", original)

    def test_outside_artifacts_nothing_is_added(self):
        self.patch_constructor()
        self.move(self.prompt)
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.passed, [self.prompt])

    def test_ui_automation_document_is_left_to_nvda(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        self.patch_constructor()
        self.move(self.uia_doc)
        self.assertEqual(self.spoken, [])

    def test_same_element_is_read_once(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        self.patch_constructor()
        self.move(self.doc)
        self.move(self.doc)
        self.assertEqual(self.spoken, ["private paragraph"])

    def test_container_under_the_mouse_is_not_read(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        self.patch_constructor()
        self.found = FakeUIA(Role.DOCUMENT, "My artifact title")
        self.move(self.doc)
        self.assertEqual(self.spoken, [])

    def test_moves_are_throttled(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        self.patch_constructor()
        self.module.event_mouseMove(self.doc, lambda: None, x=1, y=1)
        self.found = FakeUIA(Role.STATICTEXT, "another line")
        self.module.event_mouseMove(self.doc, lambda: None, x=2, y=2)
        self.assertEqual(self.spoken, ["private paragraph"])

    def test_log_holds_no_page_text(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        self.patch_constructor()
        self.move(self.doc)
        self.assertTrue(self.logged)
        self.assertNotIn("private", "\n".join(self.logged))

    def test_errors_never_break_nvda(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=FakeUIA)
        original = claude.elementFromPoint
        claude.elementFromPoint = lambda x, y, timeout=0: (_ for _ in ()).throw(RuntimeError("COM"))
        self.addCleanup(setattr, claude, "elementFromPoint", original)
        self.move(self.doc)
        self.assertEqual(self.passed, [self.doc])
        self.assertEqual(self.spoken, [])

    def test_element_from_point_waits_for_the_answer(self):
        sys.modules["NVDAObjects.UIA"] = types.SimpleNamespace(UIA=lambda UIAElement=None: UIAElement)
        self.assertIs(claude.elementFromPoint(5, 6), self.item)
        self.assertEqual(len(self.queued), 1)

    def test_element_from_point_gives_up_after_the_timeout(self):
        handler = sys.modules["UIAHandler"].handler
        handler.MTAThreadQueue = types.SimpleNamespace(put_nowait=lambda fn: None)  # never answers
        self.assertIsNone(claude.elementFromPoint(5, 6, timeout=0.01))


class PrivacyTests(unittest.TestCase):
    """Diagnostics may be shared in public bug reports, so they must not carry page content."""

    def test_document_titles_are_not_logged(self):
        self.assertEqual(claude._nodeInfo(Node(Role.DOCUMENT, "My secret session - Claude Code")), "DOCUMENT")

    def test_text_is_not_logged(self):
        self.assertEqual(claude._nodeInfo(Node(Role.STATICTEXT, "a private message")), "STATICTEXT")

    def test_ordinary_buttons_are_not_named(self):
        self.assertEqual(claude._nodeInfo(button("My session title, rename session")), "BUTTON")

    def test_close_buttons_and_panels_are_named(self):
        self.assertEqual(claude._nodeInfo(button("Close")), "BUTTON 'Close'")
        self.assertEqual(claude._nodeInfo(Node(Role.REGION, "Artifacts")), "REGION 'Artifacts'")
        self.assertEqual(claude._nodeInfo(Node(Role.TOOLBAR, "Session tools")), "TOOLBAR 'Session tools'")

    def test_long_names_are_cut(self):
        info = claude._nodeInfo(Node(Role.REGION, "x" * 100))
        self.assertEqual(info, "REGION %r" % ("x" * 40))

    def test_diagnostics_hold_no_page_text(self):
        window, h = build_window()
        h["feed_message"].name = "private chat line"
        secret = Node(Role.STATICTEXT, "private paragraph")
        h["artifact_doc_inner"].children.append(secret)
        secret.parent = h["artifact_doc_inner"]
        logged = []
        claude.log.info = lambda *a, **k: logged.append(a[0] % a[1:] if len(a) > 1 else a[0])
        claude.api.getFocusObject = lambda: h["artifact_doc_inner"]
        module = claude.AppModule()
        module._writeDiagnostics()
        text = "\n".join(logged)
        self.assertNotIn("private", text)
        self.assertNotIn("My artifact", text)
        self.assertIn("'Close'", text)


class BrokenNodeTests(unittest.TestCase):
    def test_node_that_raises_is_not_a_close_button(self):
        class Broken:
            @property
            def role(self):
                raise RuntimeError("COM error")
        self.assertFalse(claude.isPanelCloseButton(Broken()))


if __name__ == "__main__":
    unittest.main()
