# Alpha39 preview: resources and timed traps

This is a development preview, not the installed stable release. Alpha38 remains installed.
The candidate native bridge is deliberately not in the normal client's live-admission list.
Use Offline Test Lab.cmd in the standalone preview for validation; restart the game afterward.
The lab grants only when its item buttons are pressed. Use a disposable test save for supplies.

## Implemented

- Crafting Cache: up to one full unit of rag, alcohol, blade, binding, explosive and sugar.
  The game stores each full material as four quarters; inventory caps are 12 quarters.
  Full materials are skipped. An entirely full cache waits; a partially applied native
  batch is held as uncertain and never automatically duplicated.
- Workbench Parts: up to 25, capped at the native inventory maximum (9999).
- Supplement Stash: up to 10, capped at the native inventory maximum (9999).
- Supplies wait for the persistent backpack, controllable gameplay and inventory space.
- Shaky Hands: 30 seconds of additional reticle/aim offset.
  Current tuning uses triple the original preview displacement and 25% faster
  mixed oscillations (reference-plane bounds: +/-75 horizontal, +/-51 vertical).
- Faulty Flashlight: 30 seconds of smoothly varying brightness. Does not toggle the light
  or change the player's controller settings; ordinary render updates restore intensity.
- Same-kind traps stack (three copies = 90 seconds); different traps can overlap.
- Separate native playable clocks stop for menus, cutscenes, death, loading, locked missions
  and missing client leases. Journals preserve remaining time through reconnect/restart.
  A crash before the latest journal write may conservatively repeat a fraction of a second.
- Resource rewards are useful; both new traps carry Archipelago trap classification.
- New YAML toggle for resource supplies (on by default for new YAMLs), separate trap
  percentages (off by default), total of all three trap percentages limited to 100.
- Old slot data remains byte-for-byte compatible and old item IDs are unchanged.
  ID 19710005 remains reserved for the separate Progressive Tools prototype.
- Delivery list, summary and trap notification include the new rewards.
- Offline lab has resource buttons, stackable trap buttons, countdowns and Stop Both.

## Automated verification

252 Python tests passed, including durable trap journal, stacked/overlapping clocks,
old schemas, IDs, resource capacity, reconnect and failed journal writes.
Actual native C harness passed existing regressions and new resource/timer cases.
A real MinHook detour on an isolated VMOVSS function passed, checking that the narrowly
scoped VEX decoder extension preserves its output and return pointer.
Official Archipelago checkout: 83 valid base option combinations, additional default,
DeathLink/Airhorn mixes and new resource/trap pools passed generation, reachability,
classification and item-count checks.

## Required live checks before admission/install

1. With effects disabled: normal movement, aiming, pause menu, checkpoint restart,
   mission hold/release and collectible pickup must still work on this exact DLL.
2. Crafting Cache displays one full unit each; parts +25 and supplements +10; inventory
   caps, pre-backpack refusal, menu/cutscene queue and duplicate receipt query.
3. Shaky Hands visibly changes aiming and shot direction, then returns to normal.
   Check mouse/controller input, scoped weapons and accessibility settings.
4. Faulty Flashlight dims only the player's lamp, leaves an off lamp off, and restores
   normal brightness. Check pause, cutscene, checkpoint reload and client shutdown.
5. Three 30-second copies last 90 playable seconds; menu/cutscene/mission-lock waits,
   reconnect and game restart preserve remaining time without duplicate receipts.
6. Two-player AP smoke test: correct useful/trap flags, notifications and journal resume.

Prior parked QTE/campaign/collectible/Ammo Supply/Progressive Tools validation remains
outstanding. This preview does not certify those tests or enable Progressive Tools.

## Live session 14 October 2026

The first preview DLL d03429926f61a01e crashed during Continue before any
reward/trap activation (game RVA 199bb95). The aim leaf's callers retain R8
across the call; a standard C detour clobbered that private calling convention.
That build is rejected before injection. Replacement 43255877b25169af preserves
the original volatile register/flag results around the effect helper. The actual
MinHook regression now also reproduces the caller retaining its pointer in R8.

On corrected DLL 43255877b25169af in the Suburbs, isolated from AP:
- Continue loaded successfully; ordinary gameplay and pause/options navigation worked.
- Parts 214 -> 239; paused request deferred and same receipt then applied once.
  Duplicate submission returned cached success, remaining at 239.
- Supplements 110 -> 120.
- Crafting Cache sugar 8 -> 12 quarters, five already-full materials stayed 12.
  A second cache at full capacity returned no-effect (retryable).
- Native maxima matched expected materials 12 and parts/supplements 9999.
- Faulty Flashlight visibly varied the beam brightness with the player's light on.
- Shaky Hands timer expired at exactly 30,000 ms; its visual/shot effect still
  needs an aiming test (computer input only reliably supports short button taps).
- Both clocks stayed unchanged through pause/options and a mission hold for over
  two minutes. Release resumed the clocks. Locked supplies returned no effect.
- No AP connection or real run ledger was used. Saves/AP state were backed up
  before testing. Checkpoint reload restored original resource counts.

- Restart Checkpoint returned to normal gameplay and restored the original inventory.
- A further flashlight trap ran with the lamp off; the lamp remained off at the
  end. Switching it on afterwards showed normal brightness. This was an endpoint
  observation, not continuous capture of the entire off-lamp interval.
- During another active flashlight trap, exiting the isolated driver cleared the
  effect mask/mode and visibly restored full beam brightness before expiry.
  The driver's local mmap alias then caused a teardown BufferError after cleanup;
  that test-helper alias was removed. The production client was not involved.
- The game was closed after testing to clear the experimental DLL.

Still pending: aim/shot alignment, controller/scoped/accessibility combinations,
actual cutscene suspension for both new effects, continuous off-lamp/expiry
observation, collectible pickup on this exact DLL, and two-player AP smoke test.
Keep normal-client admission disabled until remaining checks are sufficient.

### Manual aiming follow-up

On the same corrected DLL, in a fresh game process at the Suburbs checkpoint,
the player held aim and fired during an isolated 30-second Shaky Hands test.
They confirmed: "Sway and shots worked; normal afterward". Telemetry reached
exactly 30,000 ms and cleared effect_mask to zero; no native error was reported.
This passes the basic unscoped aiming/shot/recovery check. Controller, scoped
weapons, accessibility combinations and cutscene coverage remain unverified.

### Stronger sway revision

Following feedback that the original sway was too easy to counter, build
7ef795fe676cfb90 triples both displacement axes and increases oscillation speed
by 25%. It retains the corrected register-preserving hook, playable-time duration
and all eligibility guards. The native regression harness passed. The previous
live aiming confirmation applies to the milder build; this tuning awaits a fresh
live test and is not yet admitted to the normal client.

Follow-up on build 7ef795fe676cfb90: after restarting and loading the Suburbs
checkpoint, the player completed a 30-second isolated aiming test and reported
"Good strength; shots and recovery worked". Telemetry reached exactly 30,000 ms,
cleared the effect mask, and reported no native error. Keep this stronger tuning.
Basic unscoped aim, shot alignment and expiry recovery now pass on this build;
scoped/controller/accessibility combinations, cutscenes and multiplayer validation
remain outstanding. The isolated client was stopped after the test.

### Suburbs sniper DeathLink fix

Build 85087342ea250501 also contains the targeted sniper stabbing fix developed
in alpha38-hotfix1. Native regressions passed. The earlier stronger-sway live
result applies to 7ef795fe676cfb90; this combined build remains a preview pending
live coverage. See the Suburbs hotfix report for its separate live validation.

### Suburbs sniper-cover team failure

Build 458da239c79c4297 includes alpha38-hotfix2 handling for the observed team
failure task ef3d134138308c13. Native tests pass. This preview retains the stronger
Shaky Hands tuning and remains outside normal-client admission. See the hotfix2
report for the separate stable build live validation.

## Cabin Resort hunter-grab fix

Carries the exact mission-24/task-287c4dfeee8373a7 failure fix from alpha38-hotfix3.
Preview native build 805f4f917d342600 passes the native regression suite, including
duplicate, restart and no-echo exclusions. The corresponding stable build passed
the isolated live grab test; this combined preview build is not yet live-admitted.

## Cabin Resort Joel two-hunter struggle

Preview source also includes hotfix4: mission 24/task d29720961b0dd730, exact
task-fail! caller 235c9ae. Combined preview build e72504f2e92f5277 passes native
regressions but is not live-admitted. Stable ae3231d220955d44 passed one-event
isolated live validation, normal checkpoint reload and rearming.

## David strangling Ellie QTE

Preview source carries hotfix5 for mission 24/task a1b5df858fcc16bb and exact
task-fail! caller 235c9ae. Combined preview build bd6c618d05aa8add passes native
regressions but is not live-admitted. Stable 16812ed83c995090 passed isolated
one-event live validation and normal checkpoint recovery.

## Bus Depot Underground Tunnel water fall

Preview source carries hotfix6 for mission 26/task 42526a220348d020 and exact
task-fail! caller 235c9ae. Combined preview build c556124769671d94 passes native
regressions but is not live-admitted. Stable e2ca64782b4d6ce9 passed isolated
one-event live validation, normal checkpoint recovery and rearming. Scripted
Ellie/bus failure coverage remains unverified.

## Firefly Lab escape gunfire

Preview source carries hotfix7 for mission 27/task 1c9a2ef9f564b7ef and exact
caller 235c9ae. Combined preview build dad81bb760479ba5 passes native regressions
but is not live-admitted. Stable bdd56b87a7ef922c passed isolated one-event live
validation, normal checkpoint recovery and rearming. Earlier preview ZIPs have
not been rebuilt with this source change.

## Firefly escape capture variants

Preview source carries hotfix8 for mission 27/task 89a12fd5192d1361 and exact
caller 235c9ae. All three recorded NPC variants share this task. Combined
preview build 131d69156041a466 passes native regressions but remains unadmitted.
Stable 402f75f8c0acb00d passed all three isolated live retests with one local
event/notification per attempt and live rearming after each reload. Preview
ZIPs have not been rebuilt with this change.
