# Alpha 10 validation

This release changes the launcher and tracker only. Native ABI 2 and bridge
build `99d6c0864e316360` remain unchanged. Existing alpha 8 live evidence is
retained in `dist/gate-validation.json`.

## Automated checks

- Shared Light/Dark themes update launcher, tracker, dropdowns, tables and logs.
- Theme selection persists across a fresh launcher and retains connection and
  notification settings. Closing/reopening the tracker retains the current theme.
- Available checks exclude earned/confirmed checks and enforce actual mission
  order. Chapter completion becomes available at the chapter's last mission.
- Checks in logic match the official Archipelago 0.6.9 world at every chapter
  unlock stage across all 83 valid options, plus additional seeds.
- Disabled categories are excluded from all relevant totals. Chapter overview
  still lists all 12 main chapters, including chapters with zero enabled checks.
- Disconnection and pending item synchronization show unknown access, including
  when a previously connected snapshot remains on screen.
- Search, category, status and access filters compose without changing progress.
- Standalone and source packages run isolated UI, journal and WebSocket smoke tests.

The full Python suite has 99 passing tests. Prior native tests and live game
evidence are unchanged; no new campaign validation is claimed by these UI tests.
The development workspace retains artifact hashes and results in
`dist/validation.json` and `dist/standalone-validation.json`.

## Gameplay tests still pending

Natural outgoing DeathLinks, actual cinematics and scripted scenes, live queue
persistence through restarts, later mission boundaries, the remaining collectible
and firearm catalog, a complete multiworld campaign, and installation on a second
Windows machine remain the outstanding release tests. See the retained
`validation_alpha9.md` for their pass conditions. Weapons, traps and new check
categories are not part of this release.
