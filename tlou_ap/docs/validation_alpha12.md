# Alpha 12 validation

Airhorn Trap is item 19710004. Existing IDs and older seed configurations remain
compatible. New seeds default to 10% of non-progression rewards replaced by
single-blast traps. Timed mode repeats at five-second intervals for 30–120
seconds of controllable gameplay. Update the client and DLL together and restart
the game: this release uses ABI 4.

## Automated checks

- 115 Python tests cover queues, timed delivery, pauses, sequential traps,
  restart recovery, changed-inventory rejection and duplicate protection.
- 42 native test groups cover the bridge command code, including refused,
  confirmed and ambiguous horn effects, player changes, stale heartbeats,
  paused clocks and existing gate, supply and DeathLink behavior.
- Official Archipelago 0.6.9 generation passes all 83 valid check/start options,
  five extra default and five DeathLink seeds, 30 trap-setting combinations and
  a mixed two-player world. Trap classification and item counts are checked.

## Live testing

The exact native build `d058868d7041f63b` loaded into the supported executable.
Tests used the isolated, backed-up save pack and an offline fake inventory;
no real AP server, checks, goals or run ledger were involved.

A queued trap survived the main menu and loading, then emitted six confirmed
AI horn events during a 30-second timer in Outside. Each event was verified in
the game's noise queue with the player handle, position and noise identifier.
Pausing stopped the timer at 16 seconds remaining. Gameplay clocks stopped
under a mission lock while the pause menu remained accessible. Another trap
waited through that lock, pause and the main menu, including a client restart.
Confirmed blasts were not replayed after reconnecting the test client.

A Warehouses encounter comparison on Moderate also passed. Joel remained
crouched without movement or gunfire. After horn delivery, an enemy approached
and attacked him. Reloading the encounter without the trap left Joel undamaged
and crouched in cover for a further 60 seconds. This is targeted evidence for
human enemies in this encounter, not every AI type or difficulty.
See the accompanying gate-validation.json for exact evidence.

## Remaining coverage

Every enemy type, hearing distance, difficulty and scripted encounter needs
broader testing. A hearing event does not guarantee immediate combat; enemies
use their own hearing/search rules. The end of a timed trap stops further noise
without resetting enemy awareness. Live cinematic and special scripted-control
coverage remains incomplete; those deferrals have automated coverage.

The broader campaign limitations from alpha 11 remain: natural outgoing
DeathLink coverage, remaining collectible acquisition paths, complete multiworld
playthroughs and clean-machine installation. This is an experimental alpha.

The horn sound is original synthesized audio. It plays through Windows, outside
the game's volume mixer. Unknown crash-interrupted blasts are held for recovery
instead of being silently discarded or automatically replayed.
