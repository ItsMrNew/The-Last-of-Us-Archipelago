# Alpha 14 validation

This is a client reliability update before manual gameplay testing. It retains
alpha 12's native DLL d058868d7041f63b, ABI 4, and alpha 13's features.

## Reproduced and fixed

- Airhorn timing previously counted from reply receipt and scheduled the next
  blast five seconds after acknowledgement. A native reply arriving on the next
  client poll therefore stretched each interval and the stacked duration.
  Timing now uses submission and the native gameplay clock. A delayed-reply
  fixture verifies three 30s traps finish in 90s with 18 submissions at 5s
  intervals. No actual game effects are emitted by that fixture.
- Time crossing a receipt boundary is retained even if confirmation is pending
  or the client restarts. A refused first blast refunds its tentative elapsed
  time; an uncertain blast holds its receipt and everything behind it.
  A long client stall cannot cause a burst of expired catch-up blasts.
- Refreshing observed mission/check progress erased unfinished coverage notes.
  Drafts now survive refreshes and switching rows/scenarios for the lifetime of
  the tools window. Use Record result to save them before closing the window.
- A failed evidence write could appear saved in memory. Only successful atomic
  writes now commit results. Failed settings writes also leave running and
  future-connection preferences unchanged.
- Disconnected settings and delivery rows no longer claim a live effective
  DeathLink state or active trap delivery. Old seeds correctly display 0% traps
  and their default single-blast settings.
- Long notification stacks could extend below the game window. The layout now
  retains overflow transfers in the queue and freezes their unseen display
  time. Persistent lock/trap guidance has priority; normal bursts still show
  two transfers at once where they fit.
- Retired Airhorns are labeled Retired in history, rather than Completed.

## Verification and compatibility

137 Python tests pass, including delayed native replies, interrupted receipts,
legacy journal migration, mixed single/timed traps, evidence drafts, write
failures, disconnected status and a 720p long-card overlay geometry test.
Four initial regression tests reproduced the defects before fixes.
The unchanged native bridge retains its previous targeted live validation;
The subsequent targeted computer-use session is recorded below. It does not
constitute a complete campaign validation pass.

Airhorn journals upgrade from versions 1/2 to version 3 when used by this client.
Existing elapsed time, durations and completed pulse receipts are retained.
Older clients cannot read a version 3 journal: keep using alpha 14 after updating.
Coverage evidence is stored separately for alpha 14. Previous coverage files
remain intact. Keep the client's existing .state folder when updating.

The packaged client is smoke-tested in isolated state, including its tabs,
settings, tracker, journals, resource hashes and loopback WebSocket connection.
See standalone-validation.json and validation.json for artifact hashes and the
final package results. No real run or game save is used by these tests.

## Manual test focus

Use the backed-up offline test environment for injected test effects; the normal
client continues to reject the testing save pack. A full AP test uses the
matching managed-run saves after restoring the original save set.

1. At an unlocked encounter, receive three timed 30s Airhorns. Confirm the
   combined countdown, sounds and enemy response. Pause mid-trap, then resume.
2. Receive supplies and DeathLink during an actual cinematic or scripted-control
   sequence. Confirm they wait and each applies once after control returns.
3. Disable DeathLink with a queued death, reconnect, then enable it. Confirm the
   waiting death is preserved and does not duplicate or echo.
4. Test a locked mission: movement stays blocked, pause/load/main-menu navigation
   works, and release preserves an existing player pause.
5. Receive a burst of five items while a trap/lock card is present. Check all
   transfer cards eventually appear, including at the chosen lower corner.
6. Record evidence and export the diagnostic report. Full campaign transitions,
   collectible variants, final goal, complete multiworld playthrough and clean
   machine installation remain separate release-validation tasks.

## Targeted computer-use session, 12 October 2026

The real game was exercised with the production alpha 14 Python client, native
delivery methods and overlay, using an isolated offline packet fixture and the
active testing save pack. This was not a live AP server connection or another
test of the frozen launcher. No production code or release archive was changed.

- Three timed 30-second Airhorns completed with 90,000 ms of journal elapsed time
  and 18 confirmed native noise events. A 29.128-second pause advanced the native
  gameplay clock by zero; the remaining six seconds stayed unchanged and then
  completed after resuming. Sound loudness and enemy reactions were not assessed.
- Outside was held with the lock notification visible. The pause menu and Load
  Game browser remained navigable. Releasing the lock allowed normal gameplay.
  Releasing while keeping the player pause open was not separately established.
- A health kit waited through the lock/menu state, then increased inventory from
  one to two with one applied receipt when supply readiness returned.
- Queued DeathLink survived disabling and simulated reconnect packet handling.
  Re-enabling while paused retained the death; resuming applied it once, with no
  outgoing echo. The checkpoint recovered normally. This does not test a real
  network disconnect or server reconnect.
- Five long preview cards all became visible, at most two transfers at a time,
  with persistent lock/trap cards at top right. A second five-card burst also
  fitted at bottom right. The observed game window was 1922 by 1112 pixels.
- The 20 Years Later opening was observed, but the test death arrived after
  control returned. It applied normally as a separate second death. Cinematic
  deferral remains inconclusive and needs a longer story scene.

All observed bridge errors and dropped-event counts were zero. Shutdown cleared
the lock, allowed every mission and disabled native test delivery; the game was
left paused. SHA-256 comparison confirmed all 12 protected original save files
and three real AP state files matched the recovery archive. The testing save
pack remains active; original saves were not swapped while the game was running.

See `dist/alpha14-live-validation.json` for the machine-readable result and
`.research/alpha14-live` for screenshots, actions, native events and timeline.
The published alpha 14 ZIP archives remain the same builds; this report is
additional evidence alongside them.

## Capitol Building cutscene test, 13 October 2026

An isolated offline packet fixture sent one Health Kit during the actual Capitol
Building entrance cinematic. The production client kept it queued for 181.307
seconds before marking it applied after playable state returned. Inventory stayed
at one during the observed cinematic and increased to two with exactly one native
grant event. The user confirmed two medkits and normal character control.

No DeathLink was sent in the medkit test. A separate replay of the same cinematic
received one DeathLink packet and retained its receipt in the queued state for
165.600 seconds. It dispatched only after native playable state returned and
confirmed exactly one remote death, with no outgoing echo. The checkpoint
recovered and another 40 seconds of observation showed no repeat death. The user
confirmed the scene finished normally, followed by one death, with movement and
pause working after recovery.

A third replay received three timed 30-second Airhorns during the cinematic.
All 90 seconds remained queued with zero elapsed time and no pulses until native
playable state returned. The first confirmed noise occurred 173.431 seconds after
receipt. The stack completed with 90,000 ms of gameplay elapsed time, 18 confirmed
native noise events and 18 sound notifications at 50% volume. A 95.097-second
observed pause held the native gameplay clock and remaining nine seconds steady.
All three receipts finished, with no traps pending at shutdown.

The user confirmed silence throughout the scene, repeated audible blasts after
it, and completion of the countdown. Near soldiers, the user observed searching
and red or white detection indicators depending on distance. This supports the
enemy-alert behavior in this encounter; other enemy types and hearing distances
were not systematically tested.

These results cover a medkit, DeathLink and timed Airhorns in this cinematic, not
every supply, scripted-control sequence, AP network path or the frozen launcher.

Bridge errors and dropped events remained zero. Test shutdown disabled delivery
and left all missions allowed. The 12 protected original save files and three
real AP state files still match the recovery archive. Release archives and
production code are unchanged. See `dist/alpha14-cutscene-validation.json`,
`.research/alpha14-capitol-cutscene`, `.research/alpha14-capitol-deathlink` and
`.research/alpha14-capitol-airhorn` for the combined result and separate evidence.
