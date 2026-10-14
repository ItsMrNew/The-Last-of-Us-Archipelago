# Alpha 24: stable notification rendering

The supplied Airhorn countdown recording shows a briefly blank notification
card. Previously, each countdown change destroyed and recreated every overlay
widget and resized the visible window to one pixel high to measure its contents.

Cards now retain their frames and labels and update only changed text/styles.
Layout reads the natural requested height without collapsing the window. Window
size and placement are changed only when needed. This applies to trap status,
mission locks and item notifications. Queue timing, overflow protection,
click-through styles, focus hiding and the trap effects themselves are unchanged.

Validation: 30 consecutive countdown changes retained the same frame and labels
with zero intervening geometry, placement or hide calls. Alt-Tab hiding, return
and trap completion were checked. The 12 alpha14 regression tests (including
overflow layout and hidden-card timer preservation) and 16 notification/tracker
tests passed. These checks do not replace a full campaign playthrough.

Client-only update. Native build remains `e80002c9e90a1217`, ABI 4. Only restart
the client when updating from alpha 23; preserve saves, `.state` and the seed.
