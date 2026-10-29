# Changelog

## [0.8.0] - 2026-10-29

### Added

- NVDA reads the content of artifacts under the mouse: text, headings and list items. Without the add-on, NVDA often stopped at the artifact's frame and said nothing.
- The add-on asks UI Automation which element is at the mouse point and waits for the answer, up to 0.15 seconds, so what is read always belongs to the current point.
- Where NVDA already reads the artifact under the mouse, the add-on does nothing, so nothing is read twice. Each element is read once while the mouse stays on it.

### Notes

- Mouse tracking must be on in NVDA. NVDA+M turns it on and off.
- The NVDA log gets the role of the element that was read, never its text.
- Tested with NVDA 2026.2.

## [0.7.0] - 2026-10-25

First public version.

### Added

- Ctrl+Shift+J closes the panel that has the focus: the artifact panel, the Browser panel, Session details and split views.
- When the focus is outside the panels, Ctrl+Shift+J closes the only open panel, or opens a list of the open panels. When the focus is in the Browser panel, Browser is selected in the list.
- After a panel closes, the focus returns to where it was before you entered the panel.
- NVDA+Ctrl+Shift+J writes diagnostics to the NVDA log.
- Hebrew translation.

### Notes

- The first search looks only inside the panels that contain the focus, about 0.2 to 0.5 seconds on the author's computer. A full scan of the page, about 1.5 to 2 seconds, runs only when that finds nothing.
- The NVDA log gets counts and times on each use. Diagnostics write roles, and names only for Claude's own toolbars, regions, toggle buttons and close buttons.
- Tested with NVDA 2026.2.
