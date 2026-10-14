# The Last of Us Part I — Archipelago

Windows main-story integration for **The Last of Us Part I 1.1.3.0 AVX2**.
Current release: **v0.1.0**. Left Behind is not supported.

## Installation

Install `tlou_part1.apworld` through Archipelago Launcher and restart it.
Open **The Last of Us Part I Client**: the APWorld includes the standalone
Windows client and installs it locally on first launch. The client uses the
game icon. A standalone ZIP is also available.

See [setup and updating](tlou_ap/docs/setup_en.md), including migration of
existing portable runs. Back up saves and run records before updating.

## Features

- 29 mission checks, 12 chapter checks and 140 collectible checks.
- Progressive Chapter Unlock, with menu access while a mission is locked.
- Ammo, shivs, health kits, crafting materials, parts, supplements and bonus tools.
- Airhorn, Shaky Hands (including scoped aiming) and Faulty Flashlight traps.
- Queued DeathLink, including tested fatal QTE and companion-failure events.
- Managed runs, save compatibility guidance, tracker, themes and transfer cards.

[Release notes](RELEASE_NOTES.md) describe the release and known limits.
The campaign, collectibles and remaining acceptance checklist have been player-tested.
See [validation](tlou_ap/docs/validation_release.md) for automated and player-reported evidence.
Persistent offline crash recovery is deferred.

## Development

Python 3.12 on Windows. Install with `python -m pip install -e .[research,bundle]`.
Run `python -m unittest discover -s tests` for the isolated Python suite.
See [building and release checks](docs/RELEASING.md) for the native build,
APWorld integration tests and reproducible packaging order.

Source code is under [MIT](LICENSE). Third-party libraries, game-identification
artwork and optional licensed sounds retain their own terms; see
[third-party notices](THIRD_PARTY_NOTICES.txt). No game executable, saves or
proprietary game archives are included.
