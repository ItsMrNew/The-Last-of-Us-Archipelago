# Alpha 13 validation

This release adds client tools: delivery status/history, live preferences, future
seed YAML export, and campaign coverage recording with diagnostic export.
It retains the alpha 12 native DLL, ABI 4, build d058868d7041f63b. No new native
hooks or enemy behavior changes are introduced.

## Changes and semantics

- Deliveries list each supply, chapter permit, Airhorn and waiting DeathLink.
  Reasons come from receipt journals and read-only native telemetry. Where the
  bridge cannot distinguish pause, cinematics and scripted control, the UI says
  so rather than inventing a precise cause. Full inventories keep their items.
- DeathLink offers Follow YAML (default), Enabled and Disabled, updating the AP
  subscription during a connection. Disabling preserves waiting deaths. An
  already dispatched uncertain death remains held for recovery as before.
- Live Airhorn preferences offer Follow YAML, Single blast or Timed (30–120s).
  New receipts capture these preferences durably. Existing queued/active traps
  retain their duration; reconnecting or changing settings cannot retime them.
- Consecutive timed traps display one summed countdown and progress without an
  extra polling gap at receipt boundaries. Three 30s traps produce 90s and 18
  blasts. Timers use native controllable-gameplay time. Single blasts and held
  uncertain receipts interrupt a timed block; nothing bypasses a held receipt.
- Airhorn volume 0–100 scales the mod WAV, without changing other app mixers.
  Muting the sound does not stop AI hearing events. Four notification corners
  and 2–30s display duration are saved locally. Two transfer cards show at once;
  five items display in batches of two, two and one. Alt-Tab freezes display time.
- Trap percentage belongs only to future-seed YAML export. There is no runtime
  percentage or activation-chance control. Active slot data is never rewritten.
- Coverage provides 29 mission rows, 12 chapter rows, 140 collectible rows and
  one final-goal row. Each has named scenarios. Results require evidence notes,
  are saved by client/native/catalog version, and do not submit checks or goals.
  Observed progress never automatically passes a test. Historical test evidence
  is not automatically promoted to this build’s coverage journal.
- Diagnostic JSON uses an allowlist and includes coverage notes, delivery source
  names, settings and compact runtime status. Passwords, server addresses, raw
  logs and game save files are excluded. Review your notes before sharing.

## Verification

125 Python tests pass, including new stacked-clock, migration, pause/restart,
live DeathLink protocol, sound amplitude, five-notification FIFO, YAML validation,
coverage persistence/export and Tk integration tests. Existing gate, native
mailbox, supply, DeathLink, tracker and recovery tests continue to pass.
The standalone smoke test exercises all four new tools tabs in isolated state.
See standalone-validation.json for the final packaged smoke-test result and hash.

No live AP checks, real-run journals or game saves are used by these tests.
Alpha 12’s targeted native live validation still applies to the unchanged DLL.
Full campaign, natural outgoing DeathLink, additional collectible acquisition
paths, broader enemy/cinematic coverage, complete multiworld playthrough and a
clean-machine installation remain release-validation tasks. The coverage panel
helps record these tests; it does not imply they have already passed.
