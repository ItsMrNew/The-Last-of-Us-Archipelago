# Alpha40 validation â€” 14 October 2026

This is an experimental alpha, not final-release certification. It combines
alpha38-hotfix9, the corrected resource/trap preview and Progressive Tools.
Native build: `cb7988e78641366d`, ABI 5, supported game 1.1.3.0 AVX2.

## Implemented

- Removed Retire Held Rewards, Future Seed YAML Creator and Campaign Coverage
  from the launcher. Deliveries and Live settings remain. Legacy receipt
  resolution remains readable; ambiguous receipts are not retried automatically.
- Resource items, stronger Shaky Hands, Faulty Flashlight and all nine previous
  hotfixes share one source tree and native build.
- Progressive Tools adds a bonus tool level up to 5, retaining normal toolboxes.
  Absolute journaled targets prevent duplicate upgrades and restore earned floors.
  Existing seeds retain their original item pools; new worlds offer 0â€“5 copies.
- Bridge rejection/constructor cleanup preserves the original diagnostic and
  releases the process handle, including when ctypes views retain an mmap.

## Automated evidence

- 280 Python tests passed, including all four bridge cleanup tests and the
  launcher, managed-run, delivery, trap and tool regressions.
- Actual native command/gate harness passed, including QTE death detection,
  cleanup independent of DeathLink, resource caps, tool targets and hook registers.
- Official AP generation: category/start combinations, DeathLink, Airhorn modes,
  mixed-player settings, resource/trap pools and nine tool combinations passed.
- Official local two-player server test passed: both clients acknowledged all
  41 fixture checks, with useful/trap/filler flags and transfer notifications.
  This used fixture game adapters; it is not a two-run live-save acceptance test.

## Live evidence on this exact binary

An isolated driver used separate journals and no AP connection. Original saves
and the installed managed run were backed up before the test.

- Startup/Continue, Pittsburgh to Bill's Town save loading and checkpoint restart
  completed without a crash or bridge error.
- A gameplay lock held both new trap clocks. Pause opened while locked; releasing
  the lock preserved the open pause menu. The native tool command refused delivery
  during the lock.
- Crafting Cache, 25 Parts, 10 Supplements and a tool target waited while paused.
  On resume each applied once. Repeating the same receipts did not duplicate them.
  Cache respected the three-unit material cap. Tools changed 0 to 1.
- Three Shaky Hands and three Faulty Flashlights stacked to 90 seconds per channel.
  Both reached 66.047 seconds remaining, then held that value through pause,
  journal rebind and mission lock. After checkpoint reload they resumed.
- Reissuing tool target 1 after checkpoint restart left level 1 unchanged.
  That checkpoint retained the level, so this does not establish live restoration
  from an older save with a lower level (covered by automated adapter tests).

## Additional live acceptance with the player

- Ammo at 20/20 refused the supply even with the shotgun at 6/14. Exactly
  10/20 applied the same queued receipt: pistol 20/20, shotgun 13/14. At 9/20,
  holstering refused delivery; switching to the full revolver also refused it.
  Switching back applied once: pistol 19/20 and shotgun 14/14. Repeating the
  applied receipt gave no further ammunition.
- A second tool grant changed 1 to 2. The player confirmed level 2 at the
  workbench and that the corresponding upgrade requirement was satisfied.
- The player confirmed both new effects visible during a 90-second stack each.
  A test incoming death cleared 46.516 seconds of Shaky Hands and 47.203 seconds
  of Faulty Flashlight. One remote death was recorded with no local echo. The
  player confirmed both effects gone and normal camera/controls after reload.
- Abrupt termination of the isolated tester while paused, followed by reconnect,
  restored both 90-second stacks. Full game restart restored them in a new
  process with zero elapsed time in the main menu. Continue loaded Graveyard;
  both timers resumed during controllable gameplay. Test effects were then cleared.

## Player-confirmed acceptance — 14 October 2026

- Switching between two real managed runs: confirmed working by the player.
- Short networked gameplay test on the combined build: confirmed by the player.
- Delete-run UI check: confirmed by the player.

These are player-reported acceptance results, not additional instrumented captures.
The prior full campaign collectible verification remains accepted; another full
playthrough is not required for this checklist.

- Progressive Tools cap: isolated live adapter delivered targets 4, 5, then 5
  from level 3. All receipts settled as applied with no bridge error. The player
  confirmed level 5 and the workbench requirement satisfied.

- Faulty Flashlight initially-off test passed: player confirmed the lamp stayed
  off throughout the 60-second trap and worked normally afterward. Both timed
  effects expired with mask zero and no bridge error.
- Scoped Shaky Hands FAILED: player reported no sight movement when zoomed
  through the rifle scope using a controller. Post-trap recovery worked.
  Unscoped controller sway and shot alignment were subsequently confirmed by
  the player. Accessibility remains unconfirmed.

## Still required before final release

1. Progressive Tools: restoration
   from an older/lower-level save through the full managed-run adapter. Automated
   tests cover those paths; level 2/workbench and duplicate native targets are live-tested.
2. New traps: normal cutscene suspension and accessibility aiming.
   Scoped/controller retest passed on the replacement preview (see below). Menu/lock suspension, stacking,
   player-visible effects, death clearing and journal restart have passed live.

Confirmed historical QTE fixes and no-fix-needed tests remain recorded in prior
validation documents, including Pittsburgh rescue, Firefly escape variants, water,
Cabin Resort, David, Suburbs and the excluded prologue story death.

Persistent offline crash recovery and Left Behind remain intentionally deferred.

## Alpha40 hotfix 1: run deletion

Delete run removes the selected disconnected run from the list after confirmation. Game saves and recovery journals remain intact. Deleted profiles stay removed after restart; deleting the last creates a blank run. Automated checks cover cancellation, connected refusal, stale settings, persistence and failed writes.

## Scoped Shaky Hands replacement — live acceptance

Preview native build `6e6140cbbafa3886` adds scoped camera sway and excludes
the ordinary reticle offset while scoped. Native regressions passed. During a
60-second controller test the player confirmed correct scoped and unscoped
behaviour, switching between them and recovery, with no issues noted. Telemetry
showed expiry to zero, effect mask zero and bridge error zero. This replacement is admitted for alpha40-hotfix2 following the native
regression suite and this targeted live test; remaining acceptance above
is still required for final release. Evidence: `.research/scoped-shaky/live/scoped-test-passed.json`.

- Player confirmed normal in-world toolbox pickup works after AP tool upgrades.

## Final acceptance - v0.1.0

The player confirmed all three outstanding checks passed without issues on
14 October 2026: older/lower-save Progressive Tools restoration, normal cutscene
suspension for Shaky Hands and Faulty Flashlight, and aiming accessibility
settings. These are player-reported results; no new instrumented captures are
claimed. The outstanding checklist above is now closed. See validation_release.md.
