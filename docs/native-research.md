# Native research — local 1.1.3.0 AVX2 build

Historical notes from 12 October 2026. These describe the original read-only research. Current alpha40 native hooks and writes are documented in tlou_ap/docs/validation_alpha40.md, including remaining tests.
The exact fingerprint and activated read offsets are recorded in
`tlou_ap/native/build_1130.json`. Addresses below are module-relative RVAs,
never fixed process addresses. None is permission to call a function with an
unverified ABI.

## Confirmed collectible reads

Global TreasureManager pointer: `0x48a6ee8`.

| Manager offset | Observed meaning |
| --- | --- |
| `0x0000` | Current save's array of treasure SIDs; up to 350 QWORD entries |
| `0x0c50` | Current inventory count, DWORD |
| `0x0c58` | Last acquired treasure SID, QWORD |
| `0x0c60` | 159 DWORD profile collectible flags, each 0 or 1 |

`TreasureManager::AddPickedUp` starts at `0x13664ec`; its profile routine starts
at `0x1366884`. The latter resolves the treasure in the game's 240-byte records
and writes the matching profile flag. The former appends the treasure to the
current inventory and updates count/last SID.

Drafting Notice: native table index 1, SID `d82734ba88a8729d`, The Slums. The
controlled before/after test added only index 1 to the profile, with no removals.
After putting it away, current inventory contained the Boston Q.Z. Map,
Military Pamphlet and Drafting Notice. Wanted Poster was subsequently observed
as an inventory addition. Raw evidence stays local under ignored `.research/`.

Profile flags persist between saves. Inventory changes provide an additional
signal but loading another save also changes inventory. Neither observation
alone supplies managed-run identity or replay-safe acquisition events. A
production bridge should observe the pickup routine on the game thread and
reconcile against a bound run, including already-collected profile treasures,
death, restart and save rollback.

## Candidate completion telemetry

`GameTaskChapterCollection::Create` starts at `0x1cc331c`. It gets the main-story
cache through `0x6866e0`, using the true cache at `0x47fe910`. The observed main
story has 602 task subnodes: count DWORD at cache+0, story index at +4, node
pointers at +0x30. The alternative cache is at `0x4802dd0`; do not substitute it
without checking the caller's semantics.

| Node offset | Interpretation used for candidate reads |
| --- | --- |
| `0x28` | Task SID |
| `0x6a` | Signed completion difficulty, -1 incomplete |
| `0xb8` | Script pointer |
| `0xf8` | Definition pointer; type SID at definition+8 |

Each mission's first task comes from `chapters.bin`. Its exclusive end is the
next mission's first task. Jackson ends at the non-playable COMPLETE sentinel
SID `91ab584921c66c2f`. Chapter collection initializes its minimum difficulty
from the first task, then includes subsequent scripted tasks except
`TaskManagerPlayMovie`. This logic is reproduced as **candidate telemetry** in
`native/tasks.py`. It is not connected to AP reporting.

The early Slums save initially showed Prologue, 20 Years Later and Beyond the
Wall completed at difficulty 2; all later missions were incomplete. The live
Slums → Cargo test passed: index 3 alone changed to completed (difficulty 0),
index 4 remained incomplete, and the user confirmed playing The Cargo. A first
report of being in Cargo was corrected by the user to still being at the docks;
the observer correctly continued to show Slums incomplete at that point. Before
the real transition, 19 of 20 Slums task nodes were marked complete while the
mission stayed incomplete. Proof is in `.research/slums-completion-confirmed.json`.

A complete playthrough, checkpoint restarts, difficulty variations and final
epilogue completion remain to test. This one passing transition does not enable
the production `mission_completion` capability or establish managed-run binding.

The global checkpoint pointer at `0x5f25498`, with title SID count at +`0xda700`,
records entered chapter titles. It retains historical entries and is **not
completion evidence**. `GameSave::RememberChapter` starts at `0x1e25874`.

## Candidate task and supply entry points

`tools/find_script_native.py` resolves FNV-1a name SIDs in the executable's
registration records. The record is `{descriptor pointer, name SID, runtime
hash-chain pointer}`. The descriptor's second QWORD is the callback. Validate
the record in the supported live image before using it; a raw hash occurrence
can otherwise be unrelated data.

| Script native | Callback RVA | Static observation |
| --- | --- | --- |
| `task-subnode-play` | `0x235d78c` | Calls `0x62b2b0` or `0x62b310` |
| `task-subnode-complete` | `0x235d444` | Calls `0x62b2a0`, which requests state 2 through `0x62b1a0` |
| `task-subnode-set-active-continue` | `0x235d154` | Validates continuation and requests task changes |
| `add-player-weapon-reserve-ammo` | `0x19b78d4` | Resolves player/current weapon and calls `0x1db85d8` |
| `set-player-health` | `0x19d9e70` | Changes health through player/component virtual methods |
| `get-player-health` | `0x19be214` | Candidate health query |
| `player-has-health-kit` | `0x19cdad8` | Candidate inventory query; not a delivery function |

`0x62b2b0` queues through `0x5eb620`; `0x62b310` queues through `0x5eb810`.
Both reach `0x5e9e60` with different request kinds. They provide leads for a
chapter gate, but no trace yet proves coverage of save loading, checkpoint
restart or every automatic transition. Dropping a request may strand a script;
a tested deferred/resume path is required before enabling a gate.

Further static tracing found the request consumer at `0x5ebea0`. The scheduler
object has a five-entry request array at +`0x140`, stride `0x38`, and count at
+`0x258`. Requests contain kind DWORD at +0, parent task SID at +8, subnode SID
at +`0x10`, and additional state/timing arguments. The consumer acquires a lock,
resolves each task pair through `0x5ea5e0`, dispatches by kind, then clears the
count. The play branch calls `0x62aa10`. Simply returning halfway through this
function would leak its lock or lose requests; do not patch its loop blindly.

The 602 cached nodes have 602 unique `(parent task SID, subnode SID)` routes.
The parent SID is read via `node+0x120` then +8; the subnode SID is at node+8.
These pairs can be mapped to mission ranges without guessing names. A local
capture is saved in `.research/task-routes.json`; no process pointers are stored
in that file. Consumer coverage and a deferred transition remain unverified.

PE exception-table entries can describe fragments rather than whole functions.
For example the ProcessPlayerTask diagnostic at `0x60580e` belongs to a fragment
whose chained unwind record points back to the actual prologue at `0x6055d0`.
Always inspect chained unwind metadata before selecting a hook prologue.

The public Windows-Game-Patches project's LoadLevelByName signature matches
`0x11b746c` in this build, whose callers use particle-related names. This is
not a validated level loader. Do not install that match as a chapter hook.
Public loader compatibility claims for other game versions do not validate
this executable.

## Original adapter requirements

The following list records the initial research requirements. See the current
implementation and live results below; full campaign coverage remains open.

1. Bind a fresh/resumable game run to seed, team, slot and a durable run ID.
2. Record pickups and completed mission boundaries on the game thread, including
   old profile treasures and inventory variants. Reject activity from other saves.
3. Cover every entry and transition into a locked chapter, with an understandable
   locked-state UI and a reliable continuation when a permit arrives. A hidden
   menu entry alone is insufficient. Never suspend the entire game process.
4. Fail closed while disconnected, while inventory is unsynchronized, or when the
   bridge heartbeat expires. Test reconnects without losing the pending transition.
5. Apply supplies only during safe gameplay, respecting equipped weapons and
   inventory limits. Define full-inventory queuing and character changes.
6. Reconcile reserved/uncertain delivery receipts against game-side state after a
   crash. A client JSON receipt alone cannot make a game effect transactional.
7. Validate final mission completion and report the goal after its checks are
   acknowledged. Then audit the provisional collectible catalog.

## Current native adapter and cinematic completion correction

The runtime uses MinHook 1.3.4 on the fingerprinted AVX2 1.1.3.0 executable.
Hook RVAs are scheduler tick `0x5ebea0`, transition begin `0x62b6d0`, task play `0x62aa10`, treasure addition
`0x13664ec`, and task completion `0x62b1a0`. Copied deferred play arguments are
replayed on the game thread after access arrives, with a fresh SID lookup.
The DLL remains resident after detachment to avoid freeing an active trampoline.

Live supply tests verified +1 health kit through `0x19e02e4` with SID
`1ea95d464b68c80a`, and +3 pistol rounds through `0x1db85d8`. The player confirmed
inventory changes 1 to 2 kits and pistol 5/0 to 6/2. Duplicate receipt tests added
nothing. The Cargo checkpoint restart was held for three seconds and resumed
normally. Checkpoint reload restored checkpoint inventory, including rollback
of a delivered kit; the client intentionally does not replace rolled-back filler.

An official local AP 0.6.9 seed accepted the client. The player started New Game
in Hometown, and the managed ledger recorded live gameplay task completions.
A deliberate client process restart retained the run identity and task evidence.
Old profile and save completion did not award checks before that new run.

At Hometown's ending cinematic, task SID `e548e177d9c789a4` reached native
completion without passing through the hooked completion entry point. Its type
is `TaskManagerCinematic` (`4ff5847ca3b9f2bc`). Requiring every scripted task to
emit a hook event therefore held 20 Years Later even though Hometown's native
aggregate was complete. The player reported an out-of-map scene with cinematic
audio. The client now requires all live gameplay task completions, excluding
movie/cinematic hook evidence, AND the full native mission aggregate, which
still includes cinematics. It never synthesizes a missing completion event.

The corrected client verified 26/26 Hometown gameplay tasks plus native aggregate
difficulty 0. It awarded the mission and chapter checks through the real server,
received two Ammo Supply items, and released the pending 20 Years Later task.
This proves check/reward routing. Releasing the interrupted scene did not restore
gameplay: the player remained under the map and could not pause. The player
closed the game with Alt+F4. A regression test ensures an unfinished cinematic
still prevents a mission check.

Static tracing explains the failed recovery: `0x62b6d0` performs preparation
and cleanup, including `0x627820`, before its nested call to `0x62aa10` with state
11 or 12. Deferring only that nested call interrupts a larger operation. The
revised bridge hooks `0x62b6d0` before preparation, stores its node SID and
continuation SID, and replays the complete operation on the game thread. An
admitted operation keeps permission through its nested Play call even if the
host updates the mask meanwhile. Direct Play entry points retain their existing
deferred path. Three isolated tests execute the actual C gate code against a
fake task cache and callbacks: no preparation before unlock, exactly one replay,
no interruption by mid-operation permission revocation, and copied direct-play
arguments. The revised DLL attached to the restarted game, and Continue entered
20 Years Later with zero pending transitions or native errors. The player
confirmed normal gameplay and pause; the managed run retained both Hometown
checks and its two received ammo rewards. A prolonged automatic-transition hold
through the new early hook is not yet live-tested.

Managed-run binding is a client ledger keyed by seed/team/slot/run, combined with
fresh live evidence. There is no embedded game-save UUID. Players must resume
saves from the same managed run. Full story coverage, save-switch detection,
the collectible variants, character changes and final-goal behavior remain to
be validated in a complete playthrough.

## Automatic graph activation bypass (alpha 6)

The offline alpha 5 run `11436:134362558556986443:654a8504467e06fe` entered The
Slums with allowed mask `536870903` (Slums denied), no pending transition, and
no block/release or Play event. The user also observed no hold. Normal graph
progression therefore bypasses both previous start hooks.

Static tracing of `GameTaskGraphMgr::Update` found `0x6ad070` iterating ready
nodes: it calls readiness predicate `0x62b680`, then automatic activation
`0x626e80`. The latter changes node state from 0 to 2, prepares loading, and
either calls `0x627230` or schedules a loader process; `0x627230` enters state 3
and starts scripts. No Begin/Play call is involved. `0x6ad070` clears its dirty
flag after the loop, so merely refusing the activation would not ensure retry.

Alpha 6 hooks the complete `void (node*)` activation at `0x626e80` before state
changes, records a separate automatic pending kind, and replays on the game
thread after checking the original `bool (node*)` readiness predicate. Both
RVAs have verified anchors. Automatic events use flag `0x40000000`; Begin uses
`0x80000000`. Event 8 reports a stale automatic request discarded on replay.
Automatic graph nodes need not be player tasks, so their events never directly
replace current-player telemetry. Direct Play admission now spans its nested
automatic activation as well. Five new isolated cases cover deferred activation,
stale prerequisites/state, nested admission, native retry/menu cancellation and
heartbeat expiry.

The alpha 6 retest in offline lab `20261012-164046-eb0241f7` recorded automatic
block 107, release 108 and start 109 for SID `0x911bbbc9c1102a1f`. The native
ticks were 283872140 and 283887468: a 15.328-second hold with one release/start.
The user did not notice a gameplay delay. A subsequent three-minute test in
`20261012-165552-68da9e07` showed the countdown while Joel remained controllable
in the market. A read-only snapshot at 117 seconds remaining found all 20 Slums
tasks still in state 0 and one pending start. This verifies script deferral,
not an inaccessible play area. The user then confirmed continued progression
and NPC interactions, followed by a crash picking up Drafting Notice. Event 189
recorded completion of the still-held task; event 190 held the next Slums task.
The last status had two pending starts and 57 seconds remaining. There was no
release event. The live gate test FAILED despite zero bridge error/overflow.

The preserved minidump reports `0xc0000005` at `tlou-i.exe+0x1e731dd`, attempting
to read `0x150` (`rax=0x150`, instruction `mov rcx,[rax]`) in the script interpreter.
This proves the faulting read, not which earlier action supplied the bad value.
No collectible award was recorded in this lab before the process exited.
Evidence is under `.research/crash-20261012-1659` and the lab folder. A reader
found candidate addresses on the stack but did not unwind it; those candidates
must not be presented as a call stack or proof that the bridge was uninvolved.

The host quarantines native build `0ff9de8113ded92c`: normal-run attachment
fails before injection or ledger creation, and lab holds cannot be armed.
This is containment, not a repaired gate. The next design must prevent actual
gameplay/interactions across a locked boundary while leaving menu and client
unlock handling usable. Do not patch the faulting instruction to hide the crash.

## Alpha 7 gameplay-clock gate

An initial prototype injected Prog's pending pause at `+0x62` in per-frame
update `0x431ab0`. Build `c2af8c72f3e532ea` stopped both gameplay and menu input
in Beyond The Wall; the player confirmed this failure. Manual release restored
Options navigation. This build is rejected even by the Offline Test Lab.
Evidence: `.research/alpha7-global-pause-failed.json`.

The replacement `6c8f1b0e5a6d256c` leaves Prog pause unchanged. Its frame callback
updates gate policy and services the client mailbox while gameplay is stopped.
Begin, Play and automatic graph activation finish normal setup, with no partial
task deferral. The clock leaf at `0x20050ac` is `void(clock*, float delta)` and
reads its pause counter at `+0x40` before calculating delta. It calls no callbacks
and does not modify that counter. The hook temporarily adds a pause only when
the counter is zero, calls the original leaf, and restores the original count.
It targets clocks 1, 2 and 5 (`GameContext + 0xd8`, `+0x150`, `+0x2b8`), matching
the normal pause path's array at `0x36a7660`. Other clocks keep advancing.
This avoids persistent counter ownership across save reloads and preserves
existing pauses. Hook anchors and the executable fingerprint remain checked.

Engine hold/release events use flag `0x20000000`; their SID is zero and mission
is one-based. Main-menu task entry clears the latch even if old task telemetry
is stale. The host's allowed mask and five-second heartbeat govern access.
Normal campaign attachment remains disabled pending recovery and transition
validation; block telemetry alone is never sufficient evidence. On October 12,
the player confirmed "Gameplay blocked; menus work" during the repeated
three-minute Beyond The Wall hold. Their 10.67-second recording shows stationary
gameplay with the menu closed, followed by the pause menu opening and responding
while the lock countdown remains visible. It does not show an actual save load
or completed return to the main menu. Initial live Options navigation also
worked while held. Read-only samples found clocks 1/2/5 stationary while all
other clocks advanced. Evidence is preserved in
`.research/alpha7-gameplay-clock-confirmed.json` and
`.research/alpha7-video-review/`. Natural transitions, locked save loading,
return-to-menu recovery, and post-release collectible pickup still require live
validation. All 61 Python tests and 24 native cases pass; fake clock tests verify
ownership and policy, not the game's actual input behavior.

### Loading recovery correction

The same `6c8f1b0e5a6d256c` build subsequently passed quit-to-main-menu while
held, but failed locked Continue: its clock hold stalled asynchronous setup on
a black screen for about 67 seconds until manual release. A task-start event
and completion of its immediate callbacks do not mean the scene is ready.
This build is now rejected even in the lab. Evidence:
`.research/alpha7-clock-loading-failed.json`.

Candidate `616c0b7c5e8cf421` waits for a live player and zero black fade before
holding gameplay clocks. The fade float at `0x8220740` is read by the native
`get-black-fade` callback at `0x233b3c4`, now included in the anchor checks.
The readiness condition is checked every frame so a checkpoint teardown can
finish. The player's existence alone is insufficient: baseline sampling showed
both stale and temporary load actors before the black fade cleared. No fixed
time grace period is used.

On October 12, this candidate passed live Beyond The Wall tests for locked
Continue, Restart Checkpoint while held, pause-menu access after both loads,
release while preserving an open pause menu, and quit to main menu while held.
Read-only clock samples confirmed that after release, gameplay stayed paused
until the Back control closed the menu, then all clocks advanced again. The
game reached a visible scene after each load and recorded no native error or
dropped event. Evidence: `.research/alpha7-scene-ready-recovery.json` and
`.research/offline-lab/20261012-180256-84ec8f32`.

All 61 Python tests and 26 native cases pass. Campaign attachment remains
disabled: the natural Slums boundary, post-release Drafting Notice pickup,
loading a different mission and broader cinematic/mission coverage still need
live validation. The fade/player condition is a tested loading safeguard for
this checkpoint, not proof of every campaign scene's semantics.

## Alpha 7 targeted gate validation completed

The player subsequently confirmed the natural Beyond The Wall to Slums hold
stopped gameplay, the timer's release restored it, and Drafting Notice and
Wanted Poster could both be picked up without issues. The automatic graph
start and clock block share tick `288943500`; release at `289123796` gives
180.296 seconds. No task completion occurred between block and release.
Both collectibles emitted profile and inventory awards after release. Replaying
these four signals twice into an isolated synthetic session produced exactly
two checks, `19713000` and `19713001`. No real server checks were sent. Evidence:
`.research/alpha7-slums-confirmed.json`.

A final live test armed Slums again and used pause -> Load Game -> Save Game 4
(Beyond The Wall). The permitted mission loaded normally while Slums remained
denied, with no pending hold and all gameplay clocks advancing. Native events
80/138/141 record hold, destination start and hold clearance. Evidence:
`.research/offline-lab/20261012-180256-84ec8f32/save-switch-status.json` and
`clocks-1791789771.json` in that folder.

Build `616c0b7c5e8cf421` is now admitted by the normal alpha client. This closes
the targeted gate regression work, not whole-game certification. Full campaign,
later chapter transitions/cinematics, character changes and connected multiplayer
playthroughs remain to be covered. Test-save ownership and save consistency
guards remain enforced when attaching the normal client.

## Final-build checklist: scripted failures and QTE DeathLink

2026-10-14 campaign acceptance update: the user reports a full main-story
playthrough completed and all collectibles working. This is user-confirmed
campaign/collectible coverage; it does not close the remaining scripted-failure
tests. The user is now attempting those remaining cases. In alpha38-hotfix6,
goal reporting does not stop the client polling loop or disable DeathLink;
the completed run can continue testing while connected with DeathLink enabled
and a compatible run save loaded.

Status: **resumed for final-build verification on 2026-10-14**. The user has
confirmed the regional results below; the saving-Ellie Pittsburgh candidate
now also passed isolated hotfix9 validation. All listed cases are closed. User confirmation is distinguished from the
individual instrumented captures documented in the hotfix reports.

These are potential coverage gaps, not confirmed bugs. A static scan of 2,534
scripts found references to `task-fail!`; a reference alone does not establish
that the path executes, kills the player, or bypasses ordinary death detection.
Evidence: `.research/pittsburgh-qte/campaign-failure-audit.json`.

- [x] Bus Depot / Underground Tunnel: user reports fixed on 2026-10-14.
  Instrumented water-fall validation is in alpha38-hotfix6.
- [x] Lakeside Resort: user reports fixed on 2026-10-14; includes the previously
  instrumented hunter grab, Joel stabbing and David strangling fixes.
- [x] University / Science Building: user tested; no fix needed (2026-10-14).
- [x] Pittsburgh / Alone and Forsaken: saving Ellie after the opening ambush.
  Recorded task 93f48466a5692ad5; hotfix9 passed two isolated deaths with normal
  reloads, one outgoing event with DeathLink on and none with it off (2026-10-14).
- [x] Bill's Town / High School Escape: user tested; no fix needed (2026-10-14).
- [x] Pittsburgh: truck-pursuit failures. User tested; no fix needed (2026-10-14).
- [x] Suburbs: user reports fixed on 2026-10-14; earlier sniper knife and
  sniper-cover teammate failure fixes retain their instrumented validation.
- [x] Firefly Lab: user reports fixed with hotfix8 installation (2026-10-14).
  Hotfix7 handles the first gunfire task; hotfix8's three capture variants
  passed isolated retests, one notification per death and live rearming.
  Hotfix8 is now installed. This area-level sign-off is the user's report,
  not a claim that every possible operating-room/escape path was instrumented.

For each candidate, determine whether it is a fatal player outcome, companion
failure, objective failure or scripted story event. Fatal player outcomes should
emit exactly one outgoing DeathLink, recover and rearm after checkpoint reload,
and emit once again on a second failure. Confirm incoming DeathLinks do not echo,
manual checkpoint restarts do not send deaths, and scripted story deaths remain
excluded. Record non-player failures separately for a behavior decision; do not
enable every `task-fail!` reference indiscriminately. Verify success paths do not
send DeathLinks. Fix only confirmed missing coverage and retain test evidence.

Already verified: alpha29 bridge `7077cec8ac0ee9cc` recorded exactly one outgoing
native death event for the Pittsburgh opening broken-glass QTE and reset after
checkpoint reload. That test was isolated from the real server; one connected
repeat remains to verify during the playthrough. Installed alpha29 is connected
to the existing run. Progressive Tools remains a separate preview pending its
previously deferred live test. Evidence: `.research/pittsburgh-qte/live-validation.json`.

Hotel follow-up, 2026-10-13: alpha32 bridge `c40461d60666c46a` adds the separate
`task-fail-if-active!` event callsite (`0x235cb34`) for Hotel Lobby task
`a78b83f44520de9e` only. The production event hook recorded one local death,
normal checkpoint reload, and rearming; the user confirmed restored camera and
controls. The first diagnostic callback recorder omitted native arguments and
interrupted reload; it was detached and excluded from this successful test.
See `.research/hotel-qte/live-validation.json` and
`tlou_ap/docs/validation_alpha32.md`. Other parked QTE cases remain untested.
Expanded static audit: `.research/hotel-qte/campaign-failure-audit.json` scans
both failure functions across 2,534 scripts. The alternate function appears in
the hotel, University rebar script, and a test-only Pittsburgh script. These
references do not prove runtime failure behavior or complete QTE coverage.

## References consulted

- Local Renegade implementation: durable session/outbox and indexed received items.
- Local Generals Zero Hour implementation: mature client/native architecture.
- Local MW2 project: isolated `.apworld` generation verification workflow.
- [Official Archipelago source](https://github.com/ArchipelagoMW/Archipelago): world
  interfaces, protocol types, options and restrictive fill tests.
- [Windows-Game-Patches](https://github.com/illusionyy/Windows-Game-Patches): script
  native lookup research and compatibility leads; no native code copied into this
  project. Its game-version-specific patterns must not be assumed compatible.

The IGN page supplied by the user could not be read because access was blocked.
The current catalog was extracted from the user's local game metadata, not copied
from that guide.

## Alpha34 ammo threshold: pending live verification

Implemented in `.research/ammo-threshold/client`, with shared changes also in
main preview source. Alpha34 bridge `96b4d08a1aa9aec5` only changes the all-owned
ammo gift eligibility predicate; gate/hook behavior is unchanged from alpha32.
56 targeted Python tests and 60 native harness cases pass. Source and standalone
packages pass extracted-bundle verification. No live ammo-threshold test yet.

Before final release, check a drawn weapon at >50%, exactly 50%, and below 50%
of total loaded + reserve capacity; holstering must defer, and empty holstered
weapons must not trigger a gift while the drawn weapon is above half. Confirm
one eligible gift adds half capacity to every owned weapon with caps, while a
menu/cutscene or weapon switch before application leaves an ineligible receipt
queued. If multiple gifts are queued, exactly-half remains eligible, so an empty
20-round gun can receive two gifts (0 -> 10 -> 20), after which further gifts wait.
Do not manually retry an existing uncertain receipt for this test.

Alpha34 installed after the user closed the game on 2026-10-13. Verified all
1,056 packaged files and preserved all 12 run-state files byte-for-byte during
installation. Backup: `.research/ammo-threshold/installed-before-alpha34.zip`.
The new native bridge will load on the next game launch and client connection;
live ammo-threshold verification remains pending.


## Alpha35 save guide (2026-10-14)

Stable source: `.research/save-affinity/client`. Installed to the Desktop/1
client with all 1,057 package checksums verified and 13 state files preserved.
Backup: `.research/save-affinity/installed-before-alpha35.zip`.
Native bridge remains alpha34 build `96b4d08a1aa9aec5`; no game restart needed.
The client reconnected the existing run with 107 checks and 9/12 chapters.

26 targeted tests pass: 14 save ownership, 3 save guide UI, 5 tracker UI and
4 recovery tests. Both extracted packages pass the standalone/source smoke
checks. Live visual checks verified the guide over the paused game, hide on
Alt-Tab, non-activating menu use, and F9 show/hide after installation. F8 was
changed to F9 before release to avoid the separate test utility's shortcut.

This is an advisory overlay and launcher list, not recolouring native menu
rows. It needs manual F9 toggling and explicit confirmation of each new save.
Metadata/payload fingerprints invalidate green labels after overwrite; the
registry cannot prove descent from a previously confirmed checkpoint. No
save writes or native UI hooks were introduced. Unknown does not mean foreign.
The user confirmed the original Suburbs autosave and Save Game 18; the autosave
subsequently changed and correctly returned to amber, while Save Game 18 stayed
green. Do not relabel the newer autosave without new confirmation.

Direct native row colouring and automatic load/save ownership remain future
work. Static research found Menu2::DataSourceSaveGames::GetItemData at
0x272ba98 with title data in returned array index 5, but no hook was installed.
Do not distribute extracted game GUI research assets in save-affinity.


## Alpha36 automatic disk save compatibility (2026-10-14)

Stable source `.research/save-progress/client`, installed over alpha35 with
1,059 package checksums verified and all 13 existing state files preserved.
Backup `.research/save-progress/installed-before-alpha36.zip`. Source and
standalone archives pass extracted smoke tests, including the new task profile.
Native build unchanged; launcher restarted and reconnected existing run.

The save payload is structured serialized data, not compressed task data.
A bounded read-only parser matches two complete arrays of all 602 main-story
SIDs, 72-byte records, marker 01010101000000000600000004000000 at SID+32,
and signed difficulty at SID+24. Both full arrays must agree. Magic 60050.
Static script/type metadata is derived from the fingerprinted executable's
live task cache; script-presence also matches the early historical snapshot.
No raw save files, extracted GUI binaries or game asset payloads are packaged.

The parser's 29 mission values for CURRENT AUTOSAVE match live task telemetry;
static REQUIRED task sets exactly match the native adapter. All 21 local saves
parse, with 17 compatible / 4 incompatible against the current run. All 66
save-related files unchanged by validation. Scan time 0.17 seconds. Report:
`.research/save-progress/live-validation.json`. 46 targeted tests pass, including
all 30 campaign completion boundaries x 7 difficulties, malformed/unsupported
formats, inconsistent copies, automatic reclassification on overwrite/ledger
advance, ownership precedence, live guard, UI themes and recovery regressions.

Green now means passes the progress guard, NOT confirmed run ownership. Older
foreign saves can pass. Red means progress rejected or known foreign ownership;
unreadable/unsupported data stays unverified. New saves need no confirmation.
Scanner and live guard share progress_compatibility_error; observation never
awards checks or bypasses locks. Native UI row colouring remains unimplemented.


## Alpha37 managed run selection — 2026-10-14

Stable source: `.research/run-selector/client`. Added run-profiles.json index,
existing-ledger discovery, per-run server/slot and editable descriptions.
Selector rejects live workers, clears departed UI queues/tracker/save-guide,
restores original ledger selection, and never reuses passwords. Native owner
guard remains: restart game to change runs; separate manual saves required.
41 targeted tests pass, including A-to-B-to-A ledger/session preservation.
Both packaged source/frozen smoke tests and all checksums pass. Layout and
existing-run choices visually checked. Installed 7 changed files with backup;
all 13 prior state files preserved. Native build unchanged (96b4d08a1aa9aec5).
Game was closed; launcher reopened with original run selected, disconnected.
Actual two-room gameplay switching and existing deferred gameplay tests remain
pending. Root preview remains unshipped Progressive Tools.


## Alpha38 client review — 2026-10-14

Stable source `.research/code-review/client`. Four verified failure-path fixes:
run-selection persistence before UI mutation, adapter cleanup on startup/shutdown
exceptions, transactional notification-history binding, and guaranteed save-scan
error completion. Seven new regressions; 246 Python tests passed. Old YAML UI
fixture now names its test slot, avoiding a modal on blank new-run defaults.
Source and standalone extracted smoke tests passed (98/1061 hashes verified).
Installed 7 changed files with backup `installed-before-alpha38.zip`; all 14
existing state files unchanged. Game closed; launcher reopened disconnected on
original selected run. Native ABI/build, AP world and game saves unchanged.
Parked native/QTE and live two-room run-switch acceptance remain pending.


## Resource items and timed traps preview — 2026-10-14

Source `.research/resource-items/client`, native build d03429926f61a01e, ABI5. Candidate implements resources, aiming-offset hook, player-only render-intensity argument hook, separate leased native clocks and durable client journals. Detailed static evidence: `.research/resource-items/research-notes.txt`. Actual MinHook trampoline test includes the exact VEX prologue decoder extension. Automated tests pass; no candidate DLL was injected, no live grants occurred, and alpha38 remains installed. Required next: launch game normally, read-only inventory/flashlight inspection, then controlled isolated live baseline and feature checks from `dist/VALIDATION-alpha39-preview.md`. Normal AP connection deliberately refuses the unadmitted build.


## Alpha38 hotfix7: Firefly Lab escape — 2026-10-14

The user reproduced fatal soldier gunfire while Joel carries Ellie. The safe
wrapper recorder captured mission index 27/task 1c9a2ef9f564b7ef/caller 235c9ae
with DeathLink armed but no counter increment. The targeted fix preserves all
prior cases. Native bdd56b87a7ef922c passed native regressions and 246 Python
tests. Isolated live retest produced one native type-9 event and one local
notification, zero remote events/errors, normal reload (user-confirmed), and
live rearming. No isolated test death reached Renegade. This closes that escape
failure only; other operating-room/escape failure variants remain unverified.

Installed alpha38-hotfix7: 1,068 files verified, existing .state unchanged,
backup and reports under .research/firefly-escape and dist. The source and
standalone archives passed build verification and the frozen self-test.
The alpha39 preview source incorporates the fix (dad81bb760479ba5) and passes
native tests but remains unadmitted; preview packages were not rebuilt.

Observed during testing: connecting the old launcher to the isolated newer
bridge correctly rejected the mismatched version, but cleanup also logged
BufferError: cannot close exported pointers exist in Bridge.close. Restarting
the game/client clears this test setup mismatch. Cleanup diagnostic is a
separate follow-up; hotfix7 only changes the captured escape failure detector.


## Alpha38 hotfix8 installed — 2026-10-14

Stable source: .research/firefly-variants/client. All three captured NPC variants
(Ellie grabbed, Joel shot) used mission index 27/task 89a12fd5192d1361/caller
235c9ae with the old detector armed but unchanged death count. Native build
402f75f8c0acb00d adds this exact task and checkpoint restart alongside hotfix7's
1c9a2ef9f564b7ef. Native regressions cover both tasks, wrong mission/event/task/
caller exclusions, menu/lock/disconnect, duplicates, rearming and remote echoes.
246 Python tests and frozen standalone self-test passed.

Three isolated live attempts produced exactly three native type-9 events and
three local notifications, one per attempt, with no native errors or remote
deaths. Each reload rearmed live, including after the third. User confirmed all
three attempts. No isolated test deaths reached Renegade. Installed 1,069 files
with hashes verified and .state preserved. Reports, source and standalone ZIPs
are copied to dist; prior installation backup is under .research/firefly-variants.

Preview source also incorporates this fix (131d69156041a466), passes native
regressions and remains unadmitted. Preview ZIPs were not rebuilt.


## Alpha38 hotfix9 installed - 2026-10-14

Source `.research/trap-death/client`, native build `5384fa366f56dea7`.
Pittsburgh Ellie rescue failure now emits one DeathLink. Confirmed local or
received deaths clear the active Airhorn stack independently of DeathLink
preferences; unstarted queues and uncertain held receipts remain preserved.
Cancellation is journaled before event acknowledgement and survives reconnect.
Native cleanup uses event 12, distinct from horn pulse telemetry (event 11).
The initial candidate with an event-ID collision was rejected, never installed.

Two isolated live attempts each cleared three stacked timed Airhorns with
86/87 seconds remaining. The first emitted one DeathLink; the second, with
DeathLink disabled, emitted none. Reloading each journal kept zero traps.
Both failures and checkpoint reloads were user-confirmed normal; native error 0.
Evidence: `.research/trap-death/live-validation.json` and `fixed-test-v2.jsonl`.
256 stable Python tests and native regressions passed. The separate alpha39
preview passed 266 tests with Shaky Hands/Faulty Flashlight stack cleanup;
its binary remains unadmitted and is not installed by this hotfix.

All listed QTE cases now have user or instrumented sign-off, as distinguished
above. This does not certify every unobserved failure path or final release.
Ammo half-capacity and two-room switching remain separate acceptance work.
