# v0.1.0 validation — 14 October 2026

Supported game: The Last of Us Part I 1.1.3.0 AVX2 on Windows, main story.
Native build: `6e6140cbbafa3886`, ABI 5. This is the tested scoped-aiming bridge;
release packaging does not change its native code.

## Automated and instrumented checks

- 293 isolated Python tests passed, including a clean source export.
- Native command/gate harness passed for the admitted native build.
- Official AP 0.6.9: all 83 valid check-category/start combinations fill,
  are beatable and accessible; tracker logic matches every unlock stage.
- Additional seeds, DeathLink, Airhorn modes/durations/percentages, mixed-player
  settings, supplies, tools and timed-trap pool checks passed.
- Both packaged clients passed resource/native fingerprint, UI, transfer flags,
  persistence and loopback-network self-tests without attaching to the game.
- APWorld launched the executable through an isolated installed AP 0.6.8 runtime,
  reused its cache on relaunch and passed the extracted executable self-test.
- Installed client entry and game icon were visually checked. Existing run
  records migrated without alteration to the shared LocalAppData profile.

## Player-confirmed acceptance

The full campaign and all collectible checks passed the player's playthrough.
Mission gates preserve menus; tested fatal QTE/companion failures send DeathLink,
and the prologue's scripted story death is excluded. Queued supplies, DeathLink
and Airhorn wait through the tested cutscene and resume on player control.

The player confirmed multi-run switching, the combined networked build, run
deletion, ammo thresholds, normal toolbox compatibility, tool cap, controller
and scoped Shaky Hands, flashlight recovery, and trap clearing on death.
Earlier instrumented and player-test details remain in validation_alpha40.md.

On 14 October 2026 the player confirmed the final three outstanding tests passed
without issues:

1. AP tool upgrades restore after loading an older save with a lower tool level.
2. Shaky Hands and Faulty Flashlight suspend during a normal cutscene and resume.
3. Shaky Hands works with aiming accessibility settings.

These final three are player-reported results, not new instrumented captures.
The release acceptance checklist is complete for the supported build.

## Scope and limits

Left Behind, other executable builds and persistent offline crash recovery are
not supported. Interrupted supply deliveries with ambiguous outcomes remain
held to avoid duplication. Keep the client running during temporary network
disconnections. Restart the game when changing managed runs or leaving a test
session. Passing this checklist is not a guarantee that every possible game
configuration or unrecorded failure sequence has been exercised.
