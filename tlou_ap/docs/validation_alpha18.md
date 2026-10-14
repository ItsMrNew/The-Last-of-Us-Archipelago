# Alpha 18 validation

DeathLink and Airhorn eligibility now follows the prologue's individual tasks.
The 16 allowed tasks cover Sarah's house exploration and Joel's escape on foot.
The opening movie, car ride, crash/QTE sequence, story finale and credits hold
effects. Unknown tasks also hold them. Native scene, pause, loading, living-player,
mission permission and one-second stability checks still apply.

The task-start hooks disarm death detection before scripted work begins, even
when the active-task pointer still names the preceding woods chase. The story
death therefore cannot send an outgoing DeathLink or confirm a queued incoming
one. A dispatch interrupted by a transition is held for recovery rather than
silently consumed or automatically repeated.

The prologue and 20 Years Later no longer inherit supply-inventory restrictions
for effects. Ammo, shivs and medkits still wait for the backpack in Beyond the
Wall. Delivery explanations distinguish gameplay waits from inventory waits.

## Automated verification

- 164 Python tests pass, including prologue delivery reasons and save/mission guards.
- 48 native test groups pass against the production C implementation. New cases
  cover all allowed tasks, excluded tasks, all three finale-start paths with a
  stale active-task pointer, normal death once, remote echo suppression, checkpoint
  rearming, paused/locked clocks, transition uncertainty and 20 Years Later.
- These native boundary tests use fake engine callbacks; they are not a live
  playthrough of the ending.

## Targeted live verification

Exact ABI 4 build: `f818afd2465a624d`, executable 1.1.3.0 AVX2.
The game and AP state were backed up. An offline fixture used production queues
and native adapters without opening a network socket or the real run ledgers.

- Sarah's study became eligible for DeathLink and Airhorns.
- A 30-second Airhorn stayed queued at zero elapsed while paused and mission-locked.
- The lock stopped gameplay clocks 1, 2 and 5 while the other clocks advanced.
  The pause menu opened and closed. Releasing the lock preserved the open pause.
- The horn emitted confirmed native noise pulses after release and stopped its
  timer at the study cinematic. It resumed after checkpoint recovery.
- A DeathLink received during the cinematic stayed queued. Loading the prologue
  checkpoint delivered exactly one death as Sarah. The native remote count was
  one, local count zero, and the receipt cleared only on death confirmation.
- Normal checkpoint reload, Continue, playable readiness and pause recovered.
- All seven real AP JSON state files retained their original SHA-256 during the
  isolated test. The user's queued DeathLink and Airhorn were not consumed.

Evidence is recorded in `dist/gate-validation.json` and the local
`.research/prologue/live` timeline. The lab was stopped and game closed after testing.

## Compatibility and remaining checks

Restart the game and update the launcher and native DLL together. Keep `.state`.
Existing worlds/seeds and item IDs remain compatible; no seed regeneration is
needed. The ABI size is unchanged; a formerly reserved field now reports the
prologue stage. Earlier unsafe bridge builds remain refused.

A live playthrough of Joel's prologue chase, its natural failures and the final
story death still needs confirmation. Enemy responses to horns in that chase,
all campaign transitions and a full multiworld run remain broader test coverage.
The current evidence supports targeted alpha use, not full-campaign certification.
