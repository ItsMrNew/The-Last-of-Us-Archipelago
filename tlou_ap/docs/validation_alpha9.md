# Alpha 9 validation and remaining gameplay tests

Alpha 9 changes the Python client and distribution. It keeps native ABI 2 and
bridge build `99d6c0864e316360`, previously tested live in alpha 8. No new live
campaign coverage is claimed for the client-only automated work.

## Automated coverage

- Waiting DeathLinks survive a fresh client/adapter and abrupt process exit.
- Seed, team, slot and managed-run identities keep their queues separate.
- Recent duplicate and coalesced burst packets remain suppressed after restart.
- Journal writes happen before native dispatch. A failed write sends no command.
- Interrupted dispatches remain visibly held, never automatically replayed.
- Confirmed natural/remote deaths clear their journal entry; a native rejection
  before application restores a waiting entry. Submission alone is not death proof.
- Recovery backups include the DeathLink journal.
- Tracker snapshots distinguish local progress from server acknowledgements,
  follow enabled check categories, preserve story order and wait for item sync.
- Tracker GUI rendering, filtering, search, mission access and empty-state reset.
- Portable executable runs its smoke tests with no Python on PATH, using an
  isolated state folder and loopback WebSocket server, without attaching to the game.
- Existing native gate, inventory, supply and DeathLink tests remain in the suite.
- Archipelago generation checks cover 83 valid option combinations, extra seeds,
  DeathLink on/off, and a two-player mixed-options world.

The development workspace keeps machine-readable results and artifact hashes
in `dist/validation.json` and `dist/standalone-validation.json`. Native/live evidence remains separately
recorded in `dist/gate-validation.json` with the original build and test scope.

## Still needed before a completed release

These tests need actual gameplay; fixtures cannot certify their outcome.

| Area | Remaining test | Pass condition |
| --- | --- | --- |
| DeathLink | Natural deaths for Joel and Ellie with a linked player | Exactly one outbound death; checkpoint recovery works; no echo loop |
| DeathLink | Receive during an actual cinematic and special scripted sequences | Wait throughout the scene; apply once after stable player control |
| Persistence | Close/reopen the client with a waiting live death | Restore only in the same managed run; apply once after control returns |
| Mission locks | Later chapter transitions, Ellie sections and epilogue | Gameplay blocked while denied; pause/load/menu remain usable; unlock releases cleanly |
| Collectibles | Campaign sweep across all 140 catalog candidates | Correct check identity and chapter; replay/load does not duplicate a check |
| Supplies | Every supported firearm, full inventory and character changes in live play | Appropriate ammo/kit delivery; safe queueing and receipt recovery |
| Multiworld | Full main-story run with another game/player | No progression deadlocks; correct send/receive notifications; Jackson goal acknowledged |
| Distribution | Portable client on a second supported Windows installation | Correct fingerprint rejection/attachment, connection, overlay and recovery behavior |

Weapons and traps remain future features. New check categories require the
user's agreement; alpha 9 retains mission, chapter and collectible checks.
