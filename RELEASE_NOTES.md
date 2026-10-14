# v0.1.0

First release for Windows game version 1.1.3.0 AVX2, main story only.

## Install

Download `tlou_part1.apworld`, install it through Archipelago Launcher, and restart
the launcher. Open **The Last of Us Part I Client**; the APWorld includes the
executable and installs it on first launch. A standalone Windows ZIP is also
provided. Follow `tlou_ap/docs/setup_en.md` when migrating an existing portable run.

## Included

- 181 checks: 29 missions, 12 chapters and 140 collectibles, with configurable check categories.
- Progressive Chapter Unlock and a mission lock that retains pause-menu access.
- Ammo Supply, Shiv, Health Kit, Crafting Cache, Workbench Parts, Supplement Stash and bonus Progressive Tools.
- Airhorn, Shaky Hands and Faulty Flashlight traps, with safe delivery queues and clearing on death.
- DeathLink, managed runs, save compatibility guidance, a mission/check tracker,
  light/dark themes and configurable in-game notifications.

## Release preparation

- APWorld now contains and registers the standalone client in Archipelago Launcher.
- Client cache upgrades preserve managed runs in a shared LocalAppData profile.
- Portable legacy profiles migrate once, without overwriting an existing profile.
- Game icon applied to the executable, client window and Archipelago Launcher entry.
- Scoped Shaky Hands fix passed live controller testing, aim-mode switching and recovery.
- Tool level-5 cap, normal toolbox compatibility, run switching and delete-run UI passed.

## Validation

All 293 isolated Python tests passed, along with world generation, multiplayer
logic and packaged-client checks. The bundled APWorld launched through the
installed Archipelago runtime and reused its verified client on a second launch.

Full campaign and collectible coverage is player-confirmed. The player also
confirmed the final checks passed without issues: AP tool restoration after
loading an older lower-level save, Shaky Hands/Faulty Flashlight cutscene
suspension, and aiming accessibility settings. These final three are
player-reported results, not additional instrumented captures.

## Known limits

Left Behind and persistent offline crash recovery are not supported. The client
requires the exact supported Windows executable. Keep it running during temporary
server disconnections; restart the game when changing managed runs or leaving
the isolated test lab. An ambiguous interrupted supply delivery is held rather
than automatically duplicated. The removed reward-retirement UI has no replacement
self-service recovery action in this release.
