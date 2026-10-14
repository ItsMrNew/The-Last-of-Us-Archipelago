# Alpha 20 validation

Prologue bite failures now produce an outgoing DeathLink. The game's task-failure
event can restart the checkpoint without entering the ordinary player-death
state. The bridge observes only the fingerprinted task-fail call site during
an armed, permitted prologue escape task. It forwards the event unchanged and
deduplicates it against ordinary death detection.

Player tracking uses the game's stable handle and generation instead of the
object address, which can change during movement. A new player spawn still
resets the detector. Airhorn readiness uses the same stable identity.

Native build: `e80002c9e90a1217`, ABI 4, game 1.1.3.0 AVX2.

## Verified in the running game

Tests used backed-up saves and an isolated production-client harness with no
network socket. Actual Archipelago state files stayed byte-for-byte unchanged.
The outgoing packet was captured locally; it was not sent to Renegade.

- Joel's alley bite: one native local death, exactly one outgoing DeathLink
  packet, normal checkpoint reload and working pause afterward.
- Manual Restart Checkpoint: zero outgoing DeathLinks.
- Incoming DeathLink: queued while paused, one confirmed death after resuming,
  normal checkpoint reload, no additional outgoing packet.
- Locked Continue loaded successfully. Gameplay clocks stopped in the alley;
  pause opened. Releasing the mission lock preserved the player's pause.
- Bridge shutdown reported no errors or dropped events.

### Subsequent live-room confirmation — 13 October 2026

After alpha 20 was installed and the existing room reconnected, the player
confirmed that the scripted death at the end of the prologue sent no DeathLink.
The client log records Prologue mission and Hometown chapter completion at
13:22 Australia/Sydney, with no outgoing DeathLink at that transition. This
passes the live finale-exclusion test, in addition to the automated coverage.
This follow-up was in the player's actual run, separate from the isolated
harness tests above.

The player subsequently confirmed the real TLOU/Renegade room sent and received
exactly one DeathLink, with no repeated death.

### Autonomous pre-playthrough regression — 13 October 2026

Used the same native build with production Python network/delivery classes,
an official private AP server, and temporary backed-up saves. Prerequisite
mission history was a fixture; no earned checks or goals were submitted.
Detailed assertions are in `dist/alpha20-preflight-validation.json`.

- Outside loaded locked; gameplay clocks stopped while pause remained usable.
  A server-issued Progressive Chapter Unlock released the gate, preserved an
  open pause menu, and gameplay clocks resumed after closing pause.
- Medkit and ammo gifts waited in pause, then delivered once. One ammo gift
  added half capacity to all nine owned weapons, including holstered guns.
  A subsequent gift capped each weapon correctly.
- Full medkit/ammo inventories retained excess gifts. Those pending gifts
  delivered once after a checkpoint reload restored lower inventory counts;
  already delivered gifts did not replay.
- A fresh game and client process retained a queued DeathLink, supply receipts,
  and exactly 21.875 seconds of an unfinished Airhorn. The DeathLink caused one
  confirmed death after control returned, with zero outgoing echo. Supplies
  delivered after recovery and the Airhorn completed its remaining time.
- A socket reconnect duplicated no rewards, deaths or completed traps.
- A shiv queued at the three-shiv cap survived both game/client restarts.
  Both available inventory fixtures held three shivs, so using one to trigger
  the replacement remains a manual regression check on this build.
- No native errors or dropped events across 8,484 captured observations.
  All 57 original save files and nine AP state files matched their pre-test
  hashes after restoration, before reconnecting the normal client.

## Automated verification

55 native test groups and 166 Python tests passed. Added native cases cover
relocated player objects, generation changes, bite deduplication, remote death
confirmation in either event order, manual restarts, unrelated failure events,
disabled/stale/locked/paused states, and the excluded finale even while the
previous playable task pointer is stale.

The package smoke tests check the actual launcher, both themes, cross-game item
classification and all five bundled horn recordings using isolated state.

## Remaining coverage

Prologue enemy responses to horns, other escape checkpoints, the full campaign
and a complete multiworld playthrough remain pending.
Also retain the live shiv-consumption/replacement check and a natural chapter
transition with cinematic skip. Chapter replay entry does not cover that skip.

Restart the game and client together when installing this update. Keep `.state`
and existing saves. Item IDs, world options and seeds are unchanged.
