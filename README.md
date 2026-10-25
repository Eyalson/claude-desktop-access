# Claude Desktop Access

An NVDA add-on for Claude Desktop on Windows. It closes Claude's side panels with one keyboard shortcut, without hovering with the mouse and without searching for the Close button.

Claude Desktop Access is an independent add-on. It is not affiliated with, endorsed by or sponsored by Anthropic. Claude is a trademark of Anthropic, used here only to name the application the add-on works with.

## What it does

### Keyboard commands

| Keys | Action |
| --- | --- |
| Ctrl+Shift+J | Close a panel, see below |
| NVDA+Ctrl+Shift+J | Write diagnostics to the NVDA log |

Other keys can be assigned in NVDA's Input Gestures dialog, under "Claude Desktop Access".

### Which panel closes

| When you press Ctrl+Shift+J | What happens |
| --- | --- |
| The focus is inside a panel: the artifact panel, Session details or a split view | That panel closes |
| The focus is outside the panels, for example in the prompt or the chat, and one panel is open | That panel closes |
| The focus is outside the panels and two or more panels are open | A list of the open panels opens. Enter closes the selected panel, Escape closes the list |
| No panel is open | NVDA announces "No panel to close" |

The Browser panel shows a web page of its own, which is a separate document from the main Claude page, so the add-on cannot tell from inside it which panel the page belongs to. When the focus is in the Browser panel and other panels are open too, the list opens with Browser already selected.

After a panel closes, NVDA announces "Closed" and the name of the panel, and the focus returns to where it was before you entered the panel.

### How it finds the panels

NVDA reaches Claude's page content only by walking up from the focused element, not by walking down from the window, so the add-on starts from the top of the page that holds the focus. A panel is found by its accessible names: a Close button in a named toolbar, such as "Artifacts controls", or a toggle button that is on in the "Session tools" toolbar, such as "Session rail" for Session details. Element ids are not used, because Claude generates new ones on every render.

Reading one element through NVDA takes several milliseconds, so the add-on first looks only inside the panels that contain the focus (about 0.2 to 0.5 seconds on the author's computer). Only if that finds nothing does it scan the page, skipping the chat, the sidebar and the content of artifacts (about 1.5 to 2 seconds).

## Requirements

- NVDA 2026.1 or later. Tested with NVDA 2026.2.
- Claude Desktop for Windows.

## Installation

Download the `.nvda-addon` file from [Releases](https://github.com/Eyalson/claude-desktop-access/releases) and open it. NVDA asks to install it and then to restart.

## Known limits

- The Terminal, Changes and Files toggle buttons have not been tested as a way to close their panels.
- After Session details closes, the focus is not moved back.
- If Claude changes the structure of its interface, the add-on may stop finding a panel. NVDA+Ctrl+Shift+J then shows in the log what NVDA sees.

## What is written to the NVDA log

Each use of Ctrl+Shift+J writes one line with counts and times only. NVDA+Ctrl+Shift+J writes the roles of the elements around the focus, and names only for Claude's own toolbars, regions, toggle buttons and close buttons. It never writes document titles, session names or text from the page.

## Status

The changes of every version are listed in [CHANGELOG.md](CHANGELOG.md).

## Building and testing

You need Python 3. No other packages are needed.

```
python tools/build_addon.py        # runs the tests, then builds dist/claudeAccess-<version>.nvda-addon
python -m unittest discover -s tests
```

The tests run the add-on's logic against element trees that copy the structure NVDA reports for Claude Desktop, with NVDA's modules replaced by small stand-ins.

## Contact and reporting problems

Written and maintained by Eyal Sonsino, [Sontech](https://sontech.co.il/en/). You do not need a GitHub account to reach the author: use the contact form in [English](https://sontech.co.il/en/contact/) or in [Hebrew](https://sontech.co.il/contact/).

For bugs and suggestions you can also open an issue in this repository. Please include your NVDA version, your Claude Desktop version and, if you can, the lines of the NVDA log written by NVDA+Ctrl+Shift+J.

## License

Copyright (C) 2026 Sontech - Eyal Sonsino.

This add-on is covered by the GNU General Public License, version 2. See [LICENSE](LICENSE).
