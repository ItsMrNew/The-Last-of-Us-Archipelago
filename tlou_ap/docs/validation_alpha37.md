# Alpha 37: managed run selector

The launcher has a Managed run selector and a short editable description shown
beside the run ID. Each run remembers its server address and slot name. Use
Save beside Description to keep edits. New managed run creates an empty entry;
enter its new room/slot details before connecting. Passwords are never stored
and are cleared when changing the selected run.

Existing plain run ledgers are discovered automatically; recovery copies and
test-control sidecars are excluded. Room details from the old launcher migrate
to the previously selected run only. Unknown older room addresses are not guessed.
Unconnected new entries persist across launcher restarts. The run directory is
stored in .state/run-profiles.json and included in recovery backups alongside
launcher selection, run ledgers, sessions and save ownership notes.

Switching is available after disconnect completes. The native bridge still
permits one run per game process, so restart the game before connecting a
different run. Returning to a previous run restores its original run UUID,
seed/slot binding, checks, indexed item receipts and effect journals. A wrong
seed/slot is still rejected. Old tracker state, queued notification cards,
pending UI actions and save-guide status are cleared on selection changes.
Server/slot fields and run selection are disabled while connected/connecting.

Keep a separate manual game save for each run before switching. The game has
a shared autosave slot; the selector does not create, swap or restore game saves.
For a new run, restart the game, select the new run, connect its room, and start
New Game in Hometown. To return, disconnect, restart the game, select the old
run, connect, then load its manual save. Progress-compatible green save labels
remain an advisory check, not proof that a save originated in the selected run.

Native bridge remains 96b4d08a1aa9aec5, ABI 4. Installing from alpha36 only needs
a launcher restart; changing the selected run requires the game restart above.
Actual two-room campaign play remains a live acceptance test. Isolated tests
cover A-to-B-to-A selection, independent session/ledger files, migration,
metadata persistence, connected-switch rejection, queued UI cleanup and backups.
Progressive Tools and the existing deferred gameplay/QTE tests remain parked.
