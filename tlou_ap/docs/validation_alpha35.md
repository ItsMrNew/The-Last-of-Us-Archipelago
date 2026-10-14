# Alpha 35: save ownership guide

Adds a launcher Save guide and an F9-toggleable click-through guide over the
game in windowed/borderless mode. It does not recolour native menu rows or
detect which menu is open. Toggle it off with F9 when finished browsing saves.
F8 is deliberately avoided because the separate test utility uses that key.

Green means this exact save was explicitly confirmed for this managed run.
Red means it was confirmed for another seed/team/slot/run. Amber means ownership
is unknown, not that the save is incompatible. Empty, unreadable or changing
saves are unavailable. Saves are listed newest first, with their game titles.
There is no automatic ownership inference from story progress or being online.

The registry hashes both USR-DATA and params.json. Overwriting a save invalidates
its label; new saves require confirmation in the launcher. Copies of exactly
the same files retain their label. A confirmation rechecks the files and active
run to reject a stale selection. Known foreign saves cannot be reassigned.
Ownership is advisory and never bypasses existing mission/save guards.

Labels are stored in .state/save-guide.json and included in recovery backups.
No game saves or game code are modified. Refresh runs in the background every
five seconds while the guide is open/enabled, with a displayed snapshot time.
The guide must be manually enabled after a launcher restart.

Native build remains 96b4d08a1aa9aec5, ABI 4. Only the client needs restarting
when updating from alpha34. Existing seed, inventory receipts and run ledger
are retained. Progressive Tools remains a separate preview; other QTE tests
and persistent offline play remain parked. Alpha34's ammo threshold still
needs its previously deferred live gameplay test.
